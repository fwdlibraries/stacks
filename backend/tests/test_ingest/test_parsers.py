import pytest

from app.ingest.parsers import MAX_ENTRIES, ParseError, detect_format, parse

RIS = """TY  - JOUR
AU  - Scott, Joan W.
TI  - Gender: A Useful Category
  of Historical Analysis
JO  - The American Historical Review
PY  - 1986///
VL  - 91
IS  - 5
SP  - 1053
EP  - 1075
SN  - 0002-8762
DO  - https://doi.org/10.2307/1864376
ER  - 

TY  - CHAP
AU  - Davis, Natalie Zemon
TI  - Women on Top
T2  - Society and Culture in Early Modern France
ED  - Someone, Ed
PB  - Stanford University Press
PY  - 1975
SN  - 978-0-8047-0972-9
ER  - 
"""

BIBTEX = r"""@book{bloch1953,
  author = {Bloch, Marc and Putnam, Peter},
  title = {The Historian's Craft},
  publisher = "Knopf", address = {New York}, year = 1953,
}
@comment{not an entry}
@article{trouillot, author={Trouillot, Michel-Rolph}, title={{Silencing} the Past},
 journal = {Beacon} # { Press}, year={1995}, pages={1--20}, note={Caf\'{e} na\"ive}}
"""


def test_detect_format():
    assert (detect_format(RIS), detect_format(BIBTEX), detect_format("Carr. What is history? 1961.")) == (
        "ris", "bibtex", "text",
    )


def test_ris():
    article, chapter = parse(RIS)
    d = article.draft
    assert (d.resource_type, d.title) == ("journal_article", "Gender: A Useful Category of Historical Analysis")
    assert (d.author, d.year, d.volume, d.issue, d.pages) == (["Scott, Joan W."], 1986, "91", "5", "1053-1075")
    assert (d.issn, d.doi, d.metadata) == ("0002-8762", "10.2307/1864376", {"journal_name": "The American Historical Review"})
    c = chapter.draft
    assert (c.resource_type, c.title, c.editor) == ("book_chapter", "Women on Top", ["Someone, Ed"])
    assert (c.isbn, c.metadata) == ("9780804709729", {"container_title": "Society and Culture in Early Modern France"})
    assert article.structured and article.text.startswith("TY  - JOUR")


def test_bibtex():
    book, article = parse(BIBTEX)
    assert (book.draft.title, book.draft.author, book.draft.year) == ("The Historian's Craft", ["Bloch, Marc", "Putnam, Peter"], 1953)
    assert (book.draft.publisher, book.draft.place_of_publication) == ("Knopf", "New York")
    a = article.draft
    assert (a.resource_type, a.title, a.pages, a.metadata) == (
        "journal_article", "Silencing the Past", "1-20", {"journal_name": "Beacon Press"},
    )
    assert article.raw["note"] == "Café naïve"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Numbered, with a wrapped line and a blank line
        (
            "1. Carr, E. H. (1961). What is history?\n"
            "2. Scott, J. W. (1986). Gender.\n   American Historical Review. https://doi.org/10.2307/1864376\n\n"
            "3. Trouillot, M.-R. Silencing the Past. Boston: Beacon, 1995.",
            [("Carr", 1961, None), ("Scott", 1986, "10.2307/1864376"), ("Trouillot", 1995, None)],
        ),
        # One per line
        ("Carr, E. H. What is history? 1961.\nBloch, Marc. The Historian's Craft. 1953.", [("Carr", 1961, None), ("Bloch", 1953, None)]),
        # Paragraphs wrapping over lines; a date range in the title isn't the year
        (
            "Hobsbawm, Eric. The Age of Revolution: Europe 1789-1848.\nLondon: Weidenfeld, 1962.\n\n"
            "Bloch, Marc. The Historian's Craft.\nNew York: Knopf, 1953.",
            [("Hobsbawm", 1962, None), ("Bloch", 1953, None)],
        ),
    ],
)
def test_pasted_references(text, expected):
    entries = parse(text)
    assert [(e.text.split(",")[0], e.draft.year, e.draft.doi) for e in entries] == expected
    assert not any(e.structured for e in entries)


def test_too_many_entries():
    with pytest.raises(ParseError):
        parse("\n".join(f"Author{i}, A. A reference title number {i}. 2001." for i in range(MAX_ENTRIES + 1)))
