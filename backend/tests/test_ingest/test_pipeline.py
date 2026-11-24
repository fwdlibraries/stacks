import pytest

from app.ingest import pipeline
from app.ingest.resolvers import ResolveContext
from app.ingest.sources import AlmaConfig, PrimoConfig, Source
from tests.test_ingest.fake_http import FakeSources
from tests.test_ingest.fixtures import CROSSREF_WORK, OPEN_LIBRARY_BOOK, alma_bib, primo_doc

ALMA = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/bibs/"
PRIMO = "https://api-na.hosted.exlibrisgroup.com/primo/v1/search"
MMS = "991234567890123"
ISBN = "9780140449136"

LIBRARY = {
    "alma": Source("alma", AlmaConfig(region="na"), "alma-key"),
    "primo": Source(
        "primo",
        PrimoConfig(region="na", vid="01ABC_INST:MAIN", discovery_url="https://abc.primo.exlibrisgroup.com"),
        "primo-key",
    ),
}


@pytest.fixture
def fake():
    return FakeSources()


async def run(fake: FakeSources, text: str, sources=None):
    async with fake.client() as http:
        return await pipeline.lookup(text, ResolveContext(http=http, sources=sources or {}))


async def test_mms_id_fetches_the_alma_record(fake):
    fake.add(ALMA + MMS, alma_bib(MMS))
    result = await run(fake, MMS, LIBRARY)

    [candidate] = result.candidates
    assert (candidate.source_system, candidate.source_identifier, candidate.confidence) == ("alma", MMS, 1.0)
    assert candidate.authoritative
    assert candidate.draft.title.startswith("What is history?")
    request = fake.requests[0]
    assert request.headers["Authorization"] == "apikey alma-key"
    assert request.url.params["view"] == "full"


async def test_isbn_prefers_the_librarys_record_over_open_data(fake):
    fake.add(PRIMO, {"docs": [primo_doc(MMS), primo_doc("ignored", context="PC")]})
    fake.add(ALMA + MMS, alma_bib(MMS))
    result = await run(fake, ISBN, LIBRARY)

    assert [(c.source_system, c.match_method, c.confidence) for c in result.candidates] == [("alma", "isbn", 0.95)]
    search = fake.requests[0]
    assert search.url.params["q"] == f"isbn,exact,{ISBN}"
    assert search.url.params["vid"] == "01ABC_INST:MAIN"
    assert "openlibrary.org" not in fake.hosts()


async def test_isbn_falls_back_to_open_library_when_the_library_lacks_it(fake):
    fake.add(PRIMO, {"docs": []})
    fake.add("https://openlibrary.org/api/books", {f"ISBN:{ISBN}": OPEN_LIBRARY_BOOK})
    result = await run(fake, ISBN, LIBRARY)

    [candidate] = result.candidates
    assert (candidate.source_system, candidate.authoritative) == ("openlibrary", False)
    assert candidate.draft.author == ["Marc Bloch"]
    assert result.warnings == []


async def test_failing_source_is_a_warning_not_an_error(fake):
    fake.add(PRIMO, {"errorsExist": True}, status=401)
    fake.add("https://openlibrary.org/api/books", {f"ISBN:{ISBN}": OPEN_LIBRARY_BOOK})
    result = await run(fake, ISBN, LIBRARY)

    assert [c.source_system for c in result.candidates] == ["openlibrary"]
    assert result.warnings == ["Primo: rejected the API key"]


async def test_unreachable_source(fake):
    fake.down.add("api.crossref.org")
    result = await run(fake, "10.1093/ahr/rhaa001")
    assert result.candidates == []
    assert result.warnings == ["Crossref: could not be reached (ConnectError)"]


async def test_without_library_sources_only_open_data_is_used(fake):
    fake.add("https://api.crossref.org/works/10.1093/ahr/rhaa001", {"message": CROSSREF_WORK})
    result = await run(fake, "https://doi.org/10.1093/AHR/RHAA001 and 991234567890123")

    [candidate] = result.candidates
    draft = candidate.draft
    assert (candidate.source_system, draft.resource_type, draft.year) == ("crossref", "journal_article", 2020)
    assert draft.author == ["Lovelace, Ada", "History Collective"]
    assert draft.doi == "10.1093/ahr/rhaa001"
    assert draft.metadata == {"journal_name": "The American Historical Review"}
    assert fake.hosts() == ["api.crossref.org"]


async def test_unknown_mms_id(fake):
    # Alma answers an unknown MMS ID with 400
    fake.add(ALMA + MMS, {"errorsExist": True}, status=400)
    result = await run(fake, MMS, LIBRARY)
    assert (result.candidates, result.warnings) == ([], [])


@pytest.mark.parametrize(
    ("system", "identifier"),
    [("alma", "99/../../users"), ("crossref", "10.1/../x"), ("openlibrary", "not-an-isbn")],
)
async def test_fetch_rejects_malformed_identifiers_without_calling_out(fake, system, identifier):
    async with fake.client() as http:
        assert await pipeline.fetch(system, identifier, ResolveContext(http=http, sources=LIBRARY)) is None
    assert fake.requests == []
