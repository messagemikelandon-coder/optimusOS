# Optimus 7.0.1 — Landon Motor Works Command Center

A Python 3.12–3.13 local service combining the complete Optimus 6.2.2 owner-control backend with a production-style mechanic command center.

## Core capabilities

- Direct owner-to-Optimus chat
- Selective and silent specialist consultation
- OpenAI Responses API web research with cited source links
- Current parts prices and local availability research
- Official retailer/product links when pricing is hidden
- Browser location, ZIP, or city/state store research
- NHTSA VIN decoding and Census coordinate resolution
- Book-time and practical mobile-mechanic labor analysis
- Itemized Landon Motor Works estimates
- Owner-full-control routing for reversible work
- Source-aware OpenAI key diagnostics and replacement
- Resilient one-call job research with structured and JSON compatibility modes
- Stage-specific estimator diagnostics with safe trace IDs

## Official interface

The 7.0 interface includes:

- Landon Motor Works branding and original shield mark
- Three-dimensional mechanic scene rendered locally with HTML/CSS
- Command Deck, Optimus Chat, Job Estimator, and System Bay
- Desktop and mobile navigation
- Live health and autonomy status
- Safe formatted answers and citation links
- Copyable and printable estimates
- Persistent non-secret pricing and location preferences
- Responsive layout and reduced-motion support

Preview files are included as `PREVIEW_DESKTOP.png` and `PREVIEW_MOBILE.png`.

## Windows installation

1. Extract the ZIP to a normal folder such as `C:\Optimus-7`.
2. Double-click `WINDOWS_SETUP.bat` once.
3. Enter the OpenAI API key when prompted.
4. Double-click `local.bat` whenever you want to start Optimus.
5. Run `CHECK_OPTIMUS.bat` to verify the key, configuration, and tests.
6. Run `DIAGNOSE_ESTIMATOR.bat` to perform one live labor-and-parts test when troubleshooting estimates.

`local.bat` binds only to `127.0.0.1` and opens the sign-in page at `http://127.0.0.1:8000/login`.

## Upgrades

- From Optimus 7.0.0: read `UPGRADE_FROM_7.0.0.md`.
- From Optimus 6.2.2: read `UPGRADE_FROM_6.2.2.md`.

The safest process is a clean new folder with only the old `.env` copied over.

## Configuration

Recommended `.env` values:

```env
BUSINESS_NAME=Landon Motor Works
BUSINESS_TAGLINE=Mobile Mechanic Intelligence
AUTONOMY_MODE=owner_full_control
DIRECT_OWNER_CHAT_DEFAULT=true
AGENT_DELEGATION_ENABLED=true
MAX_AGENT_CONSULTATIONS=2
ALLOW_PUBLIC_HTTPS_PARTS_LINKS=true
LABOR_RATE=100.00
```

The OpenAI API key is separate from the bootstrap owner credentials. The owner password is hashed into the database, and browser sessions use an HttpOnly cookie-backed server session.

## Manual run

```bash
python3.12 -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

Create the first owner account once after migrations:

```bash
python -m app.bootstrap_owner
```

## API endpoints

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/chat`
- `POST /api/estimate`
- `POST /api/location/resolve`
- `GET /health`

## Validation commands

```bash
python -m pytest -q
python scripts/regression_backtest.py
python -m ruff check app integration tests scripts
python -m mypy app integration
node --check app/static/app.js
python scripts/diagnose_estimator.py  # live, billable diagnostic
```

## Accuracy behavior

- Confirmed local stock requires explicit current evidence tied to a named store.
- Hidden prices remain unknown and are excluded from estimate totals.
- Official product/search links remain available when a retailer hides price.
- Private-network and non-HTTPS research links are blocked.
- Optimus separates unavailable information from an unavailable capability.

## Estimator recovery behavior

- Labor and parts research are requested together to reduce upstream failure points.
- The primary structured-output path falls back to a JSON compatibility path when necessary.
- Model output is treated as untrusted and revalidated locally before prices, links, labor hours, or availability enter a quote.
- Estimator errors identify the failing stage, a safe error code, and a trace ID without exposing the API key or raw upstream response.
- A missing or rejected part result no longer suppresses otherwise usable labor research.

See `ESTIMATOR_SECURITY_REPORT.md` and `VALIDATION.md`.
# optimusOS
