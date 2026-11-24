"""Seed a demo organization with one published reading list.

    python -m app.seed

Idempotent: does nothing if the demo organization already exists. Afterwards the
student view is at /public/demo/HIST101/fall-2026.
"""
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.models import (
    Citation,
    College,
    CourseOffering,
    CourseTemplate,
    Department,
    ListSection,
    Organization,
    ReadingList,
    ResourceType,
)

DEMO_ORG_SLUG = "demo"
DEMO_COURSE_CODE = "HIST101"
DEMO_TERM = "fall-2026"


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(Organization).where(Organization.slug == DEMO_ORG_SLUG))
        if existing is not None:
            print(f"Demo organization '{DEMO_ORG_SLUG}' already exists; nothing to do.")
            return

        org = Organization(name="Demo University", slug=DEMO_ORG_SLUG)
        college = College(organization=org, name="College of Arts and Sciences", code="CAS")
        dept = Department(college=college, name="History", code="HIST")
        course = CourseTemplate(
            department=dept, code=DEMO_COURSE_CODE, name="Introduction to Historical Methods"
        )
        CourseOffering(template=course, term=DEMO_TERM)

        reading_list = ReadingList(
            course_template=course,
            title="HIST 101 Reading List",
            description="Readings for Introduction to Historical Methods. Complete each week's "
            "required readings before the seminar.",
            visibility="public",
            is_published=True,
        )

        foundations = ListSection(reading_list=reading_list, title="Required", sort_order=0)
        week1 = ListSection(
            reading_list=reading_list,
            title="Week 1: What is history?",
            description="Two classic reflections on the historian's task.",
            sort_order=1,
        )
        supplemental = ListSection(reading_list=reading_list, title="Supplemental", sort_order=2)

        citations = [
            Citation(
                section=foundations,
                sort_order=0,
                resource_type=ResourceType.book,
                title="What Is History?",
                author=["Carr, Edward Hallett"],
                year=1961,
                publisher="Macmillan",
                place_of_publication="London",
                student_note="Read chapters 1 and 2 before the first seminar.",
                staff_note="Course reserve copy at the main desk. Not shown to students.",
            ),
            Citation(
                section=week1,
                sort_order=0,
                resource_type=ResourceType.book,
                title="The Historian's Craft",
                author=["Bloch, Marc"],
                year=1953,
                publisher="Alfred A. Knopf",
                place_of_publication="New York",
            ),
            Citation(
                section=week1,
                sort_order=1,
                resource_type=ResourceType.journal_article,
                title="Gender: A Useful Category of Historical Analysis",
                author=["Scott, Joan W."],
                year=1986,
                publisher="American Historical Review",
                volume="91",
                issue="5",
                pages="1053–1075",
                doi="10.2307/1864376",
            ),
            Citation(
                section=supplemental,
                sort_order=0,
                resource_type=ResourceType.website,
                title="The Chicago Manual of Style Online",
                url="https://www.chicagomanualofstyle.org/",
                is_required=False,
                student_note="Reference for footnote and bibliography formatting.",
            ),
        ]
        db.add_all([org, *citations])
        await db.commit()

        print(
            f"Seeded '{org.name}' with {len(citations)} citations. Student view: "
            f"/public/{DEMO_ORG_SLUG}/{DEMO_COURSE_CODE}/{DEMO_TERM}"
        )


if __name__ == "__main__":
    asyncio.run(seed())
