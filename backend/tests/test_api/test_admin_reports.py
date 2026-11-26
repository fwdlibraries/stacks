"""Operations reports: scoped to the viewer's reports.view grants."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    BackgroundJob,
    Citation,
    CitationEvent,
    College,
    CourseTemplate,
    Department,
    LibrarySource,
    LinkClick,
    ListSection,
    Organization,
    ReadingList,
    ResourceType,
    ScopeType,
)
from app.routers import admin_reports
from app.services import access, credentials
from tests.test_api.test_admin import person, sign_in


@pytest.fixture
async def campus(db_session: AsyncSession):
    org = Organization(name="Uni", slug="uni")
    arts = College(organization=org, name="Arts")
    history = Department(college=arts, name="History")
    biology = Department(college=arts, name="Biology")
    lists = {}
    for dept, code in ((history, "HIST101"), (biology, "BIO101")):
        rl = ReadingList(course_template=CourseTemplate(department=dept, code=code, name=code), title=f"{code} list",
                         is_published=code == "HIST101")
        section = ListSection(reading_list=rl, title="Week 1", sort_order=0)
        lists[code] = (rl, section)
    db_session.add(org)
    await db_session.flush()

    hist_list, hist_section = lists["HIST101"]
    gone = Citation(section=hist_section, resource_type=ResourceType.book, title="Gone book", sort_order=0,
                    source_system="alma", source_identifier="991", source_status="missing")
    paywalled = Citation(section=hist_section, resource_type=ResourceType.journal_article, title="Hard article", sort_order=1)
    easy = Citation(section=hist_section, resource_type=ResourceType.journal_article, title="Easy article", sort_order=2)
    bio_list, bio_section = lists["BIO101"]
    bio = Citation(section=bio_section, resource_type=ResourceType.book, title="Bio book", sort_order=0)
    db_session.add_all([gone, paywalled, easy, bio])
    await db_session.flush()

    now = datetime.now(UTC)
    db_session.add(CitationEvent(citation_id=gone.id, kind="missing", source_system="alma", occurred_at=now - timedelta(days=2)))
    clicks = [(paywalled, "fallback")] * 3 + [(paywalled, "alma")] + [(easy, "libkey")] * 5 + [(bio, "alma")] * 2
    db_session.add_all(LinkClick(citation_id=c.id, reading_list_id=(bio_list if c is bio else hist_list).id, resolved_by=r)
                       for c, r in clicks)
    db_session.add(LinkClick(citation_id=easy.id, reading_list_id=hist_list.id, resolved_by="libkey",
                             clicked_at=now - timedelta(days=60)))  # outside the window
    db_session.add(BackgroundJob(job_type="bulk_import", status="completed", created_at=now,
                                 payload={"organization_id": str(org.id), "reading_list_id": str(bio_list.id), "section_id": str(bio_section.id)},
                                 result={"total": 4, "added": 3}))
    await db_session.commit()
    return {"org": org, "history": history, "biology": biology, "hist_list": hist_list, "bio_list": bio_list}


async def test_org_admin_report(client, db_session, campus):
    await sign_in(client, await person(db_session, campus["org"], "admin", access.ADMINISTRATOR, (ScopeType.organization, campus["org"].id)))
    body = (await client.get("/api/v1/admin/reports")).json()
    assert body["overview"] == {"lists_published": 1, "lists_draft": 1, "citations": 4, "library_records": 1,
                                "flagged": 1, "clicks": 11, "direct_clicks": 8}
    assert [(r["title"], r["status"], r["list_title"], r["section_title"]) for r in body["flagged"]] == [
        ("Gone book", "missing", "HIST101 list", "Week 1")]
    assert body["flagged"][0]["since"] is not None
    assert [(r["title"], r["clicks"], r["fallback_clicks"]) for r in body["hard_to_reach"]] == [("Hard article", 4, 3)]
    assert [(r["list_title"], r["clicks"]) for r in body["top_lists"]] == [("HIST101 list", 9), ("BIO101 list", 2)]
    assert body["top_citations"][0]["title"] == "Easy article"
    assert [(i["list_title"], i["total"], i["added"]) for i in body["imports"]] == [("BIO101 list", 4, 3)]
    assert body["sync"] == {"connected": False, "last_run_at": None, "last_status": None, "checked": None,
                            "updated": None, "flagged": None, "error": None, "can_run": False}


async def test_department_librarian_sees_only_their_department(client, db_session, campus):
    await sign_in(client, await person(db_session, campus["org"], "lib", access.LIBRARIAN, (ScopeType.department, campus["biology"].id)))
    body = (await client.get("/api/v1/admin/reports")).json()
    assert body["overview"]["citations"] == 1 and body["overview"]["clicks"] == 2
    assert body["flagged"] == [] and body["hard_to_reach"] == []
    assert [r["list_title"] for r in body["top_lists"]] == ["BIO101 list"]
    assert len(body["imports"]) == 1
    assert body["sync"]["can_run"] is False
    assert (await client.post("/api/v1/admin/sync")).status_code == 403


async def test_reports_need_reports_view(client, db_session, campus):
    await sign_in(client, await person(db_session, campus["org"], "ins", access.INSTRUCTOR, (ScopeType.organization, campus["org"].id)))
    assert (await client.get("/api/v1/admin/reports")).status_code == 403


async def test_sync_status_and_sync_now(client, db_session, campus, monkeypatch):
    org = campus["org"]
    await sign_in(client, await person(db_session, org, "admin", access.ADMINISTRATOR, (ScopeType.organization, org.id)))
    assert (await client.post("/api/v1/admin/sync")).status_code == 409  # no Alma yet

    db_session.add(LibrarySource(organization_id=org.id, kind="alma", config={"region": "na"},
                                 api_key_encrypted=credentials.encrypt("k")))
    db_session.add(BackgroundJob(job_type="catalogue_sync", status="completed", payload={"organization_id": str(org.id)},
                                 result={"checked": 40, "updated": 2, "flagged": 1}, completed_at=datetime.now(UTC)))
    await db_session.commit()
    sync = (await client.get("/api/v1/admin/reports")).json()["sync"]
    assert (sync["connected"], sync["last_status"], sync["checked"], sync["updated"], sync["can_run"]) == (True, "completed", 40, 2, True)

    queued = []
    monkeypatch.setattr(admin_reports, "enqueue_sync", queued.append)
    assert (await client.post("/api/v1/admin/sync")).status_code == 202
    assert queued == [org.id]
