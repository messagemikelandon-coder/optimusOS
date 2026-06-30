# Optimus 7.0.1 Windows setup

## First installation

1. Extract the package to a normal folder such as `C:\Optimus-7`.
2. Do not run it inside the ZIP preview.
3. Double-click `WINDOWS_SETUP.bat`.
4. Enter the API key from the OpenAI API platform when prompted.
5. Double-click `local.bat`.

The installer:

- Finds Python 3.12 or 3.13.
- Creates `.venv` in the Optimus folder.
- Installs the application and development checks.
- Creates `.env` when needed.
- Stores the OpenAI key in `.env`.
- Generates a strong local access token.
- Applies owner-full-control defaults.
- Validates the runtime and tests OpenAI authentication when configured.

## Starting Optimus

Double-click `local.bat` or `RUN_OPTIMUS_LOCAL.bat`.

The launcher:

- Validates `.env`.
- Binds the server to `127.0.0.1:8000` only.
- Waits for `/health`.
- Opens the Landon Motor Works command center.
- Supplies the access token through a URL fragment.
- Removes the fragment immediately after the browser stores the token in session memory.

The token is not sent in the page request or written to the server access log.

## Upgrade

Use a new folder and copy the old `.env` into it before running setup.

- From 7.0.0: see `UPGRADE_FROM_7.0.0.md`.
- From 6.2.2: see `UPGRADE_FROM_6.2.2.md`.

## Verification

Double-click `CHECK_OPTIMUS.bat` to run:

- Runtime configuration validation
- OpenAI authentication and model check
- Automated Python tests

## Job-estimator diagnostic

Double-click `DIAGNOSE_ESTIMATOR.bat` after `CHECK_OPTIMUS.bat`. It performs one live estimate request and reports a safe error code, failing stage, and trace ID. The test uses API credits.

## Replacing an API key

Double-click `RESET_OPENAI_KEY.bat`. It updates `.env` and reports a masked fingerprint without displaying the full key.

## Common issues

### Invalid API key

Run `DIAGNOSE_OPENAI.bat`. Optimus 7.0 inherits the 6.2.2 correction that gives `.env` priority over a stale Windows `OPENAI_API_KEY` variable.

### API key accepted but requests fail

The diagnostic separates authentication from billing/quota, project permission, model access, and network failures.

### Port 8000 is already in use

Close older Optimus windows. If another program owns the port, update both URL occurrences and the Uvicorn port in `local.bat`.

### Python is missing

Install 64-bit Python 3.12 and enable:

- Add Python to PATH
- Install the Python launcher
