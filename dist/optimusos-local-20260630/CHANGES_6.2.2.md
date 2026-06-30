# Optimus 6.2.2

## OpenAI authentication repair

- Makes the project `.env` file authoritative over stale Windows environment variables.
- Adds `RESET_OPENAI_KEY.bat` for hidden-input key replacement and immediate testing.
- Adds `DIAGNOSE_OPENAI.bat` to show masked key fingerprints without revealing the secret.
- Separates HTTP 401 invalid credentials from billing/quota, permissions, connectivity, and model-access errors.
- Uses a no-token model-list request for the first authentication check.
- Updates `CHECK_OPTIMUS.bat` to show which key Optimus is actually sending.
