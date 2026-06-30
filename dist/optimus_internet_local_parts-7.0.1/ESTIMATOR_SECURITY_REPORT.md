# Job Estimator Security and Reliability Review

Build reviewed: Optimus 7.0.1

## Findings corrected

### 1. Entire estimate failed when either research call failed — High reliability impact

The previous estimator performed separate labor and parts OpenAI calls. A timeout, schema rejection, model refusal, or malformed parts result in either call aborted the complete estimate.

**Correction:** one combined research call with a compatibility fallback and model fallback.

### 2. API transport schema was unnecessarily fragile — High reliability impact

The old parts schema sent strict URL and numeric constraints directly to the model-facing structured-output schema. The parts schema was substantially larger and more failure-prone than the labor schema.

**Correction:** the model-facing transport schema now uses simple primitive types. URL, range, length, enum, and quantity enforcement happens locally before any result is displayed or priced.

### 3. Generic upstream error concealed the failing stage — Medium operational impact

The browser only reported that the estimator failed.

**Correction:** safe errors now identify authentication, permissions, quota, rate limiting, model access, timeout, connection, schema, fallback parsing, and unexpected pipeline failures. Each failure includes a trace ID without exposing secrets.

### 4. Low-confidence pricing could outrank stronger evidence — Medium quote-integrity impact

The previous selector prioritized stock status and price before evidence confidence.

**Correction:** confidence is now the first selection factor. Low-confidence selected prices produce an explicit verify-before-quoting warning.

### 5. Chat and estimate requests shared one rate-limit bucket — Low reliability impact

Heavy chat use from the same browser could consume the estimator request allowance.

**Correction:** rate limits are keyed by endpoint and client.

## Controls verified

- Loopback-only Windows bind: `127.0.0.1`.
- Bearer access-token support.
- Strict Content Security Policy without inline-script exceptions.
- HTML escaping for estimator fields and errors.
- HTTPS-only source links.
- Loopback/private/local link rejection.
- Outbound NHTSA and Census requests restricted by host allowlist.
- HTTP proxy inheritance disabled for restricted service requests.
- No purchasing, reservations, form submission, or store contact in the estimator path.
- API keys are not returned to the browser or written to estimator logs.

## Validation performed

- Unit and API tests for structured research, JSON fallback, URL rejection, prompt-injection isolation, pricing selection, safe errors, math, VIN, location, rate limiting, UI, and Windows distribution.
- Strict type checking and linting.
- JavaScript syntax validation.
- OpenAI SDK schema inspection confirming the estimator transport schema contains no URI format, exclusive-minimum, maximum-length, or maximum-items keywords.
- 50,000 randomized regression checks covering estimate math, routing, authority decisions, part selection, and blocked URLs.
- Fresh package build and clean installation checks.
- Bandit scan of production Python sources with zero findings.

## Remaining operational dependency

A true live parts-and-labor result depends on the owner’s OpenAI API project, model permissions, billing/quota, internet connection, and what retailers expose publicly. `DIAGNOSE_ESTIMATOR.bat` tests that full live path without displaying the API key.

## Audit limitation

The external dependency-vulnerability database could not be queried from the build container because DNS resolution to the service was unavailable. `pip check` passed and production-source static scanning completed, but this is not claimed as a completed dependency-CVE audit.
