# Changelog

All notable changes to Stacks will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Stacks uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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
