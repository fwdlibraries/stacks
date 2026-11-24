#!/usr/bin/env bash
# setup-dev.sh — One-command development environment setup
# Usage: ./scripts/setup-dev.sh  OR  cd scripts && ./setup-dev.sh  OR  bash scripts/setup-dev.sh

set -euo pipefail

# Resolve repo root regardless of where the script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}→${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }

echo ""
echo "  ███████╗████████╗ █████╗  ██████╗██╗  ██╗███████╗"
echo "  ██╔════╝╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝██╔════╝"
echo "  ███████╗   ██║   ███████║██║     █████╔╝ ███████╗ "
echo "  ╚════██║   ██║   ██╔══██║██║     ██╔═██╗ ╚════██║ "
echo "  ███████║   ██║   ██║  ██║╚██████╗██║  ██╗███████║ "
echo "  ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝"
echo "  Dev environment setup"
echo ""
echo "  Repo root: ${REPO_ROOT}"
echo ""

# Check prerequisites
info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required but not installed."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node.js is required but not installed."; exit 1; }

info "Prerequisites OK"

# All compose commands run from the repo root, reading .env for variable substitution
COMPOSE=(docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml)

# Copy .env if it doesn't exist
if [ ! -f .env ]; then
    info "Creating .env from .env.example..."
    cp .env.example .env
    warn "Edit .env to set your configuration before continuing."
    warn "At minimum, set: SECRET_KEY, POSTGRES_PASSWORD"
    read -p "Press Enter when ready to continue..."
else
    info ".env already exists, skipping"
fi

# Install frontend dependencies
info "Installing frontend dependencies..."
cd frontend && npm install && cd "${REPO_ROOT}"

# Start services
info "Starting Docker services..."
"${COMPOSE[@]}" up -d db redis

# Wait for database
info "Waiting for database to be ready..."
until "${COMPOSE[@]}" exec db pg_isready -U "${POSTGRES_USER:-stacks}" >/dev/null 2>&1; do
    sleep 1
done

# Run migrations
info "Running database migrations..."
"${COMPOSE[@]}" run --rm app alembic upgrade head

# Start all services
info "Starting all services..."
"${COMPOSE[@]}" up -d

echo ""
echo -e "${GREEN}✓ Stacks dev environment is running!${NC}"
echo ""
echo "  Backend API:  http://localhost:8000"
echo "  API docs:     http://localhost:8000/api/docs"
echo "  Frontend:     http://localhost:5173"
echo "  Database:     localhost:5432 (user: stacks)"
echo ""
echo "  Logs: ${COMPOSE[*]} logs -f"
echo "  Stop: ${COMPOSE[*]} down"
echo ""
