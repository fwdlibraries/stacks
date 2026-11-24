import pytest

from app.ingest import pipeline
from app.ingest.resolvers import ResolveContext, primo
from tests.test_ingest.fake_http import FakeSources
from tests.test_ingest.fixtures import CDI_ARTICLE, primo_search_doc
from tests.test_ingest.test_pipeline import ALMA, LIBRARY, PRIMO

HELD = "991003392230803687"
NETWORK_ZONE = "9911814563504266"

BOOK = primo_search_doc(
    f"alma{HELD}",
    context="L",
    title="Emissions trading schemes and their linking : challenges and issues$$QEmissions trading",
    creator=["Asian Development Bank.$$QAsian Development Bank"],
    availability="available_in_library",
    addata={"date": ["2016"], "isbn": ["978-92-9257-560-1", "bad"]},
)
NZ_BOOK = primo_search_doc(f"alma{NETWORK_ZONE}", context="L", title="Pricing carbon emissions")


@pytest.fixture
def fake():
    fake = FakeSources()
    fake.add(PRIMO, {"info": {"total": 4160}, "docs": [CDI_ARTICLE, BOOK, NZ_BOOK]})
    fake.add(ALMA.rstrip("/"), {"total_record_count": 1, "bib": [{"mms_id": HELD}]})
    return fake


async def run_search(fake, sources=LIBRARY, **kwargs):
    async with fake.client() as http:
        return await pipeline.search("carbon; pricing", ResolveContext(http=http, sources=sources), **kwargs)


def test_cdi_article_to_draft():
    draft = primo.to_draft(CDI_ARTICLE)
    assert draft.resource_type == "journal_article"
    assert draft.author == ["Bonacina, Monica", "Gulli, Francesco"]
    assert (draft.year, draft.volume, draft.issue, draft.pages) == (2007, "35", "8", "4200-4220")
    assert draft.doi == "10.1016/j.enpol.2007.02.016"
    assert draft.metadata == {"journal_name": "Energy policy"}


def test_catalogue_record_display_cleanup():
    draft = primo.to_draft(BOOK)
    assert draft.title == "Emissions trading schemes and their linking: challenges and issues"
    assert draft.author == ["Asian Development Bank"]
    assert draft.isbn == "9789292575601"


async def test_search_binds_only_what_the_institution_holds(fake):
    total, candidates = await run_search(fake, offset=10, limit=3)

    assert total == 4160
    assert [(c.source_system, c.source_identifier, c.authoritative, c.availability) for c in candidates] == [
        ("primo", CDI_ARTICLE["pnx"]["control"]["recordid"][0], False, "online"),
        ("alma", HELD, True, "in_library"),
        # A consortium (Network Zone) record the institution's Alma can't serve
        ("primo", f"alma{NETWORK_ZONE}", False, "online"),
    ]
    search, holdings = fake.requests
    assert search.url.params["q"] == "any,contains,carbon pricing"  # ';' would start a new clause
    assert (search.url.params["offset"], search.url.params["limit"]) == ("10", "3")
    assert search.url.params["scope"] == "MyInst_and_CI"
    assert holdings.url.params["mms_id"] == f"{HELD},{NETWORK_ZONE}"


async def test_search_without_alma_binds_nothing(fake):
    _, candidates = await run_search(fake, sources={"primo": LIBRARY["primo"]})
    assert {c.source_system for c in candidates} == {"primo"}
    assert "api-na.hosted.exlibrisgroup.com" in fake.hosts()
    assert all("/almaws/" not in r.url.path for r in fake.requests)


async def test_network_zone_record_is_added_from_primo(fake):
    fake.add(PRIMO, {"info": {"total": 1}, "docs": [NZ_BOOK]})
    fake.add(ALMA + NETWORK_ZONE, {"errorsExist": True}, status=400)
    async with fake.client() as http:
        candidate = await pipeline.fetch("alma", NETWORK_ZONE, ResolveContext(http=http, sources=LIBRARY))
    assert (candidate.source_system, candidate.source_identifier) == ("primo", f"alma{NETWORK_ZONE}")
    assert not candidate.authoritative
    assert fake.requests[-1].url.params["q"] == f"any,exact,{NETWORK_ZONE}"


async def test_refetch_cdi_record_by_id(fake):
    record_id = CDI_ARTICLE["pnx"]["control"]["recordid"][0]
    async with fake.client() as http:
        ctx = ResolveContext(http=http, sources=LIBRARY)
        candidate = await pipeline.fetch("primo", record_id, ctx)
        # Only the exact record counts, not whatever else the search returns
        missing = await pipeline.fetch("primo", "cdi_other_record", ctx)
    assert candidate.draft.doi == "10.1016/j.enpol.2007.02.016"
    assert missing is None


async def test_primo_record_ids_are_validated(fake):
    async with fake.client() as http:
        assert await pipeline.fetch("primo", "anything,exact,x", ResolveContext(http=http, sources=LIBRARY)) is None
    assert fake.requests == []
