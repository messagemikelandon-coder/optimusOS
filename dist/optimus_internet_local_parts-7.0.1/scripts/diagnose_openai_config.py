from __future__ import annotations

import os

from app.config import Settings
from app.openai_key_info import read_project_key, validate_key_text


def main() -> None:
    project_key = read_project_key()
    inherited_key = os.getenv("OPENAI_API_KEY", "").strip()
    effective = Settings().openai_api_key

    print("Optimus OpenAI configuration diagnostic")
    print(f"Project key source: {project_key.source}")
    if project_key.value:
        print(f"Project key: {project_key.masked}; {project_key.fingerprint}")
    else:
        print("Project key: missing")

    if inherited_key:
        inherited_info = type(project_key)(inherited_key, "Windows/process environment")
        print(f"Inherited Windows key: {inherited_info.masked}; {inherited_info.fingerprint}")
        if inherited_key != project_key.value:
            print("NOTICE: Windows contains a different old key. Optimus 7.0.1 ignores it.")
    else:
        print("Inherited Windows key: not set")

    effective_info = type(project_key)(effective, "effective Settings value")
    if effective:
        print(f"Effective Optimus key: {effective_info.masked}; {effective_info.fingerprint}")
    else:
        print("Effective Optimus key: missing")

    for problem in validate_key_text(effective):
        print(f"ERROR: {problem}")

    if effective and effective == project_key.value:
        print("Configuration precedence: correct (.env wins)")
    elif effective:
        print("ERROR: Optimus is not using the project .env key.")
        raise SystemExit(1)
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
