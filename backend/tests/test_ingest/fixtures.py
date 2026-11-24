"""Sample source responses, shaped like the real APIs' output."""

# Alma Bibs API returns MARC XML in `anies`, without a namespace
ALMA_MARC = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<record>
  <leader>01234cam a2200301 i 4500</leader>
  <controlfield tag="001">991234567890123</controlfield>
  <controlfield tag="008">170301s2017    nyu      b    001 0 eng d</controlfield>
  <datafield tag="020" ind1=" " ind2=" "><subfield code="a">9780199535569 (paperback)</subfield></datafield>
  <datafield tag="050" ind1="0" ind2="0"><subfield code="a">D16</subfield></datafield>
  <datafield tag="100" ind1="1" ind2=" "><subfield code="a">Carr, Edward Hallett,</subfield><subfield code="e">author.</subfield></datafield>
  <datafield tag="245" ind1="1" ind2="0"><subfield code="a">What is history? :</subfield><subfield code="b">the George Macaulay Trevelyan lectures /</subfield><subfield code="c">E.H. Carr.</subfield></datafield>
  <datafield tag="250" ind1=" " ind2=" "><subfield code="a">2nd ed.</subfield></datafield>
  <datafield tag="264" ind1=" " ind2="4"><subfield code="c">©1961</subfield></datafield>
  <datafield tag="264" ind1=" " ind2="1"><subfield code="a">New York :</subfield><subfield code="b">Vintage Books,</subfield><subfield code="c">2017.</subfield></datafield>
  <datafield tag="700" ind1="1" ind2=" "><subfield code="a">Davies, R. W.,</subfield><subfield code="e">editor.</subfield></datafield>
  <datafield tag="700" ind1="1" ind2=" "><subfield code="a">Evans, Richard J.,</subfield><subfield code="e">writer of introduction.</subfield></datafield>
  <datafield tag="710" ind1="2" ind2=" "><subfield code="a">University of Cambridge.</subfield></datafield>
  <datafield tag="710" ind1="2" ind2=" "><subfield code="a">History Workshop Collective,</subfield><subfield code="e">author.</subfield></datafield>
</record>"""

ALMA_EBOOK_MARC = """<record xmlns="http://www.loc.gov/MARC21/slim">
  <leader>01234nam a2200301 i 4500</leader>
  <controlfield tag="008">200101s2020    enk     o     000 0 eng d</controlfield>
  <datafield tag="245" ind1="0" ind2="0"><subfield code="a">Digital history.</subfield></datafield>
</record>"""


def alma_bib(mms_id: str, marc: str = ALMA_MARC) -> dict:
    return {"mms_id": mms_id, "record_format": "marc21", "suppress_from_publishing": "false", "anies": [marc]}


def cdi_doc(source_record_id: str) -> dict:
    """A Central Discovery Index record: numeric sourcerecordid, but not an Alma record."""
    return {
        "context": "PC",
        "pnx": {"control": {"recordid": [f"cdi_proquest_{source_record_id}"], "sourcerecordid": [source_record_id]}},
    }


def primo_doc(mms_id: str, context: str = "L") -> dict:
    return {
        "context": context,
        "pnx": {
            "control": {"recordid": [f"alma{mms_id}"], "sourcerecordid": [mms_id]},
            "display": {"title": ["What is history?"]},
        },
    }


CROSSREF_WORK = {
    "DOI": "10.1093/AHR/RHAA001",
    "type": "journal-article",
    "title": ["History and its discontents"],
    "author": [{"given": "Ada", "family": "Lovelace"}, {"name": "History Collective"}],
    "container-title": ["The American Historical Review"],
    "publisher": "Oxford University Press",
    "volume": "125",
    "issue": "1",
    "page": "1-20",
    "ISSN": ["0002-8762"],
    "published-print": {"date-parts": [[2020, 2]]},
}

OPEN_LIBRARY_BOOK = {
    "title": "The Historian's Craft",
    "authors": [{"name": "Marc Bloch"}],
    "publish_date": "1953",
    "publishers": [{"name": "Knopf"}],
}


def primo_search_doc(record_id: str, *, context: str, title: str, type_: str = "book", availability: str = "not_restricted",
                     addata: dict | None = None, creator: list[str] | None = None) -> dict:
    """A Primo search result with display/addata/delivery, as the live API returns them."""
    return {
        "context": context,
        "pnx": {
            "control": {"recordid": [record_id], "sourcerecordid": [record_id.removeprefix("alma")]},
            "display": {"title": [title], "type": [type_], "creator": creator or []},
            "addata": addata or {},
        },
        "delivery": {"availability": [availability]},
    }


CDI_ARTICLE = primo_search_doc(
    "cdi_crossref_primary_10_1016_j_enpol_2007_02_016",
    context="PC",
    title="Electricity pricing under “carbon emissions trading”",
    type_="article",
    availability="fulltext",
    creator=["Bonacina, Monica ; Gulli, Francesco"],
    addata={
        "jtitle": ["Energy policy"],
        "volume": ["35"],
        "issue": ["8"],
        "spage": ["4200"],
        "epage": ["4220"],
        "date": ["2007"],
        "doi": ["10.1016/j.enpol.2007.02.016"],
        "issn": ["0301-4215"],
        "pub": ["Elsevier Ltd"],
    },
)
