---
branch: main
category: technical
date: '2025-08-07T21:18:38.901129'
document_id: fb5e4cf9318ffd21
file_path: docs/ledger/migrations/v6.0-migration.md
repository: regen-ledger
source: github:regen-ledger
source_type: github
subcategory: regen-ledger
tags:
- regen-ledger
- token
- technical
- ecocredit
- guide
title: Migration Guide v6.0
url: https://github.com/regen-network/regen-ledger/blob/main/docs/ledger/migrations/v6.0-migration.md
---

# Migration Guide v6.0

# Migration Guide v6.0

## API Changes

### cosmos

Regen Ledger v6.0 includes an update to [Cosmos SDK 0.47](https://github.com/cosmos/cosmos-sdk/releases/tag/v0.47.17) and the addition of Cosmwasm module.

### regen.data.v2

Regen Ledger v6.0 deprecates regen.data.v1 and migrate to the regen.data.v2 protobuf API which enables off-chain coordination of supported algorithms and file types.

### regen.ecocredit.v1

Regen Ledger v6.0 includes non-breaking changes to [regen.ecocredit.v1](https://buf.build/regen/regen-ledger/docs/main:regen.ecocredit.v1).

#### Msg Service

The following messages have been added:

- [v1.MsgBurnRegen](https://buf.build/regen/regen-ledger/docs/main:regen.ecocredit.v1#regen.ecocredit.v1.MsgBurnRegen)

#### Events

The following events have been added:

- [v1.EventBurnRegen](https://buf.build/regen/regen-ledger/docs/main:regen.ecocredit.v1#regen.ecocredit.v1.EventBurnRegen)

---
*Source: [https://github.com/regen-network/regen-ledger/blob/main/docs/ledger/migrations/v6.0-migration.md](https://github.com/regen-network/regen-ledger/blob/main/docs/ledger/migrations/v6.0-migration.md)*
*Indexed: 2025-08-13*
