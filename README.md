# Stacks

**Open-source course reading lists for libraries.**

Instructors and librarians build reading lists in Stacks. The lists open inside the LMS through LTI 1.3, and students reach each reading through the library's own systems.

> **Note:** Stacks is in active development and not yet production-ready. Contributions, feedback and institutional interest are welcome.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

---

## Features

**Reading lists**
- Lists are organized into sections (Required, Week 1, Further reading…), with student notes and staff notes.
- Lists are drafts until published. A published list is public, limited to the institution, or unlisted (only people with the link can open it).
- Students don't need an account to read a public list.

**Adding citations**
- Search the library catalogue (Alma, Primo), or look up a DOI or ISBN (Crossref, Open Library).
- Import a bibliography in bulk (RIS, BibTeX or pasted text), then review the matches before adding them.
- The browser extension adds the article, book or page you're viewing ([extension/](extension/README.md)).
- A Z39.50 gateway is optional, for catalogues without an API.

**Getting students to the reading**
- Links are resolved when a student clicks. Stacks tries, in order: LibKey for direct article access, the Alma link resolver, a legal open-access copy (OpenAlex), and then the catalogue record or DOI.
- Records linked to the catalogue stay in sync with it, and Reports flag citations whose records were removed or hidden.
- Click statistics are counted without recording who clicked.

**LMS**
- Stacks works with Brightspace, Canvas, Moodle and other LTI 1.3 platforms. The first launch from a course sets it up in Stacks.
- Lists can take on the LMS's look, or the organization's own colours and logo.

**Administration**
- **Roles:** Administrator, Librarian, Instructor and Viewer. A role can apply to the whole organization, a college, a department or a single course.
- **Sign-in:** email and password, or single sign-on with OpenID Connect ([Entra setup guide](docs/sso/entra.md)). Entra app roles can be mapped to Stacks roles.
- **Settings screens:** the organization, library connections, link resolution, LMS registrations, people, and reports.
- **Several organizations:** one installation can serve several, each recognized by its own web address.

**In development:** term rollover, with per-term reading lists and a workspace for copying lists from primary courses each term.

## Quick start

```bash
git clone https://github.com/fwdlibraries/stacks
cd stacks
./scripts/setup-dev.sh
```

The script:
1. creates `.env` from `.env.example` (set `SECRET_KEY` and `POSTGRES_PASSWORD` when it asks);
2. installs the frontend's dependencies;
3. starts PostgreSQL and Redis, runs the database migrations and adds a demo reading list;
4. starts the API, the background worker and the frontend dev server.

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Demo list | http://localhost:5173/public/demo/HIST101/fall-2026 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/api/docs |

Then create an administrator to sign in with:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
  exec app python -m app.cli create-user --org demo --email you@example.edu --name "Your Name" --role Administrator
```

`python -m app.cli --help` lists the other admin commands (roles, LTI platforms, library connections).

## Requirements

- Docker and Docker Compose v2
- Node.js 20+
- Python 3.12+ (only for backend development outside Docker)

## Architecture

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy (async), Alembic |
| Database | PostgreSQL 16 |
| Background jobs | Celery worker and beat, Redis |
| Frontend | React, Vite, TypeScript, React Bootstrap |
| Browser extension | Manifest V3 (Chrome, Edge, Firefox), no build step |
| File storage | S3-compatible |
| Z39.50 (optional) | YAZ gateway (`--profile z3950`) |

## Deployment

### Docker Compose (one institution or a few)

```bash
cp .env.example .env
# edit .env: SECRET_KEY, POSTGRES_PASSWORD, PUBLIC_BASE_URL, S3 settings, SMTP, ...
docker compose --env-file .env -f deploy/docker-compose.yml up -d
docker compose --env-file .env -f deploy/docker-compose.yml exec app alembic upgrade head
```

Migrations never run on startup, so run `alembic upgrade head` after each upgrade. To let your LMS show Stacks in a frame, set `FRAME_ANCESTORS` (or each organization's LMS addresses under Administration).

A Helm chart for Kubernetes is planned.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started, and the [style guide](docs/design/style-guide.md) for the interface and wording.

Good first issues are tagged [`good first issue`](https://github.com/fwdlibraries/stacks/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## License

[Apache-2.0](LICENSE) © Stacks Contributors

Stacks is free to use, modify, distribute and self-host, including commercially. Attribution is required; no warranty is implied.
