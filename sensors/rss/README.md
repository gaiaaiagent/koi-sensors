# RSS Sensor

Generic RSS / Atom feed sensor for the koi-sensors framework. Polls feeds
on per-feed intervals and emits KOI bundles for new entries. Supports
per-feed privacy via `is_private` + `access_source` (matches Notion
sensor; consumed by `koi_memories.is_private` and the `NOT node_private`
filters in koi-processor).

## Adding a feed

Edit `config.yaml`:

```yaml
feeds:
  - slug: my-feed                         # used in RID and access_source default
    url: "https://example.com/feed"
    domain: ai                            # free-form bucket
    tags: [tag1, tag2]
    is_private: false                     # true = @regen.network OAuth required
    access_source: rss-my-feed            # any string; appears in koi_memories
    check_interval: 3600
    enabled: true
```

Restart: `sudo systemctl restart koi-sensor@rss`.

## Authenticated / paid feeds

For paid Substacks, get the **private RSS URL** from Substack settings →
"Manage subscription" → "Private RSS feed". The URL contains a long token.

Don't paste the token into `config.yaml`. Put the token portion in the
root `/opt/projects/koi-sensors/.env`:

```
RSS_NATE_SUBSTACK_TOKEN=<token-from-substack>
```

…and reference it via `${VAR}` in the feed URL:

```yaml
url: "https://natesnewsletter.substack.com/feed/private/${RSS_NATE_SUBSTACK_TOKEN}"
```

`run-sensor.sh` sources the root `.env` before launching the sensor;
config-load expands `${VAR}` from `os.environ`. If the variable is unset
the sensor refuses to start.

## Logs

```bash
journalctl -u koi-sensor@rss -f
```

State (RIDs already emitted) lives in `rss_sensor_state.json` next to the
script. Delete it to re-emit a feed from scratch.
