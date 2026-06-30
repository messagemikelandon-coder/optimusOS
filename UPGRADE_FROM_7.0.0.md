# Upgrade Optimus 7.0 to 7.0.1

1. Stop Optimus with `Ctrl+C`.
2. Keep a backup copy of the old `.env` file.
3. Extract the 7.0.1 ZIP to a new folder such as `C:\Optimus-7.0.1`.
4. Copy only the old `.env` file into the new folder.
5. Do not copy the old `.venv`, `app`, `dist`, or cache folders.
6. Run `WINDOWS_SETUP.bat`.
7. Run `CHECK_OPTIMUS.bat`.
8. Run `DIAGNOSE_ESTIMATOR.bat`.
9. Start the server with `local.bat`.

The existing API key, access token, labor rate, tax, location preferences, and autonomy settings remain compatible.
