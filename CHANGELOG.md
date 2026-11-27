# Changelog

All notable changes to Stacks will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Stacks uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Changed
- New default look: neutral greys, one blue accent and bundled Inter, with WCAG AA contrast throughout (fixes the Slate link and Warm Grey text failures). Organizations on Custom keep their saved colours; the classic serif fonts are still offered there.
- Administration has a left sidebar instead of tabs; Reports shows stat tiles and titled panels.
- Student reading lists have a course header, an "On this list" section index, soft type badges and link buttons.

### Added
- Terms (rollover stage 1, see docs/design/rollover.md): Administration › Terms manages teaching terms (code, name, dates, rollover and lists-due dates), and an LMS course code pattern such as `{crn}.{term}` lets launches find their term and section. Each term of a course can have its own reading list: "Copy to another term" in the editor makes a draft copy that keeps each item's identity across terms. Existing lists stay shared by every term, as before.
- Rollover workspace, first part (rollover stage 2): Administration › Rollover imports a term's sections from an Alma/Leganto course loader file and a list of primary shells, then finds each section's primary (loader file's `OLD_COURSE_CODE`, a remembered choice, a code rule, or the course's only primary of that length). Sections it can't match wait under "Needs a source"; librarians choose a primary (remembered for later terms), approve or skip, singly or in bulk. Column names, the primary code pattern and the part-of-term → length table are organization settings.
- Initial project scaffold
- Database schema for org hierarchy, reading lists, citations, users, LTI
- FastAPI backend with health endpoints
- Z39.50 import handler via YAZ sidecar
- Manual citation entry with DOI/Open Library lookup assist
- Import pipeline with staging/review flow
- React + Vite frontend scaffold with public list view
- CitationCard component with structured display
- WebSocket client with reconnection logic
- Docker Compose dev and production configurations
- GitHub Actions CI and Docker image build workflows
- Architecture design document
