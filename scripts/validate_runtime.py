from __future__ import annotations

from app.config import Settings

_PLACEHOLDERS = {
    "replace_me",
    "your_actual_openai_api_key",
    "replace_with_a_long_random_token",
    "replace_with_a_long_owner_password",
}


def is_missing_or_placeholder(value: str) -> bool:
    normalized = value.strip()
    return not normalized or normalized.lower() in _PLACEHOLDERS


def main() -> None:
    settings = Settings()
    errors: list[str] = []

    if is_missing_or_placeholder(settings.openai_api_key):
        errors.append("OPENAI_API_KEY is missing or still contains the example value.")
    if not settings.optimus_owner_username:
        errors.append("OPTIMUS_OWNER_USERNAME is missing.")
    if is_missing_or_placeholder(settings.optimus_owner_password):
        errors.append("OPTIMUS_OWNER_PASSWORD is missing or still contains the example value.")
    elif len(settings.optimus_owner_password) < 12:
        errors.append("OPTIMUS_OWNER_PASSWORD must be at least 12 characters.")

    if errors:
        print("Optimus configuration is not ready:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    print("Optimus runtime configuration: ready")
    print(f"Chat model: {settings.openai_model}")
    print(f"Estimator model: {settings.estimator_model}")
    print(f"Estimator fallback: {settings.openai_fallback_model or 'disabled'}")
    print(f"Labor rate: ${settings.labor_rate:.2f}/hr")
    print(f"Autonomy mode: {settings.autonomy_mode}")
    print(f"Direct owner chat: {settings.direct_owner_chat_default}")


if __name__ == "__main__":
    main()
