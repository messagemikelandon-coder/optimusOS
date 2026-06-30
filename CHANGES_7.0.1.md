# Optimus 7.0.1 — Estimator Reliability and Security Patch

## Fixed

- Replaced two sequential OpenAI estimator calls with one combined labor-and-parts research request.
- Added a JSON compatibility fallback when strict structured-output parsing is rejected.
- Added automatic fallback from the configured estimator model to `gpt-4.1-mini` when the primary model is unavailable.
- Removed `HttpUrl`, range, and collection-size constraints from the API transport schema; strict validation now runs locally after the response is received.
- Added safe error codes, stages, and request IDs instead of the generic “Job estimator failed” message.
- Added `DIAGNOSE_ESTIMATOR.bat` for a complete live end-to-end estimator check.
- Increased the default OpenAI request timeout from 120 to 180 seconds.
- Separated chat and estimate rate-limit buckets so normal chat use cannot consume the estimator’s allowance.

## Security hardening

- Keeps user job text and webpage content explicitly classified as untrusted data.
- Requires web search during estimator research.
- Validates all labor values, quantities, prices, availability labels, URLs, and strings locally.
- Drops non-HTTPS, loopback, private-network, malformed, and disallowed retailer links.
- Never exposes API keys, prompts, or raw upstream exception bodies in browser error messages.
- Prioritizes higher-confidence price evidence before stock status and price.
- Adds a visible warning when low-confidence pricing is used in a total.
- Continues to bind the Windows server to `127.0.0.1` only.

## Compatibility

- Python 3.12 and 3.13.
- Existing Optimus 7.0 `.env` files remain valid.
- New optional estimator settings are automatically added by `WINDOWS_SETUP.bat` when absent.
