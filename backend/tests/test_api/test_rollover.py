"""Rollover stage 2: importing loader files and primary shells, and matching sections to
primaries. Course codes, CRNs and term codes are invented."""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import CourseOffering, Primary, RolloverItem, ScopeType, Term
from app.services import access, rollover
from tests.test_api.test_permissions import World, sign_in

PATTERN = "{subject}{number}_{mode}_{length}_PRIMARY"

LOADER = """CourseID,Course,Section_ID,Academic_Department,Term1,SEARCH_ID1,INSTR1,INSTR2,OPERATION,OLD_COURSE_CODE
40112.202710,Physical Geography,40112,GEO,TERM1,GEO 101,ada@uni.edu,,,
40113.202710,Physical Geography,40113,GEO,FULL,GEO 101,bo@uni.edu,cy@uni.edu,,
40200.202710,Ancient History,40200,HIST,FULL,HIST 101,,,,HIST101_F2F_SEM_PRIMARY
40300.202710,Old Course,40300,HIST,FULL,HIST 999,,,DELETE,
40400.202810,Wrong Term,40400,HIST,FULL,HIST 202,,,,
"""

PRIMARIES = """Org Unit Id,Name,Code,Department
6001,GEO 101 Online 8 week,GEO101_OL_TER_PRIMARY,GEO Global
6002,GEO 101 F2F 16 week,GEO101_F2F_SEM_PRIMARY,GEO Global
6003,GEO 101 Online 16 week,GEO101_OL_SEM_PRIMARY,GEO Global
,Sandbox,SANDBOX_JD,
"""


# ── Pure functions ───────────────────────────────────────────────────────────


def test_primary_code_pattern():
    parsed = rollover.parse_primary_code(PATTERN, "geo101_ol_ter_primary")
    assert (parsed.code, parsed.course, parsed.mode, parsed.length) == ("GEO101_OL_TER_PRIMARY", "GEO101", "OL", "TER")
    assert rollover.parse_primary_code(PATTERN, "EDU7085_F2F_SEM_PRIMARY").course == "EDU7085"
    assert rollover.parse_primary_code(PATTERN, "40112.202710") is None
    assert rollover.build_primary_code(PATTERN, "GEO101", "OL", "TER") == "GEO101_OL_TER_PRIMARY"
    with pytest.raises(ValueError, match="needs"):
        rollover.compile_primary_pattern("{mode}_PRIMARY")


def test_read_table_handles_tabs_bom_and_loose_headers():
    header, rows = rollover.read_table("﻿Course ID\tSection_ID\n40112.202710\t40112\n\n")
    assert header == ["Course ID", "Section_ID"]
    assert rows == [{"courseid": "40112.202710", "sectionid": "40112"}]


# ── Workspace ────────────────────────────────────────────────────────────────


@pytest.fixture
async def world(db_session: AsyncSession):
    world = await World().build(db_session)
    world.fall = Term(organization_id=world.org.id, code="202710", name="Fall 2027")
    world.org.settings = {
        "section_code_pattern": "{crn}.{term}",
        "rollover": {"primary_code_pattern": PATTERN, "lengths": {"FULL": "SEM", "TERM1": "TER"}},
    }
    db_session.add(world.fall)
    await db_session.commit()
    return world


@pytest.fixture
async def admin(client: AsyncClient, db_session, world):
    user = await world.person(db_session, "admin", access.ADMINISTRATOR, (ScopeType.organization, world.org.id))
    await sign_in(client, user)
    return user


async def items(client: AsyncClient, term: Term, **params) -> dict:
    resp = await client.get(f"/api/v1/admin/rollover/terms/{term.id}/items", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_code(body: dict) -> dict:
    return {i["lms_code"]: i for i in body["items"]}


async def test_loader_import_creates_sections_and_queues_the_unmatched(client, db_session, world, admin):
    resp = await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": LOADER})
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert (result["added"], result["updated"]) == (3, 0)
    assert {(s["code"], s["reason"]) for s in result["skipped"]} == {
        ("40300.202710", "Marked DELETE"),
        ("40400.202810", "This section is in term 202810, not 202710"),
    }
    # The file named a primary nobody had imported yet: it's added, and used
    assert result["matched"] == {"file": 1} and result["needs_source"] == 2
    assert await db_session.scalar(select(Primary.origin).where(Primary.code == "HIST101_F2F_SEM_PRIMARY")) == "file"

    body = await items(client, world.fall)
    assert body["counts"] == {"needs_source": 2, "in_review": 1, "approved": 0, "skipped": 0}
    rows = by_code(body)
    hist = rows["40200.202710"]
    assert hist["primary"]["code"] == "HIST101_F2F_SEM_PRIMARY" and hist["match_source"] == "file"
    assert hist["course"] == "HIST101"  # the World's existing course, found by code
    geo = rows["40113.202710"]
    assert (geo["course"], geo["course_name"], geo["length"]) == ("GEO101", "Physical Geography", "SEM")
    assert geo["instructors"] == ["bo@uni.edu", "cy@uni.edu"]
    assert geo["problems"] == ["The course has no primary of length SEM"]

    # The offering exists ahead of term, coded as the LMS shell, so the launch finds it
    offering = await db_session.scalar(select(CourseOffering).where(CourseOffering.lms_code == "40112.202710"))
    assert (offering.term, offering.section) == ("202710", "40112")

    queue = await items(client, world.fall, status="needs_source")
    assert {i["lms_code"] for i in queue["items"]} == {"40112.202710", "40113.202710"}


async def test_primaries_import_then_only_one_fits(client, world, admin):
    await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": LOADER})
    resp = await client.post("/api/v1/admin/rollover/primaries/import", json={"text": PRIMARIES})
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 3
    assert resp.json()["skipped"] == [{"line": 5, "code": "SANDBOX_JD", "reason": "Doesn't look like a primary code"}]

    assert (await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/rematch")).status_code == 204
    rows = by_code(await items(client, world.fall))
    # One 8-week primary: that's the one
    assert rows["40112.202710"]["primary"]["code"] == "GEO101_OL_TER_PRIMARY"
    assert rows["40112.202710"]["match_source"] == "only_one"
    # Two 16-week primaries (F2F and OL), and no mode rule yet: a librarian decides
    assert rows["40113.202710"]["primary"] is None and rows["40113.202710"]["status"] == "needs_source"
    assert rows["40113.202710"]["problems"] == [
        "Several primaries fit: GEO101_F2F_SEM_PRIMARY, GEO101_OL_SEM_PRIMARY"
    ]


async def test_a_choice_is_remembered_for_later_terms(client, db_session, world, admin):
    await client.post("/api/v1/admin/rollover/primaries/import", json={"text": PRIMARIES})
    await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": LOADER})
    geo = by_code(await items(client, world.fall))["40113.202710"]
    primary = (await client.get("/api/v1/admin/rollover/primaries", params={"q": "F2F_SEM"})).json()[0]

    resp = await client.patch(
        f"/api/v1/admin/rollover/items/{geo['id']}", json={"set_primary": True, "primary_id": primary["id"]}
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["match_source"], resp.json()["status"], resp.json()["problems"]) == ("manual", "in_review", [])

    remembered = (await client.get("/api/v1/admin/rollover/remembered")).json()
    assert [(r["course"], r["length"], r["primary"]) for r in remembered] == [
        ("GEO101", "SEM", "GEO101_F2F_SEM_PRIMARY")
    ]

    # Next term, the same course variant gets the same primary
    winter = Term(organization_id=world.org.id, code="202810", name="Winter 2028")
    db_session.add(winter)
    await db_session.commit()
    loader = "CourseID,Term1,SEARCH_ID1\n50113.202810,FULL,GEO 101\n"
    resp = await client.post(f"/api/v1/admin/rollover/terms/{winter.id}/import", json={"text": loader})
    assert resp.json()["matched"] == {"remembered": 1}

    # Forgetting it sends later imports back to the rules
    await client.delete(f"/api/v1/admin/rollover/remembered/{remembered[0]['id']}")
    await client.post(f"/api/v1/admin/rollover/terms/{winter.id}/rematch")
    assert (await items(client, winter))["items"][0]["status"] == "needs_source"


async def test_review_statuses(client, world, admin):
    await client.post("/api/v1/admin/rollover/primaries/import", json={"text": PRIMARIES})
    await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": LOADER})
    rows = by_code(await items(client, world.fall))
    matched, unmatched = rows["40112.202710"], rows["40113.202710"]

    resp = await client.post(
        "/api/v1/admin/rollover/items/bulk", json={"ids": [matched["id"], unmatched["id"]], "status": "approved"}
    )
    assert resp.json() == {"changed": 1, "refused": 1}
    resp = await client.patch(f"/api/v1/admin/rollover/items/{unmatched['id']}", json={"status": "approved"})
    assert resp.status_code == 409
    resp = await client.patch(
        f"/api/v1/admin/rollover/items/{unmatched['id']}", json={"status": "skipped", "notes": " Not running "}
    )
    assert (resp.json()["status"], resp.json()["notes"]) == ("skipped", "Not running")

    # Re-importing keeps decisions
    resp = await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": LOADER})
    assert resp.json()["updated"] == 3
    counts = (await items(client, world.fall))["counts"]
    assert counts["approved"] == 1 and counts["skipped"] == 1

    # Back to review: the status follows whether there's a primary
    resp = await client.patch(f"/api/v1/admin/rollover/items/{unmatched['id']}", json={"status": "in_review"})
    assert resp.json()["status"] == "needs_source"


async def test_rule_builds_the_primary_code_when_mode_is_known(db_session, world):
    await rollover.import_primaries(db_session, world.org.id, PRIMARIES)
    await rollover.import_loader(db_session, world.org.id, world.fall, LOADER)
    offering = await db_session.scalar(select(CourseOffering).where(CourseOffering.lms_code == "40113.202710"))
    item = await db_session.scalar(select(RolloverItem).where(RolloverItem.course_offering_id == offering.id))
    item.mode = "OL"  # until the mode rule exists, nothing sets this
    await rollover.match(db_session, world.org.id, item)
    primary = await db_session.get(Primary, item.primary_id)
    assert (item.match_source, primary.code) == ("rule", "GEO101_OL_SEM_PRIMARY")


async def test_settings_and_permissions(client, db_session, world, admin):
    resp = await client.put("/api/v1/admin/rollover/settings", json={"primary_code_pattern": "{mode}"})
    assert resp.status_code == 422 and "needs {subject}" in resp.json()["detail"]
    resp = await client.put(
        "/api/v1/admin/rollover/settings",
        json={"primary_code_pattern": PATTERN, "lengths": {" full ": "sem", "": "x"}, "course_column": "Course Code"},
    )
    assert resp.status_code == 200
    assert (resp.json()["lengths"], resp.json()["course_column"]) == ({"FULL": "SEM"}, "Course Code")
    assert resp.json()["section_code_pattern"] == "{crn}.{term}"
    tried = (await client.post(
        "/api/v1/admin/rollover/settings/try", json={"primary_code_pattern": PATTERN, "code": "BIO120_OL_TER_PRIMARY"}
    )).json()
    assert (tried["course"], tried["mode"], tried["length"]) == ("BIO120", "OL", "TER")

    resp = await client.post(f"/api/v1/admin/rollover/terms/{world.fall.id}/import", json={"text": "Name\nx\n"})
    assert resp.status_code == 422 and "CourseID" in resp.json()["detail"]

    librarian = await world.person(db_session, "lib", access.LIBRARIAN, (ScopeType.organization, world.org.id))
    await sign_in(client, librarian)
    assert (await client.get(f"/api/v1/admin/rollover/terms/{world.fall.id}/items")).status_code == 403
