# Changelog

All notable changes to Stacks will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Stacks uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

There's no release yet. Everything so far is listed here, grouped by area, with the pull request that added it.

### Changed
- Sign-ins are server-side sessions:
  - Refresh tokens work once and rotate, and reusing an old one ends the session.
  - Logout ends the session at once.
  - People can sign out their other sessions, and organization-wide administrators can sign someone out everywhere. Turning an account off does that too.
  - Access tokens now last 15 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`, was 60).
  - Existing sign-ins end with this upgrade (migration `b3d5f7a9c1e2`).
- LTI tool private keys are encrypted at rest, like library API keys (migration `9a1f3c5e7b2d`). Back up `CREDENTIALS_KEY` (or `SECRET_KEY`, if it's unset), because the keys can't be read without it. The unused `LTI_PRIVATE_KEY_STORAGE` setting is removed.
- New default look (#30):
  - Neutral greys, one blue accent and bundled Inter, with WCAG AA contrast throughout. This fixes the failing Slate link and Warm Grey text colours.
  - Organizations on Custom keep their saved colours, and the classic serif fonts are still offered there.
- Administration has a left sidebar instead of tabs. Reports shows stat tiles and titled panels (#30).
- Student reading lists have a course header, an "On this list" section index, soft type badges and link buttons (#30).

### Added

**Reading lists**
- Lists, sections and citations that can be edited, with drafts and publishing (#6), and drag-and-drop reordering (#7).
- Public list pages for students, with a demo list seeded in development (#4).
- Lists can be seen only within your organization, and editing is limited by role (#5, #22).

**Adding citations**
- Manual entry, with DOI and Open Library lookups to fill in the details.
- A lookup pipeline over Alma, Primo, Crossref and Open Library, configured per organization (#12, #13), and library search in the add-citation dialog (#14).
- Bulk import: paste or upload references (RIS, BibTeX or plain text), review the matches, then add them (#18).
- A browser extension for Chrome, Edge and Firefox that adds the page you're viewing to a list (#19).
- An optional Z39.50 import through a YAZ gateway (`--profile z3950`).

**Links and the catalogue**
- Student links built from the current discovery settings (#15).
- Links resolved when a student clicks, trying in order: LibKey, the Alma link resolver, open access (OpenAlex), then a fallback. Clicks are counted anonymously (#16).
- A nightly sync for citations linked to Alma records (#17), and "Sync now" with operations reports (#26).

**LMS**
- LTI 1.3 launches: a course is set up in Stacks the first time the LMS opens it, and people are signed in from the LMS (#8).
- Stacks can be shown in an LMS frame, using CSP `frame-ancestors` (#9).

**Accounts and access**
- Email and password sign-in (#5), paused after repeated failed attempts (#21).
- Roles (Administrator, Librarian, Instructor, Viewer). A role can apply to the whole organization, a college, a department or one course (#22).
- Single sign-on with OpenID Connect, for Entra and other providers, with an optional mapping from Entra app roles to Stacks roles (#29). See docs/sso/entra.md.

**Organizations and administration**
- Requests are matched to an organization by hostname, and each organization has its own settings (#23).
- Administration screens:
  - organization, library connections and link resolution (#24)
  - LMS registrations, and people and roles (#25)
  - reports (#26)
- Look and feel for each organization: standard, match the LMS, or custom colours and logo (#27). The match-LMS option has Brightspace, Canvas and Moodle looks (#28).

**Terms and rollover** (see docs/design/rollover.md, #31)
- Terms (#32):
  - Administration › Terms manages teaching terms: code, name, dates, and rollover and lists-due dates.
  - An LMS course code pattern such as `{crn}.{term}` lets launches find their term and section.
  - Each term of a course can have its own reading list. "Copy to another term" makes a draft copy, and each item keeps its identity across terms.
  - Existing lists stay shared by every term, as before.
- Rollover workspace, first part (#33):
  - Administration › Rollover imports a term's sections from an Alma/Leganto course loader file, and a list of primary shells.
  - It then finds each section's primary, trying in order: the loader file's `OLD_COURSE_CODE`, a remembered choice, a code rule, or the course's only primary of that length.
  - Sections it can't match wait under "Needs a source". Librarians choose a primary, which Stacks remembers for later terms, and approve or skip sections one at a time or in bulk.
  - Column names, the primary code pattern and the table from part-of-term values to lengths are organization settings.

**Development**
- Project scaffold:
  - backend: FastAPI and the database schema
  - frontend: React and Vite, with separate editor and public apps (#3)
  - Docker Compose for development and production (#2), and a first database migration (#4)
- GitHub Actions CI for the backend, frontend, extension and Docker images (#10).
- A dev site behind a Cloudflare tunnel, serving a production build behind a hardened proxy (#11, #20).
- `.env.example`, and working README references (#1).
