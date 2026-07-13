#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if docker ps >/dev/null 2>&1; then
  DOCKER=(docker)
  COMPOSE=(docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/.env")
else
  DOCKER=(sudo docker)
  COMPOSE=(sudo docker compose -f "$ROOT/docker-compose.yml" --env-file "$ROOT/.env")
fi

require_env() {
  if [[ ! -f "$ROOT/.env" ]]; then
    echo ".env is missing. Create it from .env.example and fill required secrets."
    exit 1
  fi
}

# Reads a single KEY=value line from .env (the actual file docker compose
# uses via --env-file), never the invoking shell's ambient environment --
# those two can silently diverge (e.g. a staging .env with a non-default
# POSTGRES_DB that the operator never exported into their own shell), which
# would defeat any safety check built on the wrong value.
env_value() {
  local key="$1"
  local default_value="$2"
  local value=""
  if [[ -f "$ROOT/.env" ]]; then
    value=$(grep -E "^${key}=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2-)
  fi
  echo "${value:-$default_value}"
}

# Optional compose override, opted into via .env (e.g. the staging droplet sets
# COMPOSE_OVERRIDE_FILE=ops/docker-compose.staging.yml so every subcommand keeps
# the staging port binding instead of silently dropping back to the dev-only
# 127.0.0.1 default). Absent key = local dev, behavior unchanged.
OVERRIDE_FILE="$(env_value COMPOSE_OVERRIDE_FILE "")"
if [[ -n "$OVERRIDE_FILE" ]]; then
  [[ "$OVERRIDE_FILE" = /* ]] || OVERRIDE_FILE="$ROOT/$OVERRIDE_FILE"
  if [[ ! -f "$OVERRIDE_FILE" ]]; then
    echo "COMPOSE_OVERRIDE_FILE points at a missing file: $OVERRIDE_FILE"
    exit 1
  fi
  COMPOSE+=(-f "$OVERRIDE_FILE")
fi

compose() {
  require_env
  "${COMPOSE[@]}" "$@"
}

migrate() {
  compose run --rm backend alembic upgrade head
}

migrate_down() {
  local target_revision="${1:-}"
  if [[ -z "$target_revision" ]]; then
    echo "Usage: scripts/optimusctl.sh migrate-down <revision>"
    echo "Deploy runbook: rehearse this against a scratch/staging database before"
    echo "trusting it against a real deploy -- downgrades are not exercised by"
    echo "the automated test suite, only by this explicit, deliberate command."
    exit 1
  fi
  compose run --rm backend alembic downgrade "$target_revision"
}

bootstrap_owner() {
  compose run --rm backend python -m app.bootstrap_owner
}

seed() {
  compose exec -T postgres psql -U "${POSTGRES_USER:-optimus}" -d "${POSTGRES_DB:-optimus_os}" -v ON_ERROR_STOP=1 < "$ROOT/ops/db/002_seed_demo_data.sql"
}

IMAGE_PREFIX="optimus-server"

tag_current_as_previous() {
  for svc in backend worker; do
    if "${DOCKER[@]}" image inspect "${IMAGE_PREFIX}-${svc}:latest" >/dev/null 2>&1; then
      "${DOCKER[@]}" tag "${IMAGE_PREFIX}-${svc}:latest" "${IMAGE_PREFIX}-${svc}:previous"
    fi
  done
}

rollback() {
  for svc in backend worker; do
    if ! "${DOCKER[@]}" image inspect "${IMAGE_PREFIX}-${svc}:previous" >/dev/null 2>&1; then
      echo "No ${IMAGE_PREFIX}-${svc}:previous image tag found -- nothing to roll back to."
      exit 1
    fi
  done
  for svc in backend worker; do
    "${DOCKER[@]}" tag "${IMAGE_PREFIX}-${svc}:previous" "${IMAGE_PREFIX}-${svc}:latest"
  done
  compose up -d --no-build backend worker
  echo "Rolled back backend/worker to the :previous image tag and restarted."
}

restore() {
  local dump_file="${1:-}"
  local target_db="${2:-optimus_os_restore_check}"
  local live_db
  live_db="$(env_value POSTGRES_DB optimus_os)"
  if [[ -z "$dump_file" ]]; then
    echo "Usage: scripts/optimusctl.sh restore <dump-file> [target-db]"
    echo "Restores into a scratch database (default: optimus_os_restore_check), never the live database."
    exit 1
  fi
  if [[ ! -f "$dump_file" ]]; then
    echo "Dump file not found: $dump_file"
    exit 1
  fi
  if [[ ! "$target_db" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "target-db must be a plain identifier (letters, digits, underscore; not starting with a digit): $target_db"
    exit 1
  fi
  if [[ "$target_db" == "$live_db" ]]; then
    echo "Refusing to restore into '$target_db' -- that is the live database (POSTGRES_DB). Pass a different scratch name."
    exit 1
  fi
  case "$target_db" in
    postgres|template0|template1)
      echo "Refusing to restore into '$target_db' -- that is a PostgreSQL reserved/system database. Pass a different scratch name."
      exit 1
      ;;
  esac
  compose exec -T postgres psql -U "${POSTGRES_USER:-optimus}" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"${target_db}\";"
  compose exec -T postgres psql -U "${POSTGRES_USER:-optimus}" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"${target_db}\";"
  compose exec -T postgres psql -U "${POSTGRES_USER:-optimus}" -d "${target_db}" -v ON_ERROR_STOP=1 < "$dump_file"
  echo "Restored ${dump_file} into scratch database ${target_db}"
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
  migrate-down)
    shift || true
    migrate_down "$@"
    ;;
  bootstrap-owner)
    bootstrap_owner
    ;;
  seed)
    seed
    ;;
  restore)
    shift || true
    restore "$@"
    ;;
  backup)
    mkdir -p "$ROOT/backups"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    compose exec -T postgres pg_dump -U "${POSTGRES_USER:-optimus}" -d "${POSTGRES_DB:-optimus_os}" > "$ROOT/backups/optimus_os_${stamp}.sql"
    echo "Wrote backups/optimus_os_${stamp}.sql"
    ;;
  update)
    tag_current_as_previous
    compose build --pull backend worker
    compose up -d postgres redis backend worker frontend
    ;;
  rollback)
    rollback
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
  migrate-down <revision>  Roll a migration back to the given revision (rehearse before trusting)
  bootstrap-owner  Create the first owner account if none exists
  seed      Insert synthetic demonstration data
  backup    Write a local PostgreSQL dump under backups/
  restore   Restore a dump file into a scratch database (never the live one)
  update    Tag current images as :previous, pull base images, rebuild backend/worker, and restart
  rollback  Roll backend/worker back to the :previous image tag and restart
  health    Request http://127.0.0.1:8000/health
  ready     Request http://127.0.0.1:8000/ready
USAGE
    ;;
esac
