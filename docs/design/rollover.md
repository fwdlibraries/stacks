# Design: term rollover

Status: draft for discussion. Course codes, people and term codes below are invented examples.

## The problem

Every term, the library has to decide where each new course section's reading list comes from, check it, and have it ready before students arrive. Stacks has nothing for this yet:

- Reading lists belong to a course, not a term, so every term's sections share one live list. Editing the Winter list also changes what Fall students saw, and click statistics can't be split by term.
- A new LMS course shell is linked to an existing course only when the LMS course code is identical. Live section codes rarely are.
- Libraries run rollover from spreadsheets: an SIS export, lookups that pair each section with its source, and a loader file for the reading list system.

## Goals

- Support the three ways institutions run course copies in their LMS, and let Stacks follow the same model.
- Replace the rollover spreadsheets with a workspace where librarians see each upcoming section, its source, its problems and its status.
- Make each term's list its own record, kept as it was after the term ends.
- Match new LMS shells to their sections exactly, with no guessing from course titles.

Not covered here: deep links to single citations (but see "Stable item keys"), and new link-checking features beyond reporting their results in the workspace.

## The three models

| Model | Where edits happen | Where a new section's list comes from |
|---|---|---|
| **Copy forward** | The live section's list | The same course's section from the previous term |
| **Primary course** | A primary list that isn't tied to a term | The primary list for that course variant |
| **Start fresh** | The live section's list | Nothing: an empty draft (optionally "start from…") |

The copying machinery, the record of where each list came from, and archived terms are shared by all three. The models differ only in where the source comes from.

### Rules of the primary model

- **Live sections never write back to the primary.** This is built in and can't be configured: the primary model exists to keep improvements in one place.
- **Copies are snapshots.** A section's list is copied from the primary at rollover.
- **Re-copy during review.** Until a section is published, a librarian can copy it from its primary again to pick up recent changes.
- **No automatic updates after publishing.** If the primary changes later, the live list shows a notice: *"The primary list has changed since this was copied."* If the policy lets the section be edited, its instructor can review the changes. The notice is informational; nothing changes automatically.

## Policies

Settings can be made at four levels: **site → college → department → course**. The nearest level that sets a value wins. Any level can **enforce** a value, which the levels below then can't change.

| Setting | Values | Default |
|---|---|---|
| Rollover model | copy forward / primary / start fresh | copy forward |
| Live list editing | locked / editable | editable |
| Publish copies | when approved / at term start | at term start |

The admin screen shows the effective value at each level, and which level set or enforced it.

## Data model changes

- **Term** (new): organization, SIS code (`202710`), name (*Fall 2027*), start and end dates, rollover date, list deadline (Leganto's `SUBMIT_LISTS_BY`), and status (upcoming / rolling over / live / archived). It replaces the free-text `term` slug, and existing slugs are migrated.
- **Primary** (new): a course variant's primary shell. It links to the course, and stores its code (`GEO101_OL_TER_PRIMARY`), its variant parts (mode, length), its LMS context ID, and its reading list. Several primaries can belong to one course.
- **CourseOffering** (a live section) gains:
  - its term, CRN or section ID, and LMS shell code (`40112.202710`);
  - its department, instructors, and resolved primary;
  - how that primary was found: rule / remembered / file / manual.
- **ReadingList** gains:
  - `kind`: primary or section;
  - the offering it belongs to (null for primary lists);
  - `copied_from_list_id`, the time of the copy, and the source's version at copy time (for the "primary has changed" notice).

  The course link stays, so Reports can group a course's lists across terms.
- **RolloverItem** (new, one per section per term):
  - source list and source rule;
  - status: *needs source → in review → approved → copied → published*, or *skipped*;
  - assignee, notes, and who decided and when.
- **RolloverPolicy** (new): scope (site / college / department / course), scope ID, setting, value, enforced.
- **Remembered match** (new): a librarian's manual choice for a course and section pattern, reused in later terms.

### Stable item keys

Each citation and section gets an `item_key`, which is kept whenever a list is copied. Reports can then follow one reading across terms, and future deep links can keep working after a copy.

## Matching sections to primaries

A section's primary is found in this order. The first rule that gives exactly one answer wins.

1. **Manual:** a librarian picked it for this section.
2. **File:** an imported loader file names it (`OLD_COURSE_CODE`).
3. **Remembered:** the same course and section pattern went to a primary in an earlier term.
4. **Rule:** build the expected primary code from the section's fields and look it up among the known primaries.
5. **Only one fits:** the course has a single primary of the right length.

Anything left over goes to the **Needs a source** queue.

The rule is configured per organization; nothing here is specific to one institution:

- **Live shell code pattern:** for example `{crn}.{term}`.
- **Primary code pattern:** for example `{subject}{number}_{mode}_{length}_PRIMARY`.
- **Subject and number:** which column holds them (for example `SEARCH_ID1`, `GEO 101` → `GEO101`).
- **Length:** a table from part-of-term codes to length values (`FULL` → `SEM`, `PT1` → `TER`). Section dates in SIS exports are often term dates, so length isn't worked out from dates.
- **Mode:** an expression over SIS columns giving `F2F` or `OL`. Until that's set up, rules 3 and 5 cover most sections.

Stacks learns about primaries in three ways: when someone launches Stacks from a primary shell (its code matches the primary pattern), from an imported list of primary shells, or by a librarian adding one.

## The rollover workspace

There's one workspace per upcoming term, under Administration.

- **The table** has one row per section: section code, course, primary or source, status, assignee, and a column for problems found. It can be filtered by college, department, status, assignee and "has problems", and rows can be selected for bulk actions (assign, approve, skip, set source).
- **Problems** come from catalogue sync (removed or hidden records), link checks, empty lists, and sources with unpublished changes.
- **Section detail** shows the proposed list, a comparison with the source, how the match was made, and actions: change source, re-copy, approve, skip.
- **Import:** the Alma/Leganto course loader file (the same columns libraries produce today), a plain SIS section export with a column-mapping step, or a list of primary shells.
- **Export:** CSV, including the course loader layout, for libraries that run both systems during a transition.

### Schedule

- **Before the rollover date:** sections are imported and matched, and librarians review them.
- **On the rollover date:** a nightly job copies every approved item into a draft section list. Approving an item after that date copies it straight away.
- **Publishing** follows the "Publish copies" policy.
- **When the term ends,** its lists are archived: read-only, and still visible in Reports.

## LMS launches

- **Live shell:** its code (the LTI context label) matches the section's LMS shell code, so Stacks opens that section's list.
- **Primary shell:** its code matches the primary pattern, so Stacks opens the primary list in the editor. Students launching from a primary shell see a notice, not the list.
- **Unknown shell:** staff are asked to copy the course's last list, use a primary, or start fresh. Students see "not available yet".

## Migration

Today each course has one list. On upgrade, that list is attached to the course's existing offerings as their section list. An organization that picks the primary model can then promote a list to primary for each course variant from the workspace.

## Delivery in stages

1. Terms, section lists, list copying with item keys, and exact launch matching.
2. The rollover workspace: imports, matching rules, the needs-a-source queue, review statuses.
3. Policies with inheritance and enforcement, and the "primary has changed" notice.
4. The scheduled job, archiving, and problem checks (catalogue, links).

## Open questions

- **Mode rule:** which SIS fields decide `F2F` or `OL` (being worked out by the institution).
- **Cross-listed sections:** one LMS shell for several CRNs. Does it get one list, or one per CRN?
- **Late changes:** a section added after the rollover date, or an instructor change during review.
- **Approval:** who can approve a section (librarian, instructor, department admin), and is that a policy too?
