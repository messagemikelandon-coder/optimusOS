# Optimus 7.0.1 Estimator Validation Report

Validation date: June 25, 2026

## Failure analysis

The VIN route and estimator route did not share the same risk profile. VIN decoding used one restricted NHTSA request. The estimator used two sequential OpenAI web-research calls, and either labor or parts failure aborted the complete estimate. The parts call also used a larger, stricter model-facing schema and the browser discarded the upstream stage behind one generic failure message.

## Corrections validated

- Labor and parts now use one combined research request.
- A structured-output failure can fall back to a JSON compatibility request.
- A configured primary model can fall back to `gpt-4.1-mini` when the primary model is unavailable.
- Model-facing fields use a simple transport schema; strict price, URL, quantity, range, enum, and length checks run locally.
- Every estimator failure returns a safe code, stage, and trace ID.
- Chat and estimator rate limits use separate endpoint buckets.
- Higher-confidence price evidence outranks low-confidence stock claims.
- Low-confidence selected prices trigger a visible verify-before-quoting warning.
- Unsafe, local, private, malformed, and non-HTTPS links are removed before display.

## Automated results

- Python unit/API/distribution tests: **51 passed**.
- Randomized regression checks: **50,000 passed**.
  - 6,000 estimate-math checks
  - 7,500 conversation-routing checks
  - 12,500 authority-decision checks
  - 20,000 confidence-aware part-selection checks
  - 4,000 blocked-URL security checks
- Ruff linting: **passed**.
- Strict mypy checking: **passed across 41 source files**.
- Python compilation: **passed**.
- JavaScript syntax validation: **passed**.
- Bandit production-source scan (`app` and `integration`): **0 findings**.
- OpenAI transport-schema inspection: **passed**.
  - No URI `format`
  - No `exclusiveMinimum`
  - No `maxLength`
  - No `maxItems`
- Source distribution build: **passed**.
- Wheel build: **passed**.
- Clean wheel installation: **passed**.
- `pip check`: **no broken requirements**.
- Clean-install `/health`: **HTTP 200**, version **7.0.1**.
- Clean-install command-center page: **HTTP 200**.

## Security controls verified

- Windows launch binds to `127.0.0.1`.
- Bearer access-token support remains enabled.
- Content Security Policy remains strict.
- Estimator error text is escaped and does not expose the API key, prompt, or raw upstream body.
- Research input and web content are treated as untrusted data.
- The estimator cannot purchase, reserve, submit forms, or contact stores.
- NHTSA and Census HTTP clients remain restricted to allowed hosts with environment proxy inheritance disabled.
- Retail research URLs are accepted only after HTTPS and public-network validation.

## Environment and limits

- Declared runtime: Python 3.12–3.13.
- Validation runtime: Python 3.13.5.
- No user OpenAI API key was available, so a billable live labor-and-parts request was not executed in this workspace. Deterministic fake-client tests cover structured output, fallback JSON, model fallback, upstream error mapping, unsafe links, and prompt-injection input.
- `DIAGNOSE_ESTIMATOR.bat` is included to run the owner’s complete live path and report the exact safe failure stage.
- A dependency-vulnerability database query could not complete because the build container could not resolve the external vulnerability service. Production source scanning and dependency integrity checks did complete, but this limitation is not represented as a successful vulnerability-database audit.
- Native Windows batch execution was not available. Batch/PowerShell contents, required files, CRLF formatting, and the Python commands they invoke were validated.
