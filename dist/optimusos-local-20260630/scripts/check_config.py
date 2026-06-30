from __future__ import annotations

from app.config import Settings


def main() -> None:
    settings = Settings()
    key = settings.openai_api_key
    masked = "not configured" if not key else f"configured ({key[:7]}…{key[-4:]}, length {len(key)})"
    print(f"OPENAI_API_KEY: {masked}")
    print(f"OPENAI_MODEL: {settings.openai_model}")
    print(f"OPTIMUS_ACCESS_TOKEN: {'configured' if settings.optimus_access_token else 'not configured'}")
    print(f"Labor rate: ${settings.labor_rate:.2f}/hr")
    print(f"Autonomy mode: {settings.autonomy_mode}")
    print(f"Direct owner chat default: {settings.direct_owner_chat_default}")
    print(f"Agent delegation enabled: {settings.agent_delegation_enabled}")
    print(f"Public HTTPS parts links: {settings.allow_public_https_parts_links}")
    print(f"Retailer hosts: {len(settings.parts_retailer_hosts)}")


if __name__ == "__main__":
    main()
