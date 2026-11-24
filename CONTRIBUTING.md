# Contributing to Stacks

Thank you for your interest in contributing! Stacks is an open-source project and we welcome contributions of all kinds — bug fixes, new features, documentation improvements, and more.

## Getting Started

### 1. Set up your development environment

```bash
git clone https://github.com/fwdlibraries/stacks
cd stacks
./scripts/setup-dev.sh
```

See the [Development Guide](#development-guide) below for more detailed commands.

### 2. Find something to work on

- Check [`good first issue`](https://github.com/fwdlibraries/stacks/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) for beginner-friendly tasks
- Open an issue to discuss a new feature before building it

### 3. Make your changes

- Create a branch: `git checkout -b your-feature-name`
- Write tests for new functionality
- Ensure existing tests pass: `cd backend && pytest`
- Run linting: `cd backend && ruff check .`
- Run frontend typecheck: `cd frontend && npm run typecheck`

### 4. Submit a pull request

- Fill in the pull request template
- Link to any relevant issues
- PRs require passing CI before merge

## Development Guide

### Backend

```bash
cd backend
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=app

# Lint
ruff check .

# Type check
mypy app

# Generate a new migration after changing models
alembic revision --autogenerate -m "describe your change"
```

### Frontend

```bash
cd frontend
npm install

# Dev server (proxies API to localhost:8000)
npm run dev

# Typecheck
npm run typecheck

# Lint
npm run lint

# Regenerate TypeScript types from API spec (requires backend running)
npm run generate-types
```

### Database Migrations

Migrations run explicitly — they never run automatically on startup. Run these from the repo root:

```bash
COMPOSE="docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml"

# Apply all pending migrations
$COMPOSE exec app alembic upgrade head

# Create a new migration after changing SQLAlchemy models
$COMPOSE exec app alembic revision --autogenerate -m "add widget table"

# Downgrade one step
$COMPOSE exec app alembic downgrade -1
```

### Adding a New Import Handler

1. Create `backend/app/importers/your_source.py`
2. Extend `ImportHandler` from `app.importers.base`
3. Implement `fetch()` and `normalize()`
4. Register it in `app/importers/__init__.py`
5. Add a router endpoint in `app/routers/imports.py`
6. Add tests in `tests/test_importers/`

See `app/importers/z3950.py` for a reference implementation.

## Code Style

- **Python**: [Ruff](https://github.com/astral-sh/ruff) for linting and formatting. Line length: 100.
- **TypeScript**: ESLint with React Hooks plugin.
- **Commits**: Conventional commits preferred (`feat:`, `fix:`, `docs:`, `chore:`)

## Architecture Decisions

Before making significant architectural changes, please open an issue to discuss them. New significant decisions should be recorded as ADRs in `docs/architecture/`.

## Questions?

[File an issue](https://github.com/fwdlibraries/stacks/issues) — we're happy to help.
