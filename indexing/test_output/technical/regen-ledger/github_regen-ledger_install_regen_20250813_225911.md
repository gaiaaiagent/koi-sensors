---
title: Install Regen
description: |
  The following instructions are for building and installing the binary. In these instructions, we use the same version that was used to start both Regen Mainnet.
source: "github:regen-ledger"
source_type: github
category: technical
subcategory: regen-ledger
tags:
  - token
  - regen-ledger
  - guide
date: "2025-08-07T21:18:38.902129"
url: |
  https://github.com/regen-network/regen-ledger/blob/main/docs/validators/get-started/install-regen.md
document_id: 0b7a4c0175e1693e
repository: regen-ledger
file_path: docs/validators/get-started/install-regen.md
branch: main
---
# Install Regen

# Install Regen

The following instructions are for building and installing the `regen` binary. In these instructions, we use the same version that was used to start both Regen Mainnet. An alternative to syncing a node from genesis is [Using State Sync](using-state-sync.md) with the latest version.

## Prerequisites

- [Initial Setup](README)

## Installation

Clone the `regen-ledger` repository:

```bash
git clone https://github.com/regen-network/regen-ledger
```

Change to the `regen-ledger` directory:

```bash
cd regen-ledger
```

Check out the genesis version:

```bash
git checkout v6.0.0
```

Build and install the `regen` binary:

```bash
make install
```

Check to make sure the installation was successful:

```bash
regen version
```

You should see the following:

```bash
v6.0.0
```

---
*Source: [https://github.com/regen-network/regen-ledger/blob/main/docs/validators/get-started/install-regen.md](https://github.com/regen-network/regen-ledger/blob/main/docs/validators/get-started/install-regen.md)*
*Indexed: 2025-08-13*
