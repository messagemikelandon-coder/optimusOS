# Optimus 7.0.1 authority and security model

## Owner authority

`AUTONOMY_MODE=owner_full_control` is the default.

- Research, browsing, price lookup, inventory checks, estimates, calculations, VIN decoding, and location resolution run automatically.
- Reversible local work may run when requested by the owner or authorized by Optimus.
- An explicit owner instruction in the current request authorizes reversible external actions.
- Money movement, purchases, refunds, credential changes, permanent deletion, and privileged destructive actions require current-turn confirmation.
- Unknown actions are allowed when explicitly requested by the owner in owner-full-control mode; otherwise they request authorization.

This is a single-confirmation model. It prevents agents from inferring irreversible consent from old context without blocking normal work.

## Agent boundaries

- Optimus is the only owner-facing speaker.
- Agents provide silent advice and cannot authorize themselves.
- Agent-originated actions need Optimus authorization.
- Agents cannot recursively call other agents unless Optimus permits it.

## Internet and links

- General research uses the OpenAI Responses API `web_search` tool.
- Approximate location may be supplied for local results.
- Product links may use any public HTTPS host when `ALLOW_PUBLIC_HTTPS_PARTS_LINKS=true`.
- Non-HTTPS, loopback, private-network, and local-network URLs remain blocked to prevent server-side request forgery.
- Direct outbound HTTP remains limited to official NHTSA vPIC and U.S. Census services.

## Location privacy

- Browser geolocation requires permission.
- Coordinates are retained only in browser session storage and sent with requests that need local research.
- The included application contains no server-side location database, analytics, telemetry, or location-history storage.

## Inventory truthfulness

`confirmed_in_stock`, `limited`, and `out_of_stock` require explicit current source evidence for a named store. Otherwise status is `unknown`.

## API protection

- Set `OPTIMUS_OWNER_USERNAME` and `OPTIMUS_OWNER_PASSWORD` before bootstrapping the first owner account.
- Passwords are stored only as Argon2id hashes in `user_accounts`.
- Session tokens are issued to an HttpOnly cookie and only their SHA-256 hashes are stored in `auth_sessions`.
- The bootstrap command creates the first owner only when no owner exists; startup does not overwrite an existing owner password.
- Chat and estimate requests are rate-limited by client address.
- Use HTTPS for remote browser geolocation.
