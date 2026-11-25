import pytest

from app.ingest.draft import CitationDraft
from app.ingest.matching import guess_surname, guess_title, score
from app.ingest.parsers import Entry


def structured(**kw) -> Entry:
    return Entry(draft=CitationDraft(**kw), text="")


def pasted(text: str, year: int | None = None) -> Entry:
    return Entry(draft=CitationDraft(year=year), text=text, structured=False)


CARR = CitationDraft(title="What is history?: the George Macaulay Trevelyan lectures", author=["Carr, Edward Hallett, 1892-1982"], year=1962)


def test_structured_scores():
    entry = structured(title="What is history?", author=["Carr, E. H."], year=1961)
    assert score(entry, CARR) == pytest.approx(0.97)  # year off by one
    assert score(entry, CitationDraft(title="What is history?", author=["Jenkins, Keith"], year=1995)) < 0.85
    assert score(entry, CitationDraft(title="A brief history of nakedness", author=["Carr, X"], year=1961)) < 0.5


def test_pasted_scores():
    entry = pasted("Carr, E. H. (1961). What is history? London: Macmillan.", 1961)
    assert score(entry, CARR) >= 0.9
    # A one-word title is "in" every history reference: not a match
    assert score(entry, CitationDraft(title="History", author=["Wilson, Charles Reagan"], year=2006)) < 0.5


@pytest.mark.parametrize(
    ("text", "title", "surname"),
    [
        ("Carr, E. H. (1961). What is history? London: Macmillan.", "What is history", "carr"),
        ("Trouillot, Michel-Rolph. Silencing the Past: Power and the Production of History. Boston: Beacon, 1995.",
         "Silencing the Past: Power and the Production of History", "trouillot"),
        ("Bloch, Marc. The Historian's Craft. New York: Knopf, 1953.", "The Historian's Craft", "bloch"),
    ],
)
def test_guesses(text, title, surname):
    assert (guess_title(text), guess_surname(text)) == (title, surname)
