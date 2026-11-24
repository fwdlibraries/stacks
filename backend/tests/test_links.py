from urllib.parse import parse_qs, urlsplit

import pytest

from app.models.models import Citation, ResourceType
from app.services.links import LinkSettings, citation_link

LIBRARY = LinkSettings(discovery_url="https://abc.primo.exlibrisgroup.com", vid="01ABC_INST:NDE", institution="01ABC_INST")


def make(**fields) -> Citation:
    fields.setdefault("resource_type", ResourceType.book)
    fields.setdefault("title", "A title")
    fields.setdefault("metadata_", {})
    return Citation(**fields)


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@pytest.mark.parametrize(
    ("system", "identifier", "docid"),
    [("alma", "991234567890123", "alma991234567890123"), ("primo", "alma9911814563504266", "alma9911814563504266")],
)
def test_library_records_open_the_full_record(system, identifier, docid):
    link = citation_link(make(source_system=system, source_identifier=identifier, doi="10.1/x"), LIBRARY)
    assert link.kind == "library_record"
    # /discovery/ routes: NDE redirects them, so links survive an interface change
    assert link.url.startswith("https://abc.primo.exlibrisgroup.com/discovery/fulldisplay?")
    assert query(link.url) == {"docid": docid, "context": "L", "vid": "01ABC_INST:NDE", "lang": "en"}


def test_article_goes_through_the_link_resolver():
    article = make(
        resource_type=ResourceType.journal_article,
        title="Electricity pricing",
        author=["Bonacina, Monica", "Gulli, Francesco"],
        year=2007,
        volume="35",
        issue="8",
        pages="4200–4220",
        issn="0301-4215",
        doi="10.1016/j.enpol.2007.02.016",
        source_system="primo",
        source_identifier="cdi_crossref_primary_x",
        metadata_={"journal_name": "Energy policy"},
    )
    link = citation_link(article, LIBRARY)
    assert link.kind == "full_text"
    assert link.url.startswith("https://abc.primo.exlibrisgroup.com/discovery/openurl?")
    params = query(link.url)
    assert params["institution"] == "01ABC_INST"
    assert params["rft.genre"] == "article"
    assert (params["rft.atitle"], params["rft.jtitle"]) == ("Electricity pricing", "Energy policy")
    assert (params["rft.aulast"], params["rft.aufirst"]) == ("Bonacina", "Monica")
    assert (params["rft.spage"], params["rft.epage"]) == ("4200", "4220")
    assert params["rft_id"] == "info:doi/10.1016/j.enpol.2007.02.016"
    assert params["rfr_id"] == "info:sid/stacks"


def test_manually_entered_article_uses_publisher_as_journal():
    article = make(resource_type=ResourceType.journal_article, publisher="Past & Present", issn="0031-2746")
    assert query(citation_link(article, LIBRARY).url)["rft.jtitle"] == "Past & Present"


def test_unbound_book_with_isbn_checks_holdings():
    link = citation_link(make(isbn="9780140135848", author=["Carr, E. H."]), LIBRARY)
    assert link.kind == "full_text"
    assert (query(link.url)["rft.genre"], query(link.url)["rft.isbn"]) == ("book", "9780140135848")


def test_unlinked_citation_is_no_longer_a_library_record():
    citation = make(source_system="alma", source_identifier="991234567890123", source_status="unlinked", isbn="9780140135848")
    assert citation_link(citation, LIBRARY).kind == "full_text"


def test_websites_keep_their_url():
    link = citation_link(make(resource_type=ResourceType.website, url="https://example.org/a", doi="10.1/x"), LIBRARY)
    assert (link.kind, link.url) == ("web", "https://example.org/a")


def test_without_library_settings_doi_then_url():
    article = make(resource_type=ResourceType.journal_article, doi="10.1/x", url="https://example.org/a", issn="1")
    assert citation_link(article, None).url == "https://doi.org/10.1/x"
    assert citation_link(make(url="https://example.org/a"), None).url == "https://example.org/a"
    assert citation_link(make(source_system="alma", source_identifier="991234567890123"), None) is None


def test_not_enough_to_resolve_falls_back():
    # A book with no ISBN or DOI: nothing for the resolver to match on
    assert citation_link(make(url="https://example.org/a"), LIBRARY).kind == "web"
    assert citation_link(make(), LIBRARY) is None
