# Frontend Audit

Date: 2026-07-01

## Scope

This resumed the existing frontend audit from the stack-start step against the live local Docker stack at:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:8000`
- Repository: `/home/dejake/optimus-server`

Per instruction, this document stops before implementation changes.

## Stack Verification

Verified with `docker ps` on 2026-07-01:

| Service | Container | Status | Published ports |
| --- | --- | --- | --- |
| Frontend | `optimus-server-frontend-1` | Up | `127.0.0.1:5173->80/tcp` |
| Backend | `optimus-server-backend-1` | Up | `127.0.0.1:8000->8000/tcp` |
| Worker | `optimus-server-worker-1` | Up | internal only |
| Postgres | `optimus-server-postgres-1` | Up, healthy | internal `5432` |
| Redis | `optimus-server-redis-1` | Up, healthy | internal `6379` |

Verified HTTP responses:

| Check | Result |
| --- | --- |
| `GET /` on frontend | `200 OK` |
| `GET /static/app.js` | `200 OK`, `Content-Type: application/javascript` |
| `GET /static/styles.css` | `200 OK`, `Content-Type: text/css` |
| `GET /health` | `200 OK` |
| `GET /ready` | `200 OK`, `postgres: true`, `redis: true` |
| `GET /openapi.json` | `200 OK` |
| `OPTIONS /api/chat` from `http://127.0.0.1:5173` | `200 OK`, CORS origin allowed |

Observed `/health` payload summary:

- Version: `7.0.1`
- Business name: `Landon Motor Works`
- `web_search_configured: true`
- `owner_full_control: true`
- `agent_delegation_enabled: true`

## Baseline Screenshots

Fresh screenshots captured from the running stack:

- [baseline-dashboard-desktop.png](/home/dejake/optimus-server/docs/screenshots/baseline-dashboard-desktop.png)
- [baseline-dashboard-mobile.png](/home/dejake/optimus-server/docs/screenshots/baseline-dashboard-mobile.png)
- [repaired-dashboard.png](/home/dejake/optimus-server/docs/screenshots/repaired-dashboard.png)
- [optimus-chat.png](/home/dejake/optimus-server/docs/screenshots/optimus-chat.png)
- [estimates.png](/home/dejake/optimus-server/docs/screenshots/estimates.png)
- [system-status.png](/home/dejake/optimus-server/docs/screenshots/system-status.png)

Reference images already present in the repo:

- [original-reference-desktop.png](/home/dejake/optimus-server/docs/screenshots/original-reference-desktop.png)
- [original-reference-mobile.png](/home/dejake/optimus-server/docs/screenshots/original-reference-mobile.png)

## Frontend Surface Found

The served UI is a static single-page app from:

- `app/static/index.html`
- `app/static/app.js`
- `app/static/styles.css`

Primary in-app views:

- `dashboard`
- `chat`
- `estimate`
- `system`

No customer-management or work-order-management screens were found in the live frontend for:

- Customers
- Vehicles
- Work orders
- Approval queue

## Backend Route Inventory Relevant To Frontend

Routes present in OpenAPI and observed live:

- `GET /health`
- `GET /ready`
- `POST /api/location/resolve`
- `POST /api/chat`
- `POST /api/estimate`

Routes requested by the broader shop workflow but not present:

- `GET/POST /api/auth/login` -> `404`
- `GET /api/auth/status` -> `404`
- `GET/POST /api/customers` -> `404`
- `GET/POST /api/vehicles` -> `404`
- `GET/POST /api/work-orders` -> `404`
- `GET/POST /api/approvals` -> `404`

## Exercised UI Behavior

Observed in Playwright against the live stack:

| Flow | Observed result | Pass/Fail |
| --- | --- | --- |
| Initial load | Dashboard renders successfully | Pass |
| Hero `Talk to Optimus` | Navigates to chat view | Pass |
| Hero `Build an estimate` | Navigates to estimate view | Pass |
| `Decode VIN` prompt chip | Navigates to chat and pre-fills prompt text | Pass |
| Topbar location chip | Navigates to system view | Pass |
| Mobile menu button | Expands sidebar on mobile baseline | Pass |
| `Run check` in system view | Shows backend online state | Pass |
| Chat submit without token | Visible `Command failed` state after `401` | Fail for authenticated workflow |
| Estimate submit without token after setting ZIP | Visible `Estimate failed` state after `401` | Fail for authenticated workflow |
| Location resolve without token | Backend returns `401` | Fail for authenticated workflow |

Important audit constraint: a UI flow is not counted as passing merely because the request fired. The authenticated business workflows do not pass in the current baseline because they end in `401 Unauthorized` and no successful signed-in flow was available to verify.

## Browser Audit Output

`node scripts/ui_connection_audit_playwright.js` completed successfully and reported:

- Console errors: 2
- Failed requests: 0 transport failures
- API network observed:
  - `200 GET http://localhost:8000/health`
  - `401 POST http://localhost:8000/api/chat`
  - `401 POST http://localhost:8000/api/estimate`
  - `200 GET http://localhost:8000/health`

Console errors were the browser reporting the `401` API responses. No separate frontend JavaScript exception was observed in this run.

## Assessment

What is working:

- Docker stack is up and healthy.
- Frontend assets are served with the expected response types.
- The static SPA renders and navigates correctly between its four built-in views.
- Health-check wiring from frontend to backend works.
- Error states for protected chat and estimate actions are visible rather than silent.

What is not passing:

- No authenticated frontend workflow was available to verify successful chat, location resolve, or estimate generation.
- No login entry point exists in the served UI.
- No backend auth/login route exists for the frontend to use.
- No customers, vehicles, work-orders, or approvals routes or views exist in the current baseline.

## Stop Point

This audit resumed from stack-start, verified the live stack, captured the current baseline screenshots, and documented the frontend and API baseline. No implementation changes were made as instructed.
