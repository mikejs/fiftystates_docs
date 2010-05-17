from __future__ import with_statement
from optparse import make_option, OptionParser
import datetime
import time
import os
import sys
import urllib2
import urlparse
import random
import contextlib
import logging
import warnings
from names import NameMatcher

try:
    from BeautifulSoup import BeautifulSoup
    USE_SOUP = True
except ImportError:
    print "BeautifulSoup not found, LegislationScraper.soup_context will " \
        "be unavailable"
    USE_SOUP = False

try:
    import lxml.html
    USE_LXML = True
except ImportError:
    print "lxml not found, LegislationScraper.lxml_context will " \
        "be unavailable"
    USE_LXML = False

try:
    import httplib2
    USE_HTTPLIB2 = True
except ImportError:
    print "httplib2 not found, falling back to urllib2"
    USE_HTTPLIB2 = False

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

    Subclasses should define :meth:`scrape_bills`,
    :meth:`scrape_legislators`, and :attr:`metadata` and
    :attr:`state` attributes.

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
        make_option('--nolegislators', action='store_false', dest='legislators',
                    default=True, help="don't scrape legislator data"),
        make_option('-v', '--verbose', action='count', dest='verbose',
                    default=False,
                    help="be verbose (use multiple times for more"\
                        "debugging information)"),
        make_option('-d', '--output_dir', action='store', dest='output_dir',
                    help='output directory'),
        make_option('-n', '--no_cache', action='store_true', dest='no_cache',
                    help="don't use web page cache"),
        make_option('-s', '--sleep', action='store_true', dest='sleep',
                    help="insert random delays wheen downloading web pages"),
    )

    metadata = {}

    # The earliest year for which legislative data is available in
    # any state (used for --all)
    earliest_year = 1969

    # The user agent used for requests (this will show up in the
    # state's logs):
    user_agent = 'robot: http://fiftystates-dev.sunlightlabs.com/'

    def __init__(self, verbosity=logging.INFO, sleep=False,
                 no_cache=False, output_dir=None, **kwargs):
        """
        Create a new LegislationScraper instance.

        :param verbosity: minimum level of messages to log (from the
          Python standard library's :mod:`logging` module)
        :param sleep: if True, will insert random sleeps between attempts
          to download pages
        :param no_cache: if True, will ignore any cached downloads
        :param output_dir: the Fifty State data directory to use
        """
        if not hasattr(self, 'state'):
            raise Exception('LegislationScrapers must have a state attribute')

        self.reset_name_matchers()

        self.sleep = sleep
        self.no_cache = no_cache
        self.requests = 0

        self.output_dir = output_dir or os.path.join('data', self.state)
        self.cache_dir = os.path.join('cache', self.state)
        self.error_dir = os.path.join('errors', self.state)
        self._init_dirs()

        self.logger = logging.getLogger("fiftystates")
        formatter = logging.Formatter("%(asctime)s %(levelname)s " +
                                      self.state + " %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self.logger.addHandler(console)
        self.logger.setLevel(verbosity)

        if USE_HTTPLIB2:
            if self.no_cache:
                self.http = httplib2.Http()
            else:
                self.http = httplib2.Http(self.cache_dir)
            self.http.follow_redirects = True

        # Convenience methods
        self.log = self.logger.info
        self.debug = self.logger.debug
        self.warning = self.logger.warning

    def urlopen(self, url):
        """
        Grabs a URL, returning a cached version if available and
        sleeping if necessary.
        """
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

        parsed = urlparse.urlparse(url)
        if parsed.scheme in ['http', 'https'] and USE_HTTPLIB2:
            try:
                resp, content = self.http.request(
                    url, "GET", headers=self._make_headers())

                # raise a urllib2.HTTPError so underlying code can rely on it
                if resp.status >= 400:
                    raise urllib2.HTTPError(url, resp.status, resp.reason,
                                            resp.items, None)
            except:
                self.logger.exception('Error fetching page: %s' % url)
                raise

            if resp.fromcache:
                self.log("Got %s (httplib2, cached)" % url)
            else:
                self.log("Got %s (httplib2)" % url)

            return content
        else:
            # Use urllib2 for non-http requests (e.g. ftp)
            req = urllib2.Request(url, headers=self._make_headers())
            try:
                resp = urllib2.urlopen(req)
            except:
                self.logger.exception("Error fetching page: %s" % url)
                raise

            self.log("Got %s (urllib2)" % url)

            return resp.read()

    def show_error(self, url, body):
        exception = sys.exc_info()[1]
        if isinstance(exception, urllib2.HTTPError):
            self.logger.error('Error body:')
            self.logger.error(exception.read())
        self.logger.error('Error while parsing %s' % url)
        path = os.path.join(self.error_dir, 'error-page.html')
        n = 0
        while os.path.exists(path):
            n += 1
            path = os.path.join(self.error_dir, 'error-page-%s.html' % n)
        fp = open(path, 'wb')
        fp.write(body)
        fp.close()
        self.logger.error('Bad page saved in %s' % path)

    @contextlib.contextmanager
    def urlopen_context(self, url):
        """
        Use like: ::

           from __future__ import with_statement

           class State(LegislationScraper):
               def something(self):
                   with self.urlopen_context(url) as page:
                       do_stuff(page)

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
        if not USE_SOUP:
            raise ScrapeError("BeautifulSoup does not seem to be installed.")

        body = self.urlopen(url)
        soup = BeautifulSoup(body)

        try:
            yield soup
        except:
            self.show_error(url, body)
            raise

    @contextlib.contextmanager
    def lxml_context(self, url):
        """
        Like :meth:`urlopen_context`, except returns an lxml parsed
        document.
        """
        if not USE_LXML:
            raise ScrapeError("lxml does not seem to be installed.")

        body = self.urlopen(url)
        elem = lxml.html.fromstring(body)

        try:
            yield elem
        except:
            self.show_error(url, body)
            raise

    def _make_headers(self):
        return {'User-Agent': self.user_agent}

    def _init_dirs(self):

        def makedir(path):
            try:
                os.makedirs(path)
            except OSError, e:
                if e.errno != 17 or os.path.isfile(self.output_dir):
                    raise e

        makedir(os.path.join(self.output_dir, "bills"))
        makedir(os.path.join(self.output_dir, "legislators"))
        makedir(self.cache_dir)
        makedir(self.error_dir)

    def scrape_metadata(self):
        """
        Grab metadata about this state's legislature. Should return a
        dictionary with at least the following attributes:

        * `state_name`: the full name of this state, e.g. New Hampshire
        * `legislature name`: the name of this state's legislative body, e.g.
          `"Texas Legislature"`
        * `upper_chamber_name`: the name of the upper chamber of this state's
           legislature, e.g. `"Senate"`
        * `lower_chamber_name`: the name of the lower chamber of this
           state's legislature, e.g. `"House of Representatives"`
        * `upper_title`: the title of a member of this state's upper chamber,
           e.g. `"Senator"`
        * `lower_title`: the title of a member of this state's lower chamber,
           e.g. `"Representative"`
        * `upper_term`: the length, in years, of a term in this state's
           upper chamber, e.g. `4`
        * `lower_term`: the length, in years, of a term in this state's
           lower chamber, e.g. `2`
        * `sessions`: an ordered list of available sessions, e.g.
           `['2005-2006', '2007-2008', '2009-2010']
        * `session_details`: a dictionary, with an entry for each session
          indicating the years it encompasses as well as any 'sub' sessions,
          e.g.::

           {'2009-2010': {'years': [2009, 2010],
                          'sub_sessions': ["2009 Special Session 1"]}}

        """
        return self.metadata

    def scrape_legislators(self, chamber, year):
        """
        Grab all the legislators who served in a given year. Must be
        overridden by subclasses.

        Should raise a :class:`NoDataForYear` exception if the year is invalid.
        """
        pass

    def scrape_bills(self, chamber, year):
        """
        Grab all the bills for a given chamber and year. Must be
        overridden by subclasses.

        Should raise a :class:`NoDataForYear` exception if the year is invalid.
        """
        raise NotImplementedError('LegislationScrapers must define a '
                                  'scrape_bills method')

    def add_bill(self, bill):
        warnings.warn("add_bill renamed save_bill", DeprecationWarning)
        self.save_bill(bill)

    def save_bill(self, bill):
        """
        Save a scraped :class:`pyutils.legislation.Bill` object. Only
        call after all data for the given bill has been collected.
        """
        self.log("save_bill %s %s: %s" % (bill['chamber'],
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

        filename = "%s_%s_%s.json" % (bill['session'], bill['chamber'],
                                      bill['bill_id'])
        filename = filename.encode('ascii', 'replace')
        with open(os.path.join(self.output_dir, "bills", filename), 'w') as f:
            json.dump(bill, f, cls=DateEncoder)

    def add_person(self, person):
        warnings.warn("add_person renamed save_person", DeprecationWarning)
        self.save_person(person)

    def save_person(self, person):
        """
        Save a scraped :class:`pyutils.legislation.Person` object. Only
        call after all data for the given person has been collected.

        Should be used for non-legislator people (e.g. Governor, Lt. Gov).
        To add :class:`pyutils.legislation.Legislator` objects call
        :meth:`pyutils.legislation.save_legislator`.
        """
        self.log("save_person: %s" % person['full_name'])

        person['state'] = self.state

        role = person['roles'][0]
        filename = "%s_%s.json" % (role['session'],
                                   person['full_name'])
        filename = filename.encode('ascii', 'replace')

        with open(os.path.join(self.output_dir, "legislators", filename),
                  'w') as f:
            json.dump(person, f, cls=DateEncoder)

    def add_legislator(self, legislator):
        warnings.warn("add_legislator renamed save_legislator",
                      DeprecationWarning)
        self.save_legislator(legislator)

    def save_legislator(self, legislator):
        """
        Save a scraped :class:`pyutils.legislation.Legislator` object.
        Only call after all data for the given legislator has been collected.
        """
        self.log("save_legislator: %s" % legislator['full_name'])

        role = legislator['roles'][0]
        self.matcher[role['chamber']][legislator] = [
            role['session'],
            role['chamber'],
            role['district'],
            legislator['full_name']]

        legislator['state'] = self.state

        filename = "%s_%s_%s_%s.json" % (role['session'],
                                         role['chamber'],
                                         role['district'],
                                         legislator['full_name'])
        filename = filename.encode('ascii', 'replace')
        with open(os.path.join(self.output_dir, "legislators", filename),
                  'w') as f:
            json.dump(legislator, f, cls=DateEncoder)

    def _save_standalone_vote(self, vote):
        filename = vote["filename"] + ".json"
        self.log("_save_standalone_vote %s %s: %s '%s'" % (vote['session'],
                                                           vote['chamber'],
                                                           vote['bill_id'],
                                                           vote['motion']))

        for type in ['yes_votes', 'no_votes', 'other_votes']:
            vote[type] = map(lambda l:
                                 {'name': l,
                                  'leg_id': self.matcher[vote['chamber']][l]},
                             vote[type])

        path = os.path.join(self.output_dir, 'votes', filename)
        try:
            with open(path, 'w') as f:
                json.dump(vote, f, cls=DateEncoder)
        except IOError as e:
            if e.errno == 2:
                os.makedirs(os.path.join(self.output_dir, 'votes'))
                with open(path, 'w') as f:
                    json.dump(vote, f, cls=DateEncoder)

    def write_metadata(self):
        metadata = self.scrape_metadata()
        metadata['state'] = self.state

        with open(os.path.join(self.output_dir, 'state_metadata.json'),
                  'w') as f:
            json.dump(metadata, f, cls=DateEncoder)

    def reset_name_matchers(self, upper=None, lower=None):
        self.matcher = {}
        self.matcher['upper'] = upper or NameMatcher()
        self.matcher['lower'] = lower or NameMatcher()

    @classmethod
    def run(cls, matcher=None):
        """
        Create and run a scraper for this state, based on
        command line options.
        """
        parser = OptionParser(
            option_list=cls.option_list)
        options, spares = parser.parse_args()

        if options.verbose == 0:
            verbosity = logging.WARNING
        elif options.verbose == 1:
            verbosity = logging.INFO
        else:
            verbosity = logging.DEBUG

        scraper = cls(verbosity=verbosity, **vars(options))

        scraper.write_metadata()

        years = options.years
        if options.all_years:
            years = [str(y) for y in range(scraper.earliest_year,
                                           datetime.datetime.now().year + 1)]
        if not years:
            parser.error(
                "You must provide a --year YYYY or --all (all years) option")

        chambers = []
        if options.upper:
            chambers.append('upper')
        if options.lower:
            chambers.append('lower')
        if not chambers:
            chambers = ['upper', 'lower']
        for year in years:
            if matcher is None:
                scraper.reset_name_matchers()
            else:
                scraper.reset_name_matchers(upper=matcher['upper'](),
                                            lower=matcher['lower']())
            try:
                if options.legislators:
                    for chamber in chambers:
                        scraper.scrape_legislators(chamber, year)
                for chamber in chambers:
                    scraper.old_bills = {}
                    scraper.scrape_bills(chamber, year)
            except NoDataForYear, e:
                if options.all_years:
                    pass
                else:
                    raise


class FiftystatesObject(dict):

    def __init__(self, type, **kwargs):
        super(FiftystatesObject, self).__init__()
        self['type'] = type
        self['sources'] = []
        self.update(kwargs)

    def add_source(self, url, retrieved=None, **kwargs):
        """
        Add a source URL from which data related to this object was scraped.

        :param url: the location of the source
        """
        retrieved = retrieved or datetime.datetime.now()
        self['sources'].append(dict(url=url, retrieved=retrieved, **kwargs))


class Bill(FiftystatesObject):
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
        super(Bill, self).__init__('bill', **kwargs)
        self['session'] = session
        self['chamber'] = chamber
        self['bill_id'] = bill_id
        self['title'] = title
        self['sponsors'] = []
        self['votes'] = []
        self['versions'] = []
        self['actions'] = []
        self['documents'] = []

    def add_sponsor(self, type, name, **kwargs):
        """
        Associate a sponsor with this bill.

        :param type: the type of sponsorship, e.g. 'primary', 'cosponsor'
        :param name: the name of the sponsor as provided by the state
        """
        self['sponsors'].append(dict(type=type, name=name, **kwargs))

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


class Vote(FiftystatesObject):

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
        super(Vote, self).__init__('vote', **kwargs)
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


class Person(FiftystatesObject):

    def __init__(self, full_name, **kwargs):
        """
        Create a Person.

        Note: the :class:`pyutils.legislation.Legislator` class should
        be used when dealing with state legislators.

        :param full_name: the person's full name
        """
        super(Person, self).__init__('person', **kwargs)
        self['full_name'] = full_name
        self['roles'] = []

    def add_role(self, role, session, start_date=None, end_date=None, **kwargs):
        """
        If ``start_date`` or ``end_date`` are ``None``, they will default
        to the start/end date of the given legislative session.

        Examples:

        leg.add_role('member', session='2009', chamber='upper',
                     party='Republican', district='10th')
        """
        self['roles'].append(dict(role=role, session=session,
                                  start_date=start_date,
                                  end_date=end_date, **kwargs))


class Legislator(Person):

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
        super(Legislator, self).__init__(full_name, **kwargs)
        #self['type'] = 'legislator'
        self.add_role('member', session, chamber=chamber, district=district,
                      party=party)
        self['first_name'] = first_name
        self['last_name'] = last_name
        self['middle_name'] = middle_name
