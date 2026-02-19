# Sensor Envelope Signing — Security Posture

**Status:** Local sensors unsigned; coordinator signs for federation.
**Date:** 2026-02-19
**Commits:** 1ca88e9, f0e6ed1, b3c17c6

## Current Model

```
┌──────────────────────────────────────────────────┐
│  Production Host (202.61.196.119)                │
│                                                  │
│  ┌─────────────┐    unsigned    ┌─────────────┐  │
│  │  Sensors    │───────────────▶│ Coordinator │  │
│  │  (12 units) │  localhost     │  (port 8005)│  │
│  └─────────────┘                └──────┬──────┘  │
│                                        │         │
└────────────────────────────────────────┼─────────┘
                                         │ signed
                                         ▼
                                  ┌─────────────┐
                                  │ Federation  │
                                  │   Peers     │
                                  └─────────────┘
```

- **Local sensors → coordinator:** Unsigned. Sensors set
  `KOI_ENVELOPE_SIGN=false` via `run-sensor.sh`. Traffic is
  localhost-only, so signing adds complexity without security value.

- **Coordinator → federation peers:** Signed. The coordinator uses
  its own keypair (`coordinator_private.pem`) to sign outgoing
  envelopes for external KOI-net nodes.

- **Remote sensor override:** If a sensor is deployed on a different
  host, set `KOI_SENSOR_REMOTE=1` in its environment to preserve
  envelope signing. The `run-sensor.sh` guard only disables signing
  when `KOI_SENSOR_REMOTE` is unset.

## Why Not Per-Sensor Signing?

Each sensor derives a unique node ID (e.g.,
`orn:koi-net.node:ledger-sensor+0b2007...`) from its name + the
shared public key. But the coordinator's `public_keys.json` only
knows about explicitly registered peers. Registering every local
sensor would work but is fragile:

- Keys must be updated when sensors are added/removed
- All sensors share the same keypair anyway (no isolation benefit)
- Localhost traffic doesn't need authentication

## Future: PKI RFC

A proper solution would be one of:

1. **Per-sensor keypairs + auto-registration:** Each sensor generates
   its own keypair on first start and registers with the coordinator
   via a handshake endpoint. Most secure but most complex.

2. **Coordinator-identity model:** Local sensors explicitly adopt the
   coordinator's node ID for broadcasts (act as the coordinator).
   Simple but conflates identities in audit logs.

3. **Current model (keep):** Document and accept that local sensors
   are unsigned. Add network-level controls (firewall, systemd
   socket activation) if localhost trust is insufficient.

See: GitHub issue for PKI RFC tracking.
