import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.resolvers import ResolveContext
from app.ingest.sync import sync_organization
from app.models.models import Citation, CitationEvent, ResourceType
from tests.test_api.test_list_editing import Org
from tests.test_ingest.fake_http import FakeSources
from tests.test_ingest.fixtures import ALMA_MARC, alma_bib
from tests.test_ingest.test_pipeline import LIBRARY

BIBS = "https://api-na.hosted.exlibrisgroup.com/almaws/v1/bibs"
KEPT, GONE, HIDDEN, UNLINKED = "991000000000013687", "991000000000023687", "991000000000033687", "991000000000043687"


@pytest.fixture
async def org(db_session: AsyncSession):
    mine = await Org().build(db_session, "mine")
    other = await Org().build(db_session, "other")

    def bound(org, mms, **kw):
        return Citation(
            section=org.section_b,
            resource_type=ResourceType.book,
            title=kw.pop("title", "Old title"),
            sort_order=kw.pop("sort_order", 0),
            source_system="alma",
            source_identifier=mms,
            source_status=kw.pop("source_status", "ok"),
            student_note="Read chapter 2",
            is_required=False,
            **kw,
        )

    db_session.add_all(
        [
            bound(mine, KEPT, year=1999),
            bound(mine, GONE, sort_order=1),
            bound(mine, HIDDEN, sort_order=2, title="What is history? The George Macaulay Trevelyan lectures"),
            bound(mine, UNLINKED, sort_order=3, source_status="unlinked"),
            bound(other, KEPT),  # another organization's citation: not synced with mine
        ]
    )
    await db_session.commit()
    return mine


def alma_answers(fake: FakeSources, *, hidden_restored=False):
    hidden = alma_bib(HIDDEN)
    hidden["suppress_from_publishing"] = "false" if hidden_restored else "true"
    fake.add(BIBS, {"total_record_count": 2, "bib": [alma_bib(KEPT), hidden]})


async def run(db: AsyncSession, org: Org, fake: FakeSources, sources=LIBRARY):
    async with fake.client() as http:
        report = await sync_organization(db, org.org.id, ResolveContext(http=http, sources=sources))
    await db.commit()
    return report


async def citation(db: AsyncSession, org: Org, mms: str) -> Citation:
    return await db.scalar(
        select(Citation).where(Citation.source_identifier == mms, Citation.list_section_id == org.section_b.id)
        .execution_options(populate_existing=True)
    )


async def test_sync_updates_flags_and_logs(db_session, org):
    fake = FakeSources()
    alma_answers(fake)
    report = await run(db_session, org, fake)

    # KEPT and HIDDEN both gain the record's details (authors, year, ...); GONE has no record
    assert (report.checked, report.updated, report.flagged) == (3, 2, 2)
    # One batched call for every bound citation; unlinked ones aren't asked about
    [request] = fake.requests
    assert set(request.url.params["mms_id"].split(",")) == {KEPT, GONE, HIDDEN}
    assert request.url.params["view"] == "full"

    kept = await citation(db_session, org, KEPT)
    assert (kept.title, kept.year, kept.source_status) == ("What is history? The George Macaulay Trevelyan lectures", 2017, "ok")
    # The instructor's own fields are never touched
    assert (kept.student_note, kept.is_required) == ("Read chapter 2", False)
    assert kept.source_synced_at is not None

    assert (await citation(db_session, org, GONE)).source_status == "missing"
    assert (await citation(db_session, org, HIDDEN)).source_status == "suppressed"
    assert (await citation(db_session, org, UNLINKED)).title == "Old title"

    events = {(e.kind, e.citation_id): e for e in await db_session.scalars(select(CitationEvent))}
    update = events[("updated", kept.id)]
    assert update.details["title"] == ["Old title", "What is history? The George Macaulay Trevelyan lectures"]
    assert update.details["year"] == [1999, 2017]
    assert {k for k, _ in events} == {"updated", "missing", "suppressed"}
    assert ("missing", (await citation(db_session, org, GONE)).id) in events


async def test_second_run_changes_nothing_and_records_can_come_back(db_session, org):
    fake = FakeSources()
    alma_answers(fake)
    await run(db_session, org, fake)

    again = await run(db_session, org, fake)
    assert (again.updated, again.flagged, again.unchanged) == (0, 0, 3)

    fake = FakeSources()
    alma_answers(fake, hidden_restored=True)
    restored = await run(db_session, org, fake)
    assert restored.restored == 1
    assert (await citation(db_session, org, HIDDEN)).source_status == "ok"


async def test_alma_failure_changes_nothing(db_session, org):
    fake = FakeSources()
    fake.down.add("api-na.hosted.exlibrisgroup.com")
    report = await run(db_session, org, fake)
    assert report.errors == ["Alma: could not be reached (ConnectError)"]
    assert (await citation(db_session, org, GONE)).source_status == "ok"
    assert await db_session.scalar(select(CitationEvent)) is None


async def test_unreadable_record_is_left_alone(db_session, org):
    fake = FakeSources()
    fake.add(BIBS, {"bib": [alma_bib(KEPT, marc="<not-marc"), alma_bib(HIDDEN, marc=ALMA_MARC)]})
    report = await run(db_session, org, fake)
    assert report.skipped == 1
    assert (await citation(db_session, org, KEPT)).title == "Old title"


async def test_no_alma_source_no_sync(db_session, org):
    fake = FakeSources()
    report = await run(db_session, org, fake, sources={})
    assert report.checked == 0
    assert fake.requests == []
