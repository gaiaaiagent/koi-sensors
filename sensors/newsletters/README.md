# Newsletters Sensor

Generic Gmail-IMAP sensor for paid/private newsletters. Polls a Gmail
account, watches one or more labels populated by Gmail filters, and emits
KOI bundles for each newsletter email — full HTML body included. Designed
for paid Substack subscriptions where the email contains the full post
that the public RSS feed would otherwise truncate.

Per-sender routing maps email senders to a slug + `is_private` flag +
`access_source`, matching the Notion sensor's privacy plumbing.

## Adding a new newsletter

1. **Subscribe** to the newsletter using `darrenainews@gmail.com` (or
   forward from another address).
2. **Add a Gmail filter** in `darrenainews@gmail.com`: `From contains
   <senderdomain>` → apply label `KOI/Substack` (or another label that
   the sensor watches per `imap.folders` in `config.yaml`).
3. **Add a route** in `config.yaml`:
   ```yaml
   newsletters:
     - match: <substring-of-from-or-list-id>
       slug: <my-newsletter>
       access_source: newsletter-my-source
       tags: [newsletter, ai, ...]
       is_private: true   # @regen.network OAuth required to read
   ```
4. **Restart**: `sudo systemctl restart koi-sensor@newsletters`.

The `match` field is a case-insensitive substring matched against the
combined `From` address and `List-Id` headers. First match wins.

## Credentials

Gmail app password lives in `/opt/projects/koi-sensors/.env`:

```
GMAIL_NEWSLETTERS_APP_PASSWORD=<16-char-app-password>
```

Generate at https://myaccount.google.com/apppasswords (requires 2FA on
the account). `config.yaml` references it via `imap.password_env`.

## Logs and state

- Logs: `journalctl -u koi-sensor@newsletters -f`
- State: `newsletters_sensor_state.json` — tracks per-folder UID watermark
  (keyed by `UIDVALIDITY`) and the set of RIDs already emitted.
  Delete to re-emit from scratch (will refetch all messages newer than
  `filtering.max_age_days`).

## Why the IMAP-on-prod approach

- Gmail IMAP is direct (no Bridge), prod-class reliability.
- App password is scoped to the dedicated `darrenainews@gmail.com`
  account, which is purpose-built for newsletter ingestion. Blast radius
  if leaked: someone reads AI newsletters. No personal mail exposure.
- `is_private: true` means the content is only visible to authenticated
  `@regen.network` users querying via `regen-koi-mcp`.
