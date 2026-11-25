from app.ingest.page import doi_in_url, to_entry


def test_highwire_article():
    entry = to_entry(
        "https://www.sciencedirect.com/science/article/pii/S0301421507000869",
        "Electricity pricing - ScienceDirect",
        {
            "citation_title": ["Electricity pricing under “carbon emissions trading”"],
            "citation_author": ["Bonacina, Monica", "Gulli, Francesco"],
            "citation_journal_title": ["Energy Policy"],
            "citation_publication_date": ["2007/08/01"],
            "citation_volume": ["35"], "citation_issue": ["8"],
            "citation_firstpage": ["4200"], "citation_lastpage": ["4220"],
            "citation_doi": ["10.1016/j.enpol.2007.02.016"],
            "citation_issn": ["0301-4215"],
            "og:title": ["Ignored when citation_title exists"],
        },
        [],
    )
    d = entry.draft
    assert (d.resource_type, d.title, d.year) == ("journal_article", "Electricity pricing under “carbon emissions trading”", 2007)
    assert (d.author, d.volume, d.issue, d.pages) == (["Bonacina, Monica", "Gulli, Francesco"], "35", "8", "4200-4220")
    assert (d.doi, d.issn, d.metadata) == ("10.1016/j.enpol.2007.02.016", "0301-4215", {"journal_name": "Energy Policy"})
    assert d.url.startswith("https://www.sciencedirect.com/") and entry.structured


def test_jsonld_book():
    entry = to_entry(
        "https://press.example.edu/books/silencing",
        "Silencing the Past | Beacon Press",
        {"og:title": ["Silencing the Past | Beacon Press"]},
        [{"@context": "https://schema.org", "@graph": [
            {"@type": "WebPage", "name": "page"},
            {"@type": "Book", "name": "Silencing the Past", "isbn": "978-0-8070-4310-3",
             "author": [{"@type": "Person", "givenName": "Michel-Rolph", "familyName": "Trouillot"}],
             "datePublished": "1995-03-01", "publisher": {"@type": "Organization", "name": "Beacon Press"}},
        ]}],
    )
    d = entry.draft
    assert (d.resource_type, d.title, d.author) == ("book", "Silencing the Past", ["Trouillot, Michel-Rolph"])
    assert (d.isbn, d.year, d.publisher) == ("9780807043103", 1995, "Beacon Press")


def test_plain_web_page_is_a_website():
    entry = to_entry("https://example.org/guide", "A citation guide", {"og:site_name": ["Example"]}, [])
    d = entry.draft
    assert (d.resource_type, d.title, d.url, d.metadata) == ("website", "A citation guide", "https://example.org/guide", {"site_name": "Example"})


def test_doi_from_the_url():
    assert doi_in_url("https://onlinelibrary.wiley.com/doi/full/10.1111/1468-229X.12345") == "10.1111/1468-229x.12345"
    assert doi_in_url("https://doi.org/10.2307/1864376") == "10.2307/1864376"
    assert doi_in_url("https://example.org/page") is None
    entry = to_entry("https://journals.example.org/doi/10.1086/ahr/91.5.1053/pdf", None, {}, [])
    assert entry.draft.doi == "10.1086/ahr/91.5.1053"
