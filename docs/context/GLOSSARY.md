# Glossary

Purpose: short, non-conflicting definitions of project terms.
Information owner: repository maintainers.
Read when: writing docs or user-facing copy that uses project-specific terms.
Update when: a term is redefined or a new canonical term is added.
Last verified date: 2026-07-01.
Relevant sources: `README.md`, `app/static/index.html`, `app/control.py`, `app/models.py`, `app/auth.py`, `app/orchestrator.py`.

## Terms

- Optimus: the owner-facing management agent.
- OptimusOS: the local Landon Motor Works software system in this repository.
- Landon Motor Works: the business served by OptimusOS.
- owner: the authenticated human operator who controls Optimus.
- approval: a required confirmation or authorization for a restricted action.
- protected flow: a workflow that requires an authenticated owner session.
- bootstrap owner: the first owner account created from environment-provided credentials.
- work order: a future business record for repair work.
- estimate: an itemized repair-cost projection.
- invoice: a future customer billing record.
- service request: a future intake or repair-request record.
- API gateway: the server-side path that exposes approved API behavior to the browser.
- session: the server-side authenticated login state tracked by a cookie and database row.
- frontend: the browser-delivered static UI in `app/static/`.
- backend: the FastAPI application in `app.main:app`.
- worker: the background process started by Compose for asynchronous work.
- generated distribution: files under `dist/` produced by packaging or release workflows.
