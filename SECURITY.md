# Security

Please report security problems privately through
[GitHub's private vulnerability reporting](https://github.com/tomoliveri/trailhead/security/advisories/new), not as a public issue.

Things worth knowing about how Trailhead handles data:

- Plans are stored under unguessable links; changing one needs a key held by the browser that created it.
- The Garmin relay (`/api/garmin/*`) passes credentials to Garmin and stores nothing. Tokens stay in the browser.
- Watches authenticate with an 8-character pairing code.
