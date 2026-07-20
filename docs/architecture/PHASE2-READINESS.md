# Phase 2 Readiness Note — Evaluation Only

**Status:** Evaluation. **Nothing in this note is implemented.** No container was removed, no route moved, no deployment file changed for Phase 2. This exists so the three candidate Phase 2 changes are each independently scoped, evidenced, and risk-assessed before any one of them is separately approved.

**Hard rule carried from the roadmap:** the worker removal (2A), the nginx removal (2B), and the `main.py` router extraction (2C) are **three separate changes** — separate approvals, separate commits/PRs. They must not be combined. None may change public routes, response schemas, auth behavior, tenant behavior, startup order, or health checks. No infrastructure is removed on "appears inactive" alone — only on runtime + deployment evidence.

---

## 2A — Worker container removal

### Evidence gathered

- **What it is:** `scripts/optimus_worker.py` (booted by `docker-compose.yml` `worker` service as `python -m scripts.optimus_worker`) is a 60-second loop that calls `_tcp_dependency_ready(database_url, 5432)` and `_tcp_dependency_ready(redis_url, 6379)` and logs "passed"/"degraded". It opens **no** DB session, consumes **no** queue, runs **no** scheduled job.
- **No task queue anywhere:** grep for `celery | rq | arq | dramatiq | .delay( | .enqueue( | apply_async | task_queue` across `app/` and `scripts/` → **zero hits**. Nothing enqueues work for a worker to consume.
- **No importers:** nothing in `app/` or `tests/` imports `scripts.optimus_worker` except the two Phase 1 safety tests that reference its path/name (`test_background_job_tenant_safety.py`, and a string literal in `test_security_events.py`).
- **Same across environments:** dev, staging, and production all run the identical image + command. The staging overlay (`ops/docker-compose.staging.yml`) only overrides the `frontend` port; it does not touch or specialize `worker`. There is no separate prod worker definition anywhere.
- **Redundancy:** the worker's only actual behavior (a Postgres/Redis TCP reachability heartbeat) is already performed on demand by the backend's `GET /ready` endpoint (`_tcp_dependency_ready` for both), so removing the worker loses no signal that isn't already available.

### What would fail / must change if removed

Nothing functional. The touchpoints that must be updated in lockstep (all deployment/CI/doc, no app code):
- `docker-compose.yml` — remove the `worker` service block.
- `scripts/optimusctl.sh` — remove `worker` from `start`/`update`/`rollback`/build commands (lines ~129, 139, 145, 148–149, 190, 230–231, and the usage text).
- `.github/workflows/ci.yml` — the `docker-compose-integration` job (`build backend worker`, `up ... backend worker`, `scan_logs_for_secrets --services backend worker ...`) and the backup/rollback rehearsal.
- `docs/context/ARCHITECTURE.md` (documents + diagrams the worker), `docs/context/RELEASE_CHECKLIST.md`, `docs/context/CURRENT_STATE.md` — drop worker references.

### Recommendation: **Remove**, as its own change (Phase 2A)

The evidence bar the roadmap demands ("runtime and deployment evidence, not appearance") is met: proven no-op in code, no queue, no importer, identical across all environments, redundant with `/ready`. ADR-014 already records the re-introduction trigger (an async step >2–3s, or scheduled maintenance jobs → reintroduce as a Postgres `SKIP LOCKED` DB-backed queue, not Redis). This is the lowest-risk of the three.

**Scope (2A):** delete `scripts/optimus_worker.py` + the `worker` service + all deployment/CI/doc references above. **No app code, no schema, no route, no health-check change.**
**Tests / DoD:** `docker compose config -q` valid; CI docker-integration + backup/rollback rehearsal green without the worker; `optimusctl.sh start/update/rollback` succeed with `backend` + `frontend` only; `test_background_job_tenant_safety.py` updated (its subject file is gone — either delete it or repoint it at "no background job exists"); `docs/context/DECISIONS.md` records the removal + re-introduction trigger.
**Risk / rollback:** risk low (removing a process that does nothing). Rollback = revert the single commit; the `worker` service/definition returns from history. No data, no migration involved.

---

## 2B — Nginx (`frontend`) container removal

### Responsibility map (from `ops/nginx/default.conf` + compose)

| Responsibility | Handled by nginx today? | Detail |
|---|---|---|
| TLS termination | **No** | Listens on `:80` only. TLS terminates at Cloudflare's edge (ADR-011). |
| Reverse proxy | **Yes** | `/api/`, `/health`, `/ready` → `backend:8000`, `proxy_http_version 1.1`. |
| Static assets | **Yes** | Serves `/static/` (alias) + SPA fallback `try_files $uri $uri/ /index.html` from bind-mounted `app/static`. |
| Compression | **No** | No `gzip`. Cloudflare compresses at the edge. |
| Request/rate limits | **No** | No `limit_req`/`limit_conn`. Rate limiting is in the app (the registry consolidated in Phase 1). |
| Headers | **Partial** | Sets `Cache-Control: no-cache` on static + SPA (deliberate — the config comment explains it prevents Cloudflare serving stale JS/CSS for ~4h after a deploy). Injects `X-Forwarded-For` / `X-Forwarded-Proto` / `Host` on the proxy. Security headers (CSP etc.) come from the **app**, not nginx. |
| Buffering / timeouts | **Defaults only** | No explicit tuning. |
| WebSockets | **No** | `proxy_http_version 1.1` is set but no `Upgrade`/`Connection` headers; the app has no WebSocket endpoints. |
| Routing | **Yes** | Path-based: `/static/`, `/`, `/api/`, `/health`, `/ready`. |
| Security controls | **Compose-level** | `read_only` rootfs, tmpfs, `no-new-privileges` — on the container, not in the nginx config. |

### Replacement layer required if removed — and why this is the risky one

FastAPI already mounts `/static` (`app.mount("/static", StaticFiles(...))`), so raw static serving is partly covered. But three responsibilities have **no** current replacement, and one is load-bearing for Phase 1:

1. **SPA fallback** (`/` and unknown paths → `index.html`): needs a new catch-all route in FastAPI. Straightforward but must not shadow `/api/*` or `/health`/`/ready`.
2. **`Cache-Control: no-cache` on static/SPA**: without it, Cloudflare caches stale assets ~4h after each deploy (the config comment documents this as a real past problem). Needs an explicit header on the FastAPI static/SPA responses, with a test.
3. **`X-Forwarded-For` → `request.client.host`** (**critical, Phase-1-load-bearing**): the backend runs `uvicorn ... --proxy-headers`, so today `request.client.host` is derived from the `X-Forwarded-For` header nginx sets. **Phase 1's rate limiter and audit logging key on `request.client.host`.** If nginx is removed and Cloudflare talks to the backend directly, uvicorn's `--proxy-headers` must be configured with `forwarded_allow_ips` set to Cloudflare's IP ranges — otherwise either every client collapses into one rate-limit bucket (Cloudflare's edge IP) or `X-Forwarded-For` becomes spoofable, letting a caller forge their apparent IP to evade the login/signup/reset rate limits. This is a real security dependency, not a cosmetic one.

### Recommendation: **Defer** — do not remove in Phase 2 as currently scoped

The roadmap's own rule is explicit: "Do not recommend removal unless every responsibility has an explicit replacement and rollback plan." Two responsibilities (SPA-fallback + no-cache header) need net-new FastAPI code with tests, and the third (`X-Forwarded-For` trust) is a security-sensitive proxy-header-trust configuration that directly affects the rate limiting Phase 1 just hardened. That is enough surface, with enough security weight, that nginx removal should be its **own separately-designed change with a proxy-header-trust test proving `request.client.host` still resolves to the real client behind Cloudflare** — not a quick "serve static from FastAPI" simplification. Recommend deferring until that design exists; the container is cheap and currently correct.

**If/when done (2B), scope:** add FastAPI SPA-fallback route + `Cache-Control: no-cache` header + a verified `forwarded_allow_ips` (Cloudflare ranges) config; then remove the `frontend` service + `ops/nginx/*` + the staging overlay's frontend override. **No route/schema/auth change.**
**Tests / DoD (2B):** a test proving `request.client.host` resolves to the real client IP (not the proxy) given a forwarded chain; a test proving `/` and deep links serve `index.html` while `/api/*`, `/health`, `/ready` still route correctly; a test/asserted header proving static responses carry `no-cache`; the docker-integration + e2e CI jobs green with `frontend` gone.
**Risk / rollback:** risk **medium-high** (client-IP resolution feeds security controls; a misconfig silently weakens rate limiting). Rollback = revert the commit; `frontend`/nginx returns. Because a misconfig is *silent*, this one needs the proxy-header test as a hard gate before merge.

---

## 2C — `app/main.py` router extraction (code organization, not deployment)

### Measurements

- **Size:** 5,053 lines (down from 5,105 after Phase 1's rate-limiter consolidation).
- **Route groups:** ~26 clean URL-prefix groups mapping ~1:1 onto the store modules — e.g. `/api/auth` (13), `/api/invoices` (9), `/api/technicians` (8), `/api/customers` (8), `/api/reports` (7), `/api/billing` (7), `/api/work-orders` (6), `/api/estimates` (6), `/api/appointments` (6), down to `/api/context` (3), `/api/notifications` (3), `/api/support` (3).
- **Shared module state routers would need:** `logger`, `STATIC_DIR`, `_GIT_COMMIT`, `_APP_MIGRATION_HEAD`, the dependency aliases (`SettingsDep`, `DbSessionDep`, `AuthContextDep`, `VerifiedAuthContextDep`, `CurrentUserDep`, `OwnerAuthContextDep`, `OwnerOrTechnicianAuthContextDep`, `BillingAuthContextDep`, `SupportAuthContextDep`), the `_rate_limiters` registry + `enforce_*` helpers, and the store-exception→HTTP-status mapping pattern.
- **Middleware / startup order:** `configure_structured_logging`, `validate_production_config` (Phase 1), `_APP_MIGRATION_HEAD`, `app = FastAPI(...)`, `app.mount("/static", ...)`, `install_request_context_middleware`, CORS — all app-assembly; these **stay in `main.py`** and their order is untouched.
- **Circular-import risk:** low **if** the shared kernel (dependency aliases + `enforce_*` + exception mapping) moves to a leaf module (e.g. `app/api/deps.py`) that imports only `app.config`/`app.db`/`app.auth`/`app.security_events` — never a router — and routers import `deps` + their own store, never `main`. The `app` instance stays in `main.py`; routers are `include_router`'d there. No router imports `main`, so no cycle.

### Existing safety net that makes this low-risk

`tests/test_role_isolation.py::test_every_business_route_is_role_gated_as_expected` enumerates `main.app.routes` **at runtime** and asserts every route's actual auth-dependency graph against an allowlist — it does not care which file defines a route. That test (plus the per-domain functional test files and the AST tenant test) will fail loudly if a router move changes any route's path, method, or auth dependency, making each extraction step verifiable as behavior-preserving.

### Incremental plan (no route or API-contract change at any step)

1. **Extract shared kernel** into `app/api/deps.py` (dependency aliases, `enforce_*`, exception→status helpers). No route moves. Prove: full suite green, route table identical.
2. **Extract one small, clean group** (recommend `/api/context` (3) or `/api/notifications` (3)) into `app/api/routers/<group>.py` with an `APIRouter(tags=[...])`; `app.include_router(...)` in `main.py`. Prove: the runtime route-gating audit + that group's functional tests unchanged.
3. **Repeat per group**, smallest/cleanest first, **one PR per group** (or a small batch of trivial groups), each independently revertible. Larger groups (`auth`, `invoices`, `estimates`) last, once the pattern is proven.

### Recommendation: **Proceed (2C)** as the safest structural win — but as its own track, separate from 2A/2B

This is pure code organization with a strong existing runtime safety net and no deployment or contract surface. It is independent of the container questions and should not be bundled with them.

**Scope (2C):** mechanical route relocation into `APIRouter` modules behind a shared `deps.py`; **zero** changes to route paths, methods, `response_model`, `status_code`, auth dependencies, middleware, or startup.
**Tests / DoD (2C):** `test_role_isolation.py` route audit passes unchanged after every step; per-domain functional tests unchanged; `pyright` clean (no new circular imports); a diff review confirming each moved route body is byte-identical.
**Risk / rollback:** risk low (no behavior surface). Rollback = revert the per-group commit; that group's routes return to `main.py`. Because each step is one group, a problem is isolated to one group and one revert.

---

## Separate Phase 2A / 2B / 2C scopes — summary

| | 2A Worker | 2B Nginx | 2C Router extraction |
|---|---|---|---|
| Nature | Deployment | Deployment + security-sensitive | Code organization |
| Recommendation | **Remove** | **Defer** (needs proxy-header design) | **Proceed** (own track) |
| Touches app runtime? | No | Yes (static serving, client-IP) | No (pure relocation) |
| Security weight | None | High (rate-limit client-IP) | None |
| Risk | Low | Medium-high | Low |
| Approval | Separate | Separate (later) | Separate |

They must not share a commit or an approval.

---

## Recommended next approved goal

**2C (router extraction), steps 1–2 only**, as the next approved goal — it is the lowest-risk, highest-maintainability win, is fully independent of the container decisions, and is protected by the existing runtime route-gating audit. Do 2A (worker removal) as a small parallel or follow-on change once 2C's pattern is established. Hold 2B (nginx) until a dedicated proxy-header-trust design (with a `request.client.host` resolution test) is written and separately approved, because it touches the client-IP resolution the Phase 1 rate limiter depends on.

No Phase 2 work begins without explicit approval of that specific, separately-scoped goal.
