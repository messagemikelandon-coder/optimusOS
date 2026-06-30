# Optimus 7.0.0 — Landon Motor Works Official Interface

## Integrated foundation

- Preserves the Optimus 6.2.2 owner-control, authentication-repair, direct-chat, agent-routing, web-research, VIN, location, parts, labor, and estimate code.
- Corrects all visible package and API version strings to `7.0.0`.
- Keeps `.env` authoritative over stale inherited Windows API-key variables.
- Keeps the server bound to `127.0.0.1` in the Windows launcher.

## Official mechanic interface

- Replaced the prototype page with a responsive Landon Motor Works command center.
- Added an original LMW shield logo and installable web-app manifest.
- Added a CSS-rendered three-dimensional brake rotor, caliper, diagnostic tablet, wrench, fasteners, shop grid, steel panels, and mechanic-themed ambient background.
- Added desktop sidebar navigation and mobile bottom navigation.
- Added separate Command Deck, Optimus Chat, Job Estimator, and System Bay views.
- Added live server, web-search, autonomy, and delegation indicators.
- Added safe rich-text rendering for Optimus responses and linked research sources.
- Added copy and print actions for completed estimates.
- Added persistent non-secret location and business-pricing preferences.
- Added reduced-motion support, print layout, keyboard submission, mobile responsiveness, and strict CSP compatibility.

## Windows experience

- `local.bat` opens the new command center and securely supplies the local access token through a URL fragment.
- The fragment is not sent to the server, is stored only in browser session storage, and is removed immediately from the address bar.
- The token is still copied to the clipboard as a recovery path.
- Updated setup titles and instructions for Landon Motor Works Optimus 7.0.

## Validation

- 44 Python tests passed.
- Ruff linting passed.
- Strict mypy checking passed for 19 source files.
- JavaScript syntax validation passed.
- HTML duplicate-ID and required-control validation passed.
- 26,000 regression checks passed.
- Desktop and mobile visual render checks passed without horizontal overflow.
