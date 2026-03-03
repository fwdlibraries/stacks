#!/usr/bin/env bash
# setup-dev.sh — One-command development environment setup
# Usage: ./scripts/setup-dev.sh

set -euo pipefail

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

# Check prerequisites
info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { echo "Docker is required but not installed."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "Docker Compose is required but not installed."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node.js is required but not installed."; exit 1; }

info "Prerequisites OK"

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
cd frontend && npm install && cd ..

# Start services
info "Starting Docker services..."
docker compose \
    -f deploy/docker-compose.yml \
    -f deploy/docker-compose.dev.yml \
    up -d db redis yaz

# Wait for database
info "Waiting for database to be ready..."
until docker compose -f deploy/docker-compose.yml exec db pg_isready -U stacks >/dev/null 2>&1; do
    sleep 1
done

# Run migrations
info "Running database migrations..."
docker compose \
    -f deploy/docker-compose.yml \
    -f deploy/docker-compose.dev.yml \
    run --rm app alembic upgrade head

# Start all services
info "Starting all services..."
docker compose \
    -f deploy/docker-compose.yml \
    -f deploy/docker-compose.dev.yml \
    up -d

echo ""
echo -e "${GREEN}✓ Stacks dev environment is running!${NC}"
echo ""
echo "  Backend API:  http://localhost:8000"
echo "  API docs:     http://localhost:8000/api/docs"
echo "  Frontend:     http://localhost:5173"
echo "  Database:     localhost:5432 (user: stacks)"
echo ""
echo "  Logs: docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml logs -f"
echo "  Stop: docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml down"
echo ""
