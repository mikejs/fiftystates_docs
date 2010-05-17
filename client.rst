==================
python-fiftystates
==================

Python library for interacting with the Fifty State Project API.

The Fifty State Project provides data on state legislative activities,
including bill summaries, votes, sponsorships and state legislator
information.

python-fiftystates is a project of Sunlight Labs (c) 2009.
Written by Michael Stephens <mstephens@sunlightfoundation.com>.

Source: http://github.com/sunlightlabs/python-fiftystates

Requirements
============

python >= 2.4

remoteobjects >= 1.1

Installation
============

To install run

    ``python setup.py install``

Usage
=====

An API key can be obtained at http://services.sunlightlabs.com/.

Grab state metadata:

    >>> import fiftystates
    >>> fiftystates.API_KEY = 'YOUR_API_KEY_HERE'
    >>> ca = fiftystates.State.get('ca')
    >>> print ca.name
    California
    >>> print ca.lower_chamber_name
    Assembly
    >>> for session in ca.sessions:
    ...     print session.name
    20092010
    20092010 Special Session 1
    20092010 Special Session 2
    20092010 Special Session 3
    20092010 Special Session 4
    20092010 Special Session 5
    20092010 Special Session 6
    20092010 Special Session 7

Lookup legislators by name:

    >>> mikes = fiftystates.Legislator.search(state='ca', first_name='Mike')
    >>> for mike in mikes:
    ...     print mike.full_name
    Duvall, Mike D.
    Davis, Mike
    Eng, Mike
    Feuer, Mike

Lookup legislators by name and party:

    >>> dem_mikes = fiftystates.Legislator.search(state='ca',
    ... party='Democrat', first_name='Mike')
    >>> for mike in dem_mikes:
    ...     print mike.full_name
    Davis, Mike
    Eng, Mike
    Feuer, Mike

Search bills:

    >>> bills = fiftystates.Bill.search('agriculture', state='vt')[0:3]
    >>> for bill in bills:
    ...     print "%s %s %s" % (bill.state, bill.bill_id, bill.title)
    vt H.0193 AN ACT RELATING TO THE ADDITION OF THE SECRETARY OF AGRICULTURE, FOOD AND MARKETS TO THE BOARD OF TRUSTEES OF THE UNIVERSITY OF VERMONT AND STATE AGRICULTURAL COLLEGE
    vt S.0132 AN ACT RELATING TO AGRICULTURAL FUNDING EDUCATION AND OUTREACH
    vt H.0429 AN ACT RELATING TO A TUITION CREDIT FOR STUDENTS IN AGRICULTURAL PROGRAMS

Grab information about a specific bill:

    >>> bill = fiftystates.Bill.get('ca', '20092010', 'lower', 'AB20')
    >>> print bill.title
    An act to add Chapter 14.27 (commencing with Section 67325) to Part 40 of Division 5 of Title 3 of the Education Code, relating to public postsecondary education.

List a bill's sponsors:

    >>> for sponsor in bill.sponsors:
    ...    print sponsor.full_name
    Torlakson, Tom
    Portantino, Anthony
    Block, Marty
    Solorio, Jose

List a bill's actions:

    >>> for action in bill.actions[0:3]:
    ...     print action
    Secretary of State: Chaptered by Secretary of State - Chapter   402, Statutes of 2009.
    Governor: Approved by the Governor.
    Governor: Enrolled and to the Governor at   5 p.m.

View a bill's votes:

    >>> vote = bill.votes[0]
    >>> print vote.motion
    Do pass as amended and be re-referred to the Committee on Business and Professions.
    >>> print vote.yes_count, vote.no_count, vote.other_count
    9 0 0

Lookup a legislative district:

    >>> district = fiftystates.District.get('ny', '2009-2010', 'lower', '106')
    >>> print district.legislators[0].full_name
    Ronald J. Canestrari

Lookup a district by latitude and longitude:

    >>> district_geo = fiftystates.District.geo('ny', '2009-2010', 'lower', -73.675451, 42.737498)
    >>> district.name == district_geo.name
    True

Get contact info for legislators:

    >>> print district.legislators[0].roles[0].contact_info[0].phone
    518-455-4474