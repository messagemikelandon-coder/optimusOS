# OptimusOS UI Connection Audit

Date: 2026-06-30

## Scope

This audit covers the local OptimusOS repository at `/home/dejake/optimus-server`, the active Docker-based local stack, the static Optimus frontend, the FastAPI backend, and browser behavior at `http://127.0.0.1:5173`.

## Git Checkpoint

- Checkpoint commit created before repair changes: `6d02a0f checkpoint: preserve current local deployment before ui audit`
- Prior repository foundation checkpoint: `fc9ba0a checkpoint: preserve existing optimus foundation`
- `.env` remains ignored and was not committed.

## Original Interface Files Found

The only Optimus interface source files found in the permitted repository tree are:

- `app/static/index.html`
- `app/static/styles.css`
- `app/static/app.js`
- `app/static/favicon.svg`
- `app/static/logo-mark.svg`
- `app/static/manifest.webmanifest`
- `PREVIEW_DESKTOP.png`
- `PREVIEW_MOBILE.png`

Archived/package copies of the same static interface were found in:

- `dist/optimus_internet_local_parts-7.0.1/app/static/`
- `dist/optimusos-local-20260630/app/static/`
- `dist/optimus_internet_local_parts-7.0.1/PREVIEW_DESKTOP.png`
- `dist/optimus_internet_local_parts-7.0.1/PREVIEW_MOBILE.png`
- `dist/optimusos-local-20260630/PREVIEW_DESKTOP.png`
- `dist/optimusos-local-20260630/PREVIEW_MOBILE.png`

The current `app/static/*` files matched the archived static files before the repair work. No separate React app, Vite source tree, component directory, customer screen, vehicle screen, work-order screen, approval queue screen, or alternate original Optimus UI was found in the local repository or archived build directories.

## Generated Or Regression Files Identified

The static app itself was not newly overwritten during this Ubuntu deployment phase. The deployment regression was in the generated nginx frontend configuration:

- `ops/nginx/default.conf`

Before repair, `/static/app.js`, `/static/styles.css`, and image/manifest assets were being served as `index.html`. Browser JavaScript and CSS could not load correctly from the frontend container.

Files added for audit/verification:

- `scripts/ui_connection_audit_playwright.js`
- `docs/screenshots/original-reference-desktop.png`
- `docs/screenshots/original-reference-mobile.png`
- `docs/screenshots/repaired-dashboard.png`
- `docs/screenshots/optimus-chat.png`
- `docs/screenshots/estimates.png`
- `docs/screenshots/system-status.png`
- `docs/UI_CONNECTION_AUDIT.md`

## Current Interface Being Served

- URL: `http://127.0.0.1:5173`
- Frontend service: nginx container
- Served entry point: `app/static/index.html`
- JavaScript: `app/static/app.js`
- CSS: `app/static/styles.css`
- Logo: `app/static/logo-mark.svg`

Verified static asset headers after repair:

- `/static/app.js`: `200`, `Content-Type: application/javascript`
- `/static/styles.css`: `200`, `Content-Type: text/css`
- `/static/logo-mark.svg`: `200`, `Content-Type: image/svg+xml`

## FastAPI Application Being Served

- Active ASGI app: `app.main:app`
- Backend command: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers`
- Backend URL: `http://127.0.0.1:8000`

## Docker Services And Ports

Last verified running stack before sudo authentication expired:

- `optimus-server-frontend-1`: `127.0.0.1:5173 -> 80`
- `optimus-server-backend-1`: `127.0.0.1:8000 -> 8000`
- `optimus-server-postgres-1`: internal `5432`, not publicly published
- `optimus-server-redis-1`: internal `6379`, not publicly published
- `optimus-server-worker-1`: internal worker process

Fresh Docker `ps` and log inspection was blocked by sudo authentication after the browser/API checks. HTTP readiness confirmed backend, PostgreSQL, and Redis connectivity after the rebuild.

## FastAPI Route Map

Implemented routes:

- `GET /`
- `GET /health`
- `GET /ready`
- `GET /docs`
- `GET /openapi.json`
- `POST /api/location/resolve`
- `POST /api/chat`
- `POST /api/estimate`

Missing requested routes:

- Authentication endpoint: `/api/auth/login` returns `404`
- Authentication status endpoint: `/api/auth/status` returns `404`
- Customer endpoints: `/api/customers` returns `404`
- Vehicle endpoints: `/api/vehicles` returns `404`
- Work-order endpoints: `/api/work-orders` returns `404`
- Approval endpoints: `/api/approvals` returns `404`

Protected routes require `Authorization: Bearer <token>`:

- `POST /api/location/resolve`
- `POST /api/chat`
- `POST /api/estimate`

Unauthenticated verification results:

- `POST /api/location/resolve`: `401`
- `POST /api/chat`: `401`
- `POST /api/estimate`: `401`

## Endpoint Verification

Direct backend checks:

- `GET /health`: `200`, body status `ok`
- `GET /ready`: `200`, body status `ready`, dependencies `postgres: true`, `redis: true`
- `GET /docs`: `200`
- `GET /openapi.json`: `200`
- `POST /api/chat` with synthetic data and no token: `401`
- `POST /api/estimate` with synthetic data and no token: `401`
- `POST /api/location/resolve` with synthetic data and no token: `401`
- `/api/auth/login`: `404`
- `/api/auth/status`: `404`
- `/api/customers`: `404`
- `/api/vehicles`: `404`
- `/api/work-orders`: `404`
- `/api/approvals`: `404`

## Frontend Routes And Views

This app is a static single-page interface with four internal views:

- Dashboard: `data-view="dashboard"`
- Talk to Optimus: `data-view="chat"`
- Job estimator: `data-view="estimate"`
- System bay: `data-view="system"`

No frontend routes or views were found for:

- Customers
- Vehicles
- Work orders
- Approval queue

## Button-To-Action Mapping

| UI control | Expected action | Frontend handler | API request | Auth | Success behavior | Error behavior |
| --- | --- | --- | --- | --- | --- | --- |
| Command deck nav | Show dashboard | `showView("dashboard")` | None | No | Dashboard visible | None |
| Talk to Optimus nav | Show chat | `showView("chat")` | None | No | Chat visible | None |
| Job estimator nav | Show estimate | `showView("estimate")` | None | No | Estimate visible | None |
| System bay nav | Show system | `showView("system")` | None | No | System visible | None |
| Mobile menu toggle | Toggle nav | mobile menu listener | None | No | Nav opens/closes | None |
| Hero Talk to Optimus | Show chat | `showView("chat")` | None | No | Chat visible | None |
| Hero Build an estimate | Show estimate | `showView("estimate")` | None | No | Estimate visible | None |
| Capability prompt buttons | Start prompt or navigate | quick prompt listeners | None until submit | No | Message/target view prepared | None |
| Dashboard Run command | Send chat command | `runChat()` | `POST /api/chat` | Yes | Assistant answer displayed | Visible `Command failed` message |
| Chat Send | Send chat message | `runChat()` | `POST /api/chat` | Yes | Assistant answer displayed | Visible `Command failed` message |
| Decode VIN prompt | Fill chat prompt | quick prompt listener | None until submit | No | Chat prompt filled | None |
| Diagnose fault prompt | Fill chat prompt | quick prompt listener | None until submit | No | Chat prompt filled | None |
| Find parts prompt | Fill chat prompt | quick prompt listener | None until submit | No | Chat prompt filled | None |
| Price a job prompt | Navigate estimate | quick prompt listener | None until submit | No | Estimate visible | None |
| Research and estimate | Submit estimate | `runEstimate()` | `POST /api/estimate` | Yes | Estimate cards rendered | Visible error card |
| Copy estimate | Copy rendered estimate | result action listener | Clipboard only | No | Toast on copy | Toast/error if unavailable |
| Print estimate | Print rendered estimate | result action listener | Browser print | No | Print dialog | Browser-managed |
| Start another | Reset estimate form | result action listener | None | No | Form reset/result cleared | None |
| Show/Hide token | Toggle token field type | token toggle listener | None | No | Token field type changes | None |
| Use current location | Browser geolocation | geolocation listener | None | Browser permission | Coordinates stored | Visible toast/error |
| Run check | Check backend health | `refreshHealth()` | `GET /health` | No | System status online | Visible offline/degraded state |

No silent placeholder buttons were found in the current static UI. Requested module buttons for Customers, Vehicles, Work Orders, and Approval Queue are absent rather than silently nonfunctional.

## API Client And Communication

The frontend now uses a centralized API helper in `app/static/app.js`:

- `API_BASE_URL` defaults to `http://localhost:8000`
- Runtime override is available through `window.VITE_API_BASE_URL`
- Requests go through `apiFetch()`
- Auth headers are centralized in `authHeaders()`
- API failures are parsed and rendered visibly; they are not hidden
- No frontend secret variables were added

## CORS And Security Headers

FastAPI CORS allows the actual local frontend origins:

- `http://127.0.0.1:5173`
- `http://localhost:5173`

Allowed methods:

- `GET`
- `POST`
- `OPTIONS`

Allowed headers:

- `Authorization`
- `Content-Type`

Verified preflight:

- `OPTIONS /api/chat` from origin `http://127.0.0.1:5173`: `200`
- Response includes `access-control-allow-origin: http://127.0.0.1:5173`

Content Security Policy was updated to allow browser connections to:

- `http://127.0.0.1:8000`
- `http://localhost:8000`

## Browser Console And Network

Playwright real-browser result:

```json
{
  "baseUrl": "http://127.0.0.1:5173",
  "consoleMessages": [
    "error: Failed to load resource: the server responded with a status of 401 (Unauthorized)",
    "error: Failed to load resource: the server responded with a status of 401 (Unauthorized)"
  ],
  "failedRequests": [],
  "network": [
    "200 GET http://localhost:8000/health",
    "401 POST http://localhost:8000/api/chat",
    "401 POST http://localhost:8000/api/estimate",
    "200 GET http://localhost:8000/health"
  ]
}
```

Interpretation:

- No blocking JavaScript syntax errors were observed.
- No failed browser network requests were observed.
- The `401` responses are expected because protected API calls were tested without a bearer token.
- The UI renders visible error states for those `401` responses.

## Test Results

- Frontend JavaScript syntax: `node --check app/static/app.js` passed.
- Playwright workflow: `node scripts/ui_connection_audit_playwright.js` passed.
- Backend pytest suite: not run. `pytest` is not installed globally or in `.venv`; attempting `.venv/bin/python -m pip install -e '.[dev]'` failed because `.venv` uses Python `3.14.4` and the project declares `requires-python = ">=3.12,<3.14"`.
- Compatible Python found locally: none. `python3` and `.venv/bin/python` both report `Python 3.14.4`.

## Screenshots

Captured screenshots:

- Original reference desktop: `docs/screenshots/original-reference-desktop.png`
- Original reference mobile: `docs/screenshots/original-reference-mobile.png`
- Repaired dashboard: `docs/screenshots/repaired-dashboard.png`
- Optimus chat: `docs/screenshots/optimus-chat.png`
- Estimates: `docs/screenshots/estimates.png`
- System status: `docs/screenshots/system-status.png`

Screenshots not captured because no source view or route exists locally:

- Customers
- Vehicles
- Work orders
- Approval queue

## Visual And Functional Differences

The repaired interface uses the only local Optimus visual source found: the packaged Optimus 7.0.1 static command center. Because no separate original UI source, React app, or module screens were found, the audit cannot prove or restore any different customer/vehicle/work-order/approval interface from local files.

The main functional difference before repair was not the HTML design; it was that the frontend server was returning HTML for JavaScript, CSS, and image assets. That made the local website behave like a disconnected shell.

## Root Causes

1. `ops/nginx/default.conf` served `index.html` for `/static/*` asset URLs instead of the actual files mounted from `app/static`.
2. The frontend used relative API calls through the frontend origin. This hid the intended backend origin and made browser/API behavior dependent on the nginx proxy path.
3. FastAPI CORS did not allow the actual frontend origin before repair.
4. Requested Customers, Vehicles, Work Orders, Approval Queue, and Auth API modules are not present in the local source.
5. No separate original Optimus UI source exists locally beyond the current packaged static command center and preview images.

## Repair Summary

Completed:

- Preserved a Git checkpoint before repair changes.
- Restored correct nginx static asset serving.
- Centralized frontend API calls through `apiFetch()`.
- Defaulted local API base URL to `http://localhost:8000`.
- Added FastAPI CORS for `http://127.0.0.1:5173` and `http://localhost:5173`.
- Updated backend CSP connect source for the local API.
- Verified `/health`, `/ready`, `/docs`, `/openapi.json`, protected API behavior, missing route behavior, CORS preflight, static asset MIME types, and browser workflows.
- Captured available screenshots.

Remaining:

- Provide original source or screenshots if the intended original Optimus interface differs from the packaged static command center found here.
- Implement or supply source for Customers, Vehicles, Work Orders, Approval Queue, and Auth modules if those are required.
- Enter sudo password when prompted if fresh Docker logs/status are required after this audit.
