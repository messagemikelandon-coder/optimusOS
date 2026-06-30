# Upgrade from Optimus 6.2.2

Optimus 7.0 contains the complete 6.2.2 backend and replaces its prototype interface.

## Recommended clean upgrade

1. Stop the old Optimus window with `Ctrl+C`.
2. Extract this package to a new folder such as `C:\Optimus-7`.
3. Copy only the old `.env` file into the new folder.
4. Do not copy the old `.venv`, `dist`, cache folders, or static UI files.
5. Double-click `WINDOWS_SETUP.bat`.
6. Double-click `local.bat`.
7. Run `CHECK_OPTIMUS.bat` once after installation.

This method preserves the OpenAI key, local access token, pricing defaults, autonomy mode, and other environment settings without carrying old dependencies or interface files forward.

## In-place code merge

For an existing Git repository, compare and merge:

- `app/static/` — complete official UI replacement
- `app/main.py` — official title/version and health metadata
- `app/config.py` — Landon Motor Works identity settings
- `app/__init__.py` — version
- `integration/optimus_adapter.py` — adapter version
- `local.bat` and `scripts/open_when_ready.ps1` — automatic local token handoff
- `pyproject.toml` and `MANIFEST.in` — package version/assets
- `tests/test_official_ui.py` — interface and launch security tests

Do not replace the new 7.0 files with the older 6.2.2 `app/static` directory after upgrading.
