from __future__ import with_statement
from optparse import make_option, OptionParser
import datetime, time
import os
import sys
import urllib2
import warnings
import random
from hashlib import md5
import cookielib
import contextlib
from BeautifulSoup import BeautifulSoup
try:
    import json
except ImportError:
    import simplejson as json

class ScrapeError(Exception):
    """
    Base class for scrape errors.
    """
    pass


class NoDataForYear(ScrapeError):
    """
    Exception to be raised when no data exists for a given year
    """

    def __init__(self, year):
        self.year = year

    def __str__(self):
        return 'No data exists for %s' % self.year

class DateEncoder(json.JSONEncoder):
    """
    JSONEncoder that encodes datetime objects as Unix timestamps.
    """
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return time.mktime(obj.timetuple())
        return json.JSONEncoder.default(self, obj)

class LegislationScraper(object):
    """Subclass for each state's scraper

    Subclasses must define :method:`scrape_bills` and the attribute
    `state`

    Put this at the top of your scripts::

        import sys, os
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    """
    
    option_list = (
        make_option('-y', '--year', action='append', dest='years',
                    help='year(s) to scrape'),
        make_option('--all', action='store_true', dest='all_years',
                    default=False, help='scrape all data (overrides --year)'),
        make_option('--upper', action='store_true', dest='upper',
                    default=False, help='scrape upper chamber'),
        make_option('--lower', action='store_true', dest='lower',
                    default=False, help='scrape lower chamber'),
        make_option('-v', '--verbose', action='count', dest='verbose',
                    default=False, help="be verbose (use multiple times for more debugging information)"),
        make_option('-d', '--output_dir', action='store', dest='output_dir',
                    help='output directory'),
        make_option('-n', '--no_cache', action='store_true', dest='no_cache',
                    help="don't use web page cache"),
        make_option('-s', '--sleep', action='store_true', dest='sleep',
                    help="insert random delays wheen downloading web pages"),
    )
    cache_dir = 'cache'
    output_dir = None

    metadata = {}

    # The earliest year for when legislative data is available:
    # (Used for --all)
    earliest_year = 1969
    
    # The user agent used for requests (this will show up in the
    # state's logs):
    user_agent = 'robot: http://wiki.sunlightlabs.com/index.php/Fifty_State_Project'

    def __init__(self):
        if not hasattr(self, 'state'):
            raise Exception('LegislationScrapers must have a state attribute')
        self._cookie_jar = cookielib.CookieJar()

    def urlopen(self, url):
        """
        Grabs a URL, returning a cached version if available.
        """

        if not self.no_cache:
            url_cache = os.path.join(self.cache_dir, self.state,
                                     md5(url).hexdigest()+'.html')
            if os.path.exists(url_cache):
                self.debug('Getting %s from cache' % url)
                return open(url_cache).read()

        if self.sleep:
            # insert a short random delay before each request
            # and a longer random delay after some requests
            self.requests += 1

            if self.requests >= 50:
                len = random.randint(10, 15)
                self.requests = 0
                self.debug("Long sleep: %d seconds" % len)
            else:
                len = random.uniform(1, 4)
                self.debug("Short sleep: %f seconds" % len)

            time.sleep(len)

        self.log('Retrieving URL: %s' % url)
        req = urllib2.Request(url, headers=self._make_headers())
        self._cookie_jar.add_cookie_header(req)
        try:
            resp = urllib2.urlopen(req)
        except:
            print 'Error fetching page: %s' % url
            raise
        self._cookie_jar.extract_cookies(resp, req)
        data = resp.read()

        if not self.no_cache:
            open(url_cache, 'w').write(data)

        return data

    def show_error(self, url, body):
        exception = sys.exc_info()[1]
        if isinstance(exception, urllib2.HTTPError):
            print 'Error body:'
            print exception.read()
        print 'Error while parsing %s' % url
        fn = 'error-page.html'
        n = 0
        while os.path.exists(fn):
            n += 1
            fn = 'error-page-%s.html'% n
        fp = open(fn, 'wb')
        fp.write(body)
        fp.close()
        print 'Bad page saved in %s' % fn

    @contextlib.contextmanager
    def urlopen_context(self, url):
        """
        Use like::

            from __future__ import with_statement

            class State(LegislationScraper):
                def something(self):
                    with self.urlopen_context(url) as page:
                        use the page

        When opening a page like this, if there is any error then the
        page and the URL where this error occurred with be saved and
        a better error message is presented.
        """
        body = self.urlopen(url)
        try:
            yield body
        except:
            self.show_error(url, body)
            raise

    @contextlib.contextmanager
    def soup_context(self, url):
        """
        Like :method:`urlopen_context`, except returns a BeautifulSoup
        parsed document.
        """
        body = self.urlopen(url)
        soup = BeautifulSoup(body)
        try:
            yield soup
        except:
            self.show_error(url, body)
            raise
        
    def _make_headers(self):
        return {'User-Agent': self.user_agent}

    def log(self, msg):
        """
        Output debugging information if verbose mode is enabled.
        """
        if self.verbose:
            self._log(msg)

    def debug(self, msg):
        if self.verbose > 1:
            self._log(msg)

    def _log(self, msg):
        if isinstance(msg, unicode):
            msg = msg.encode('utf-8')
        print "%s: %s" % (self.state, msg)

    def init_dirs(self):

        def makedir(path):
            try:
                os.makedirs(path)
            except OSError, e:
                if e.errno != 17 or os.path.isfile(self.output_dir):
                    raise e

        makedir(os.path.join(self.output_dir, "bills"))
        makedir(os.path.join(self.output_dir, "legislators"))
        makedir(os.path.join(self.cache_dir, self.state))

    def scrape_metadata(self):
        """
        Grab metadata about this state's legislature.
        """
        return self.metadata

    def scrape_legislators(self, chamber, year):
        """
        Grab all the legislators who served in a given year.

        Should raise a :class:`NoDataForYear` exception if the year is invalid.
        """
        pass

    def scrape_bills(self, chamber, year):
        """
        Grab all the bills for a given chamber and year.

        Should raise a :class:`NoDataForYear` exception if the year is invalid.
        """
        raise NotImplementedError('LegislationScrapers must define a '
                                  'scrape_bills method')

    def add_bill(self, bill):
        """
        Add a scraped :class:`pyutils.legislation.Bill` object.
        """
        self.log("add_bill %s %s: %s" % (bill['chamber'],
                                         bill['session'],
                                         bill['bill_id']))

        # Associate each recorded vote with an actual legislator
        for vote in bill['votes']:
            for type in ['yes_votes', 'no_votes', 'other_votes']:
                vote[type] = map(lambda l:
                                 {'name': l,
                                  'leg_id': self.matcher[vote['chamber']][l]},
                                 vote[type])

        for sponsor in bill['sponsors']:
            if 'chamber' in sponsor:
                leg_id = self.matcher[sponsor['chamber']][sponsor['name']]
            else:
                leg_id = self.matcher[bill['chamber']][sponsor['name']]

            sponsor['leg_id'] = leg_id

        bill['state'] = self.state

        filename = "%s:%s:%s.json" % (bill['session'], bill['chamber'],
                                      bill['bill_id'])
        filename = filename.encode('ascii', 'replace')
        with open(os.path.join(self.output_dir, "bills", filename), 'w') as f:
            json.dump(bill, f, cls=DateEncoder)

    def add_legislator(self, legislator):
        """
        Add a scraped :class:`pyutils.legislation.Legislator` object.
        """
        self.log("add_legislator %s %s: %s" % (legislator['chamber'],
                                               legislator['session'],
                                               legislator['full_name']))

        self.matcher[legislator['chamber']][legislator] = [
            legislator['session'],
            legislator['chamber'],
            legislator['district'],
            legislator['full_name']]

        legislator['state'] = self.state

        filename = "%s:%s:%s:%s.json" % (legislator['session'],
                                         legislator['chamber'],
                                         legislator['district'],
                                         legislator['full_name'])
        filename = filename.encode('ascii', 'replace')
        with open(os.path.join(self.output_dir, "legislators", filename),
                  'w') as f:
            json.dump(legislator, f, cls=DateEncoder)

    def write_metadata(self):
        metadata = self.scrape_metadata()
        metadata['state'] = self.state

        with open(os.path.join(self.output_dir, 'state_metadata.json'),
                  'w') as f:
            json.dump(metadata, f, cls=DateEncoder)

    def run(self):
        parser = OptionParser(
            option_list=self.option_list)
        options, spares = parser.parse_args()

        self.verbose = options.verbose
        self.no_cache = options.no_cache
        self.sleep = options.sleep
        self.requests = 0

        if options.output_dir:
            self.output_dir = options.output_dir
        else:
            self.output_dir = os.path.join(os.path.curdir, "data",
                                           self.state)
        self.init_dirs()
        self.write_metadata()

        years = options.years
        if options.all_years:
            years = [str(y) for y in range(self.earliest_year,
                                           datetime.datetime.now().year+1)]
        if not years:
            parser.error("You must provide a --year YYYY or --all (all years) option")
            
        chambers = []
        if options.upper:
            chambers.append('upper')
        if options.lower:
            chambers.append('lower')
        if not chambers:
            chambers = ['upper', 'lower']
        for year in years:
            self.matcher = {'upper': NameMatcher(), 'lower': NameMatcher()}
            for chamber in chambers:
                try:
                    self.old_bills = {}

                    self.scrape_legislators(chamber, year)
                    self.scrape_bills(chamber, year)
                except NoDataForYear, e:
                    if options.all_years:
                        pass
                    else:
                        raise


class Bill(dict):
    """
    This represents a state bill or resolution.
    It is just a dict with some required fields and a few
    convenience methods. Any key/value pairs stored in it besides the
    required fields will be saved and stored in the backend database
    for later use.
    """

    def __init__(self, session, chamber, bill_id, title, **kwargs):
        """
        Create a new :obj:`Bill`.

        :param session: the session in which the bill was introduced.
        :param chamber: the chamber in which the bill was introduced:
          either 'upper' or 'lower'
        :param bill_id: an identifier assigned by the state to this bill
          (should be unique within the context of this chamber/session)
          e.g.: 'HB 1', 'S. 102', 'H.R. 18'
        :param title: a title or short description of this bill provided by
          the state

        Any additional keyword arguments will be associated with this
        bill and stored in the database.
        """
        self['type'] = 'bill'
        self['session'] = session
        self['chamber'] = chamber
        self['bill_id'] = bill_id
        self['title'] = title
        self['sponsors'] = []
        self['votes'] = []
        self['versions'] = []
        self['actions'] = []
        self['documents'] = []
        self['sources'] = []
        self.update(kwargs)

    def add_sponsor(self, type, name, **kwargs):
        """
        Associate a sponsor with this bill.

        :param type: the type of sponsorship, e.g. 'primary', 'cosponsor'
        :param name: the name of the sponsor as provided by the state
        """
        self['sponsors'].append(dict(type=type, name=name, **kwargs))

    def add_source(self, url, **kwargs):
        """
        Add a source URL from which data related to this bill was scraped.

        :param url: the location of the source
        """
        self['sources'].append(dict(url=url, **kwargs))

    def add_document(self, name, url, **kwargs):
        """
        Add a document or media item that is related to the bill.  Use this method to add documents such as Fiscal Notes, Analyses, Amendments,  or public hearing recordings.
        :param name: a name given to the document, e.g. 'Fiscal Note for Amendment LCO 6544'        
        :param url: link to location of document or file


          If multiple formats of a document are provided, a good rule of thumb is to prefer text, followed by html, followed by pdf/word/etc.
        """
        self['documents'].append(dict(name=name, url=url, **kwargs))

    def add_version(self, name, url, **kwargs):
        """
        Add a version of the text of this bill.

        :param name: a name given to this version of the text, e.g. 'As Introduced',
          'Version 2', 'As amended', 'Enrolled'
        :param url: the location of this version on the state's legislative website.
          If multiple formats are provided, a good rule of thumb is to
          prefer text, followed by html, followed by pdf/word/etc.
        """
        self['versions'].append(dict(name=name, url=url, **kwargs))

    def add_action(self, actor, action, date, **kwargs):
        """
        Add an action that was performed on this bill.

        :param actor: a string representing who performed the action.
          If the action is associated with one of the chambers this
          should be 'upper' or 'lower'. Alternatively, this could be
          the name of a committee, a specific legislator, or an outside
          actor such as 'Governor'.
        :param action: a string representing the action performed, e.g. 'Introduced',
          'Signed by the Governor', 'Amended'
        :param date: the date/time this action was performed.
        """

        self['actions'].append(dict(actor=actor, action=action,
                                    date=date, **kwargs))

    def add_vote(self, vote):
        """
        Associate a :class:`pyutils.legislation.Vote` object with this bill.
        """
        self['votes'].append(vote)


class Vote(dict):

    def __init__(self, chamber, date, motion, passed,
                 yes_count, no_count, other_count, **kwargs):
        """
        Create a new :obj:`Vote`.

        :param chamber: the chamber in which the vote was taken, 'upper' or 'lower'
        :param date: the date/time when the vote was taken
        :param motion: a string representing the motion that was being voted on
        :param passed: did the vote pass, True or False
        :param yes_count: the number of 'yes' votes
        :param no_count: the number of 'no' votes
        :param other_count: the number of abstentions, 'present' votes, or anything
          else not covered by 'yes' or 'no'.

        Any additional keyword arguments will be associated with this
        vote and stored in the database.

        Examples: ::

          Vote('upper', '', '12/7/08', 'Final passage',
               True, 30, 8, 3)
          Vote('lower', 'Finance Committee', '3/4/03 03:40:22',
               'Recommend passage', 12, 1, 0)
        """
        self['chamber'] = chamber
        self['date'] = date
        self['motion'] = motion
        self['passed'] = passed
        self['yes_count'] = yes_count
        self['no_count'] = no_count
        self['other_count'] = other_count
        self['yes_votes'] = []
        self['no_votes'] = []
        self['other_votes'] = []
        self['sources'] = []
        self.update(kwargs)

    def yes(self, legislator):
        """
        Indicate that a legislator (given as a string of their name) voted
        'yes'.

        Examples: ::

           vote.yes('Smith')
           vote.yes('Alan Hoerth')
        """
        self['yes_votes'].append(legislator)

    def no(self, legislator):
        """
        Indicate that a legislator (given as a string of their name) voted
        'no'.
        """
        self['no_votes'].append(legislator)

    def other(self, legislator):
        """
        Indicate that a legislator (given as a string of their name) abstained,
        voted 'present', or made any other vote not covered by 'yes' or 'no'.
        """
        self['other_votes'].append(legislator)

    def add_source(self, url, **kwargs):
        """
        Add a source URL from which data related to this vote was scraped.

        :param url: the location of the source
        """
        self['sources'].append(dict(url=url, **kwargs))

class Legislator(dict):

    def __init__(self, session, chamber, district, full_name,
                 first_name, last_name, middle_name, party, **kwargs):
        """
        Create a Legislator.

        :param session: the session in which this legislator served
        :param chamber: the chamber in which this legislator served, 'upper' or 'lower'
        :param district: the district this legislator is representing, as given
          by the state, e.g. 'District 2', '7th', 'District C'.
        :param full_name: the full name of this legislator
        :param first_name: the first name of this legislator
        :param last_name: the last name of this legislator
        :param middle_name: a middle name or initial of this legislator, blank
          if none is provided
        :param party: the party this legislator belongs to

        Any additional keyword arguments will be associated with this
        Legislator and stored in the database.
        """
        self['type'] = 'legislator'
        self['session'] = session
        self['chamber'] = chamber
        self['district'] = district
        self['full_name'] = full_name
        self['first_name'] = first_name
        self['last_name'] = last_name
        self['middle_name'] = middle_name
        self['party'] = party
        self['sources'] = []
        self.update(kwargs)

    def add_source(self, url, **kwargs):
        """
        Add a source URL from which data related to this legislator was scraped.

        :param url: the location of the source
        """
        self['sources'].append(dict(url=url, **kwargs))

class NameMatcher(object):
    """
    Match various forms of a name, provided they uniquely identify
    a person from everyone else we've seen.

    Given the name object:
     {'fullname': 'Michael J. Stephens', 'first_name': 'Michael',
      'last_name': 'Stephens', 'middle_name': 'Joseph'}
    we will match these forms:
     Michael J. Stephens
     Michael Stephens
     Stephens
     Stephens, Michael
     Stephens, M
     Stephens, Michael Joseph
     Stephens, Michael J
     Stephens, M J
     M Stephens
     M J Stephens
     Michael Joseph Stephens

    Tests:

    >>> nm = NameMatcher()
    >>> nm[{'fullname': 'Michael J. Stephens', 'first_name': 'Michael', \
            'last_name': 'Stephens', 'middle_name': 'J'}] = 1
    >>> assert nm['Michael J. Stephens'] == 1
    >>> assert nm['Stephens'] == 1
    >>> assert nm['Michael Stephens'] == 1
    >>> assert nm['Stephens, M'] == 1
    >>> assert nm['Stephens, Michael'] == 1
    >>> assert nm['Stephens, M J'] == 1

    Add a similar name:

    >>> nm[{'fullname': 'Mike J. Stephens', 'first_name': 'Mike', \
            'last_name': 'Stephens', 'middle_name': 'Joseph'}] = 2

    Unique:

    >>> assert nm['Mike J. Stephens'] == 2
    >>> assert nm['Mike Stephens'] == 2
    >>> assert nm['Michael Stephens'] == 1

    Not unique anymore:

    >>> assert nm['Stephens'] == None
    >>> assert nm['Stephens, M'] == None
    >>> assert nm['Stephens, M J'] == None
    """

    def __init__(self):
        self.names = {}

    def __setitem__(self, name, obj):
        """
        Expects a dictionary with fullname, first_name, last_name and
        middle_name elements as key.

        While this can grow quickly, we should never be dealing with
        more than a few hundred legislators at a time so don't worry about
        it.
        """
        # We throw possible forms of this name into a set because we
        # don't want to try to add the same form twice for the same
        # name
        forms = set()
        forms.add(name['full_name'])
        forms.add(name['last_name'])
        forms.add("%s, %s" % (name['last_name'], name['first_name']))
        forms.add("%s %s" % (name['first_name'], name['last_name']))
        forms.add("%s %s" % (name['first_name'][0], name['last_name']))
        forms.add("%s, %s" % (name['last_name'], name['first_name'][0]))
        forms.add("%s (%s)" % (name['last_name'], name['first_name']))

        if len(name['middle_name']) > 0:
            forms.add("%s, %s %s" % (name['last_name'], name['first_name'],
                                     name['middle_name']))
            forms.add("%s, %s %s" % (name['last_name'], name['first_name'][0],
                                     name['middle_name']))
            forms.add("%s %s %s" % (name['first_name'], name['middle_name'],
                                    name['last_name']))
            forms.add("%s, %s %s" % (name['last_name'], name['first_name'][0],
                                     name['middle_name'][0]))
            forms.add("%s %s %s" % (name['first_name'], name['middle_name'][0],
                                    name['last_name']))
            forms.add("%s, %s %s" % (name['last_name'], name['first_name'],
                                     name['middle_name'][0]))

        for form in forms:
            form = form.replace('.', '').lower()
            if form in self.names:
                self.names[form] = None
            else:
                self.names[form] = obj

    def __getitem__(self, name):
        name = name.strip().replace('.', '').lower()
        if name in self.names:
            return self.names[name]
        return None
