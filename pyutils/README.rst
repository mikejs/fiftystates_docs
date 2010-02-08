.. _pythonapi:

==================
Python Scraper API
==================

.. contents::
   :local:

LegislationScraper
==================

.. autoclass:: legislation.LegislationScraper
   :members: __init__, urlopen, urlopen_context, soup_context, log, add_bill, add_legislator, scrape_bills, scrape_legislators, scrape_metadata

Bill
====
.. autoclass:: legislation.Bill
   :members: __init__, add_action, add_sponsor, add_version, add_vote, add_document, add_source

Vote
====
.. autoclass:: legislation.Vote
   :members: __init__, yes, no, other, add_source

Legislator
==========
.. autoclass:: legislation.Legislator
   :members: __init__, add_source, add_role

Exceptions
==========
.. autoclass:: legislation.ScrapeError

.. autoclass:: legislation.NoDataForYear
