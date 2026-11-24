"""Citation ingestion: turn whatever a list-builder has (an identifier, a search hit,
a web page, a PDF) into citation candidates, preferably bound to a record in the
library's own system so links and metadata stay current.

    input → identify (identifiers.py) → resolve (resolvers/) → candidates → review → save

Resolvers form an ordered chain, so new ones (a discovery search, an AI matcher)
slot in without changing callers. Every candidate says how it was matched and how
confident that match is.
"""
