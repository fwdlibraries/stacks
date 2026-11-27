# Security

Stacks holds reading lists, library API keys and sign-in settings for libraries, and it runs inside their LMS. We take reports about its security seriously, and we're grateful for them.

## Supported versions

Stacks hasn't had a release yet. Security fixes go to the `main` branch. If you run Stacks, keep it up to date with `main`, and run `alembic upgrade head` after each update.

## Reporting a vulnerability

**Please don't open a public issue, pull request or discussion about a vulnerability.**

Report it privately through GitHub instead:

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**.

Please include:
- what an attacker could do, and what they'd need first (for example a staff account, an LMS launch, or nothing at all);
- steps to reproduce it, or a proof of concept;
- the commit or date of the code you tested.

Test only against a Stacks you run yourself. Don't test against an institution's Stacks, and don't access other people's data.

### What happens next

- We'll acknowledge your report within 5 working days.
- We'll tell you whether we can reproduce it, and roughly when we expect a fix.
- We'll publish a GitHub security advisory once a fix is on `main`. We'll credit you in it unless you'd rather we didn't.
- Please give us 90 days before you disclose the issue, or until the fix is published if that's sooner. If it's being exploited in the wild, tell us and we'll move faster.

## Scope

**In scope:** this repository: the backend, the frontend, the browser extension, and the Docker and nginx configuration in `deploy/`.

**Not in scope:**
- Problems in the services Stacks connects to, such as Alma, Primo, LibKey, Crossref, OpenAlex, LMS platforms or identity providers. Report those to their vendors.
- Settings a deployer chose against this guide, for example a default `SECRET_KEY`, or `OIDC_ALLOW_HTTP` left on in production.
- Denial of service through sheer volume, and social engineering.

## How Stacks protects data

This section is for people deciding whether to run Stacks, and for reviewers.

**Signing in**
- **Passwords** are hashed with bcrypt. After repeated failed attempts, sign-in to that account pauses for a while (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`).
- **Single sign-on** uses OpenID Connect with PKCE. Stacks refuses identity providers on plain http.
  - For Entra, it only accepts your own tenant's issuer, and checks the tenant ID in every token.
  - It can require multi-factor sign-in, checked through the `amr` claim.
- **LTI 1.3 launches** are checked against the platform's published keys (JWKS). Stacks then checks the issuer, audience, expiry, nonce, LTI version, message type and deployment.
- **Sign-in sessions** are kept on the server, so they can be revoked:
  - Access tokens last 15 minutes.
  - Each refresh token works once. If an old one is used again, it was copied, and the whole session ends.
  - Logout ends the session at once. People can sign out their other sessions, and administrators can sign someone out everywhere. Turning an account off does the same.
  - The access token is held in memory only. In its own tab, Stacks keeps the refresh token in an HttpOnly, Secure, SameSite=Strict cookie that page scripts can't read.
- **Browser extension tokens** have a limited scope: they can list reading lists and add citations, nothing else. Only their SHA-256 hash is stored, and each token is shown once, when it's created.

**Who sees what**
- Each organization's data is kept separate. A request belongs to the organization whose web address it came to, and `REQUIRE_KNOWN_HOST=true` refuses requests to unknown addresses.
- Roles can apply to the whole organization, a college, a department or a single course. Lists outside someone's scope return "not found", so the response doesn't reveal that they exist.

**Secrets**
- Library API keys (Alma, Primo, LibKey), single sign-on client secrets and each LMS registration's private signing key are encrypted in the database. The encryption key is `CREDENTIALS_KEY`, or one derived from `SECRET_KEY` if that's empty.
- The key is never sent back to the browser.

**Browser and LMS**
- Pages send a Content-Security-Policy that loads scripts, fonts and images, and makes network requests, only from Stacks itself. Fonts and other assets are bundled rather than loaded from CDNs. Even an organization's custom theme CSS can't send data elsewhere.
- Only the LMS addresses you list (`FRAME_ANCESTORS`, or each organization's LMS addresses) can show Stacks in a frame.

**Privacy**
- Students don't need an account to read a public list.
- Click statistics record which citation was clicked and when. They don't record who clicked, their IP address or their browser.

## Known limitations

We'd rather state these than have you find them:

- **Inside an LMS frame, the refresh token is readable by scripts on the page.** Browsers often block cookies in frames, so there it's kept in `sessionStorage`: that tab only, and gone when the tab closes. Three things limit the risk:
  - the Content-Security-Policy makes injecting script hard;
  - refresh tokens work once, so using a stolen one ends the session;
  - access tokens last 15 minutes.
- **CI doesn't scan dependencies or secrets yet.**
- **Nobody outside the project has audited Stacks.** It's pre-release software.

## Running Stacks securely

- **Secrets:** set a long random `SECRET_KEY`, and a separate `CREDENTIALS_KEY` (`python -m app.cli generate-credentials-key`). Keep a copy of `CREDENTIALS_KEY`: without it, stored API keys, client secrets and LMS signing keys can't be decrypted.
- **HTTPS:** serve Stacks only over HTTPS, and set `PUBLIC_BASE_URL` to its https address.
- **Debug settings:** keep `DEBUG=false`, `SQL_ECHO=false` (with it on, SQL logs include secrets) and `OIDC_ALLOW_HTTP=false`.
- **Hosting several organizations:** set `REQUIRE_KNOWN_HOST=true`.
- **Framing:** list only your own LMS addresses in `FRAME_ANCESTORS`, or in each organization's settings.
- **Network:** don't expose PostgreSQL or Redis to the internet. The Compose files keep them on the internal network.
- **Accounts:** give administrator roles sparingly. For library staff, prefer single sign-on with multi-factor sign-in.
