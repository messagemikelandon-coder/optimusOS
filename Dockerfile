FROM python:3.12-slim

# Set at build time (docker-compose.yml passes GIT_COMMIT=$(git rev-parse
# HEAD); defaults to "unknown" for a plain `docker build` without it) so
# /health and the System UI can show exactly which commit is running.
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=$GIT_COMMIT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY integration ./integration
COPY scripts ./scripts
COPY CHECK_OPTIMUS.bat DIAGNOSE_ESTIMATOR.bat DIAGNOSE_OPENAI.bat RESET_OPENAI_KEY.bat ./
COPY RUN_OPTIMUS_LOCAL.bat WINDOWS_SETUP.bat WINDOWS_SETUP.md local.bat ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
