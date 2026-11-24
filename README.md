# Stacks

**Open-source course reading list and citation management platform.**

Stacks lets instructors and librarians build reading lists that embed directly in any LMS via LTI 1.3.

> **Note:** Stacks is currently a proof of concept. It is not yet production-ready. Contributions, feedback, and institutional interest are welcome.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

---

## Features

- **Reading lists** — organized into sections (Required, Week 1, Supplemental, etc.)
- **LTI 1.3** — embeds directly in Brightspace, Canvas, Moodle, and Blackboard
- **Citation import** — Z39.50 library catalog search, DOI lookup, manual entry
- **Public by default** — students access lists without authentication
- **Librarian workflow** — librarians manage citations on behalf of instructors
- **Open source** — Apache-2.0, self-hosted, no vendor lock-in

## Quick Start

```bash
git clone https://github.com/fwdlibraries/stacks
cd stacks
./scripts/setup-dev.sh
```

That's it. The script will:
1. Create a `.env` from `.env.example`
2. Start PostgreSQL, Redis, and the YAZ Z39.50 gateway
3. Run database migrations
4. Start the backend API and frontend dev server

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/api/docs |

## Requirements

- Docker + Docker Compose
- Node.js 20+
- Python 3.12+ (for local backend development without Docker)

## Architecture

Stacks is built on:

| Layer | Technology |
|---|---|
| Backend | Python / FastAPI |
| Database | PostgreSQL + pgvector |
| Cache / Queue | Redis + Celery |
| Frontend | React + Vite + TypeScript |
| Styling | React Bootstrap |
| Z39.50 | YAZ sidecar |
| Object storage | S3-compatible |

## Deployment

### Docker Compose (recommended for single institutions)

```bash
cp .env.example .env
# edit .env — set SECRET_KEY, POSTGRES_PASSWORD, S3_BUCKET, etc.
docker compose --env-file .env -f deploy/docker-compose.yml up -d
docker compose --env-file .env -f deploy/docker-compose.yml exec app alembic upgrade head
```

A Helm chart for Kubernetes deployments is planned but not yet available.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

Good first issues are tagged [`good first issue`](https://github.com/fwdlibraries/stacks/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License

[Apache-2.0](LICENSE) © Stacks Contributors

Stacks is free to use, modify, distribute, and self-host — including for commercial purposes. Attribution required; no warranty implied.
