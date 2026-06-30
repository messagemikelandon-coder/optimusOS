#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if docker ps >/dev/null 2>&1; then
  COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/.env")
else
  COMPOSE=(sudo docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/.env")
fi

require_env() {
  if [[ ! -f "$ROOT/.env" ]]; then
    echo ".env is missing. Create it from .env.example and fill required secrets."
    exit 1
  fi
}

compose() {
  require_env
  "${COMPOSE[@]}" "$@"
}

migrate() {
  compose run --rm backend alembic upgrade head
}

seed() {
  compose exec -T postgres psql -U "${POSTGRES_USER:-optimus}" -d "${POSTGRES_DB:-optimus_os}" -v ON_ERROR_STOP=1 < "$ROOT/ops/db/002_seed_demo_data.sql"
}

case "${1:-help}" in
  start)
    compose up -d --build postgres redis backend worker frontend
    ;;
  stop)
    compose down
    ;;
  restart)
    compose restart
    ;;
  status)
    compose ps
    ;;
  logs)
    shift || true
    compose logs -f --tail=200 "$@"
    ;;
  migrate)
    migrate
    ;;
  seed)
    seed
    ;;
  backup)
    mkdir -p "$ROOT/backups"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    compose exec -T postgres pg_dump -U "${POSTGRES_USER:-optimus}" -d "${POSTGRES_DB:-optimus_os}" > "$ROOT/backups/optimus_os_${stamp}.sql"
    echo "Wrote backups/optimus_os_${stamp}.sql"
    ;;
  update)
    compose build --pull backend worker
    compose up -d postgres redis backend worker frontend
    ;;
  health)
    curl -fsS http://127.0.0.1:8000/health
    echo
    ;;
  ready)
    curl -fsS http://127.0.0.1:8000/ready
    echo
    ;;
  *)
    cat <<'USAGE'
Usage: scripts/optimusctl.sh <command>

Commands:
  start     Build and start PostgreSQL, Redis, backend, worker, and frontend
  stop      Stop local containers
  restart   Restart local containers
  status    Show container status
  logs      Follow logs, optionally pass service names
  migrate   Apply local PostgreSQL foundation migration
  seed      Insert synthetic demonstration data
  backup    Write a local PostgreSQL dump under backups/
  update    Pull base images, rebuild backend/worker, and restart
  health    Request http://127.0.0.1:8000/health
  ready     Request http://127.0.0.1:8000/ready
USAGE
    ;;
esac
