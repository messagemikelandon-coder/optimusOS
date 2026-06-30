from __future__ import annotations

from app.config import Settings
from app.openai_key_info import read_project_key, validate_key_text


def main() -> None:
    key_info = read_project_key()
    problems = validate_key_text(key_info.value)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        raise SystemExit(1)

    print(f"Key source: {key_info.source}")
    print(f"Key fingerprint: {key_info.fingerprint}")
    print(f"Masked key: {key_info.masked} (length {len(key_info.value)})")

    # Pass the project key explicitly. This prevents any stale Windows-level
    # OPENAI_API_KEY from overriding the key that the owner saved in .env.
    settings = Settings(openai_api_key=key_info.value)
    try:
        from openai import (
            APIConnectionError,
            APIStatusError,
            AuthenticationError,
            NotFoundError,
            OpenAI,
            PermissionDeniedError,
            RateLimitError,
        )
    except ImportError as exc:
        raise SystemExit("Install dependencies first: pip install -e .") from exc

    client = OpenAI(
        api_key=key_info.value,
        timeout=settings.openai_timeout_seconds,
        max_retries=0,
    )

    try:
        client.models.list()
    except AuthenticationError as exc:
        request_id = getattr(exc, "request_id", None)
        print("RESULT: OpenAI rejected the credential with HTTP 401.")
        print("The key sent by this check is the masked/fingerprinted key shown above.")
        if request_id:
            print(f"OpenAI request ID: {request_id}")
        raise SystemExit(2) from exc
    except PermissionDeniedError as exc:
        print("RESULT: The key authenticated, but its project permissions denied the request.")
        raise SystemExit(3) from exc
    except RateLimitError as exc:
        print("RESULT: The key authenticated, but the API account has a quota/billing limit.")
        raise SystemExit(4) from exc
    except APIConnectionError as exc:
        print("RESULT: Could not reach api.openai.com. Check internet, VPN, proxy, or firewall.")
        raise SystemExit(5) from exc
    except APIStatusError as exc:
        print(f"RESULT: OpenAI returned HTTP {exc.status_code} during authentication test.")
        raise SystemExit(6) from exc

    print("Authentication: accepted")

    try:
        response = client.responses.create(
            model=settings.openai_model,
            input="Reply with exactly: Optimus API connection OK",
            max_output_tokens=16,
        )
    except NotFoundError as exc:
        print(
            f"RESULT: The key is valid, but model '{settings.openai_model}' is unavailable "
            "to this project. Change OPENAI_MODEL in .env."
        )
        raise SystemExit(7) from exc
    except PermissionDeniedError as exc:
        print(
            f"RESULT: The key is valid, but this project lacks permission for "
            f"model '{settings.openai_model}' or the Responses API."
        )
        raise SystemExit(8) from exc
    except RateLimitError as exc:
        print("RESULT: The key is valid, but API billing, credits, or quota blocked the test.")
        raise SystemExit(9) from exc
    except AuthenticationError as exc:
        print("RESULT: Authentication changed between the two checks; rerun the test.")
        raise SystemExit(10) from exc
    except APIConnectionError as exc:
        print("RESULT: Authentication passed, but the model request lost network access.")
        raise SystemExit(11) from exc
    except APIStatusError as exc:
        print(f"RESULT: Model request failed with HTTP {exc.status_code}.")
        raise SystemExit(12) from exc

    print(response.output_text.strip())


if __name__ == "__main__":
    main()
