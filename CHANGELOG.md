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
