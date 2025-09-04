---
author: Regen Network
category: governance
date: '2025-08-13'
document_id: e6c640029f6b2d69
published_date: '2025-08-13'
source: medium:regen-network
source_type: article
subcategory: articles
tags:
- Ecological Economics
- article
- medium
- blog
- governance_update
- Regen Network
- Blockchain
- Ecocredit
- Regen Ledger
title: Bringing full ecocredit lifecycles on-chain with Regen Ledger v4.0
url: https://regen-network.medium.com/bringing-the-full-eco-credit-lifecycle-on-chain-with-regen-ledger-v4-0-183ca96ea7c7
---

# Bringing full ecocredit lifecycles on-chain with Regen Ledger v4.0

# Bringing full ecocredit lifecycles on-chain with Regen Ledger v4.0

## Announcing the largest release since Regen Ledger’s launch

[](/@regen-network?source=post_page---byline--183ca96ea7c7---------------------------------------)

[Regen Network](/@regen-network?source=post_page---byline--183ca96ea7c7---------------------------------------)

7 min read

·

Jul 28, 2022

[](/m/signin?actionUrl=https%3A%2F%2Fmedium.com%2F_%2Fvote%2Fregen-network%2F183ca96ea7c7&operation=register&redirect=https%3A%2F%2Fmedium.com%2Fregen-network%2Fbringing-the-full-eco-credit-lifecycle-on-chain-with-regen-ledger-v4-0-183ca96ea7c7&user=Regen+Network&userId=b1f22eadb5f&source=---header_actions--183ca96ea7c7---------------------clap_footer------------------)

\--

[](/m/signin?actionUrl=https%3A%2F%2Fmedium.com%2F_%2Fbookmark%2Fp%2F183ca96ea7c7&operation=register&redirect=https%3A%2F%2Fmedium.com%2Fregen-network%2Fbringing-the-full-eco-credit-lifecycle-on-chain-with-regen-ledger-v4-0-183ca96ea7c7&source=---header_actions--183ca96ea7c7---------------------bookmark_footer------------------)

Listen

Share

Press enter or click to view image in full size

We’re excited to announce all-new features and upgrades coming to [Regen Ledger](https://docs.regen.network/ledger/)! These additions and improvements to [Regen Network’s](https://www.regen.network/) blockchain will bring a complete ecocredit lifecycle on-chain, add marketplace functionality for selling and buying ecocredits, and bridge functionality to provide new sources of ecocredit supply to the ecosystem.

Thank you to our community for voting on Proposal 14 on [Keplr](https://wallet.keplr.app/chains/regen/proposals/14), the software proposal for the upgrade to Regen Ledger 4.0. With voter approval, the web-based user interface will now move forward to go live in September. More details can be found in the [long form proposal](https://github.com/regen-network/governance/tree/main/proposals/2022-07-regen-ledger-v4.0-upgrade).

Press enter or click to view image in full size

## **Adding Marketplace Functionality to the Ecocredit Module**

The [ecocredit module](https://docs.regen.network/modules/ecocredit/) includes a new marketplace submodule that makes it possible to create sell orders for ecocredits, and to perform direct buy orders against those sell orders. When a sell order is created in the simple storefront model, the ecocredits being sold are held in escrow. The default behavior is to have ecocredits auto-retired upon sale, but the seller has the option to disable auto-retirement. When a sell order has auto-retirement disabled, the buyer can choose to receive the purchased ecocredits in a retired or tradable state.

Credit Owners can only list ecocredits for sale with a token denom that is on an “[allowed denom](https://commonwealth.im/regen/discussion/4959-adding-tokens-to-the-regen-ledger-currency-allow-list)” list specific to the marketplace and controlled through $REGEN on-chain governance. The allowed denom list will be empty at the time of the Regen Ledger 4.0 upgrade, and the community will be able to submit network governance proposals to add allowed denoms following the upgrade.

Press enter or click to view image in full size

## **Updating the Ecocredit Module to Support On-Chain Projects**

On-the-ground projects providing ecosystem services will now be represented as on-chain entities using a Project ID on Regen Ledger. In this initial implementation, a Credit Class Issuer can assign a Project ID to a project that is enrolled within a specific Credit Class. When a Project ID is created, the Credit Class Issuer is established as the initial Project ID Admin, which can be reassigned to the $REGEN wallet address of the project team.

Information about each project, including details such as project location, will be stored via the Project ID. Each Credit Batch of issued ecocredits will include a Project ID.

## **Credit Batch Denoms**

Adding support for on-chain Project IDs required updating the format of the Credit Batch denom to include the Project ID. The Credit Batch denom was previously formatted to include the Credit Type abbreviation, the Credit Class ID, the start and end dates for the monitoring period, and the Credit Batch sequence number scoped to the Credit Class. The Credit Batch denom is now formatted to include the Project ID, and the Credit Batch sequence number is now scoped to the Project ID.

Press enter or click to view image in full size

## **Adding Ecological Data Services**

The first version of the [Data Module](https://docs.regen.network/modules/data/) supports the ability to anchor data on Regen Ledger, attest to the veracity of anchored data, to define a data resolver and register anchored data to that resolver. Anchoring data (also known as “secure timestamping”) does not store the data on-chain, but rather stores a content hash of the data alongside a timestamp that represents the time at which the data was anchored. If the data is altered in any way, the content hash will be different and the data will need to be anchored again as a separate entry.

The initial use case for the data module will be to anchor data specific to each Credit Class, Project ID, and Credit Batch, including methodologies, baseline and monitoring reports for Project IDs issuing Credit Batches. Anchoring data generates a unique deterministic identifier (an IRI) that will then be stored in the metadata field for each Credit Class, Project ID, and Credit Batch. The data can optionally be registered to a resolver for convenient public (or private/verified) lookups and attested to as a means of verification.

The intention of this design is to allow for those anchoring datasets to have control over the privacy of their data. Credit Issuers and Project ID admins can leverage Regen Ledger for data anchoring and attestation, while keeping the raw datasets associated with those IRIs private if they choose. In a future software release, we intend to support [merklized hash formats](https://en.wikipedia.org/wiki/Merkle_tree), which would enable individual elements of datasets to be selectively disclosed to the public for research or to a specific ecocredit buyer.

Press enter or click to view image in full size

## **Minting and Bridging Cross-Chain Credits**

Over the past few months, Regen Network Development Inc. has been working alongside the [Toucan](https://toucan.earth/) engineering team to develop a bridge service that will enable bridging ecocredits to/from the [Polygon](https://polygon.technology/) blockchain to Regen Ledger. The initial use case of the bridge service will be to bridge Toucan’s [TCO2](https://docs.toucan.earth/protocol/bridge/tco2-toucan-carbon-tokens) tokens to Regen Ledger to establish a market for [NCT](/regen-network/introducing-nature-carbon-ton-nct-6d0fbaaf490d), Nature Carbon Ton, in the Cosmos ecosystem, a digital carbon standard that was co-designed by [Moss.Earth](https://moss.earth/), Regen Network, and Toucan.

In support of these efforts, we have added functionality in Regen Ledger v4.0 to support dynamic batch minting that enables bridged assets from the same ecocredit vintage to be minted to a pre-existing Credit Batch. Each Credit Batch will be “sealed” by default so that Credit Batches with ecocredits issued natively on Regen Ledger can remain immutable.

When ecocredits are bridged from Regen Ledger to Polygon, the ecocredits will be canceled, indicating that the ecocredits have moved to another blockchain. The bridge service will then read the event emitted from the execution of the bridge message and process the bridge request.

The functionality to support bridging assets is included in Regen Ledger v4.0 but the bridge service itself will be launched collaboratively by RND Inc. and Toucan this fall, in conjunction with the [launch of the REGEN:NCT pool](https://gov.osmosis.zone/discussion/3936-proposal-osmosis-carbon-market-with-regen-network) on the [Osmosis exchange](https://osmosis.zone/).

## **Migrating Ecocredit and Data Module to a New and Improved Storage Model (ORM)**

Regen Ledger v4.0 makes use of an [ORM storage model](https://en.wikipedia.org/wiki/Object%E2%80%93relational_mapping#:~:text=Object%E2%80%93relational%20mapping%20\(ORM%2C,from%20within%20the%20programming%20language.) implemented within the [ORM module within Cosmos SDK](https://docs.cosmos.network/main/architecture/adr-055-orm.html#adr-055-orm) that acts as an abstraction layer over the existing [KV store](https://docs.cosmos.network/main/core/store.html#base-layer-kvstores). The ORM module enables the creation of database tables with [primary and secondary keys](https://en.wikipedia.org/wiki/Primary_key). The ORM module’s abstraction layer provides support for efficient lookups and will improve the velocity of future feature development on Regen Ledger.

## **Improved API Naming**

Regen Ledger v4.0 includes a significant number of minor [API](https://docs.regen.network/ledger/infrastructure/interfaces.html#command-line-interface) changes intended to provide more consistent naming throughout the API and to provide an overall better user experience. The API is defined in proto files that are now available on [Buf Schema Registry](https://buf.build/regen/regen-ledger).

Press enter or click to view image in full size

## **Experimental Builds**

**Group Module  
** The experimental build on Hambach testnet includes an earlier version of the [Group Module](https://docs.regen.network/modules/group/) before it migrated to Cosmos SDK. This has since been updated and included in [Cosmos SDK v0.46](https://github.com/cosmos/cosmos-sdk/issues/11096) (released but Regen Ledger v4.0 is still using Cosmos SDK v0.45). The Group Module allows for the creation and management of on-chain multisignature accounts and enables voting for message execution based on configurable decision policies.

**CosmWasm Module  
** The [CosmWasm Module](https://docs.cosmwasm.com/docs/1.0/) on Hambach testnet provides a smart contract platform built for the Cosmos ecosystem. Smart contracts can be written in Rust and deployment can either be permissionless or governance-gated. We are planning to start with permissionless given we are only enabling it on our [experimental test network](https://docs.regen.network/ledger/get-started/live-networks.html). We would like to give users an opportunity to experiment with smart contracts and develop application-specific use cases before further considering this feature for Regen Ledger mainnet.

> _Community reminder:_ [Hambach Testnest](https://docs.regen.network/ledger/get-started/live-networks.html) is “experimental” and may be restarted. Therefore there are no guarantees that data will persist over an extended period of time. Stay tuned for updates on Regen Ledger’s [Live Networks](https://docs.regen.network/ledger/get-started/live-networks.html).

Press enter or click to view image in full size

## **Takeaways**

As the largest release since Regen Ledger’s launch, we’re proud of the effort and significant progress that this represents. We covered huge ground by bringing the full ecocredit cycle onto Regen Ledger, and by paving the way for new sources of ecocredit supply with the bridge functionality. At the same time, we’re already looking to the future. Going forward, we’d like to focus on smaller, more iterative software release cycles.

We’ve said it before: it takes a village to build a blockchain. We’d like to thank the Regen Network community for its support, and specifically the Cambium team for their help with testing and improving this initial version of the Data Module. Thank you also to the [Regen Ledger Development team](https://www.regen.network/team/), which includes Tyler Goodman, Aleem MD, Kaustubh Kapatral, and Ryan Christoffersen, with support from Cory Levinson and Aaron Craelius.

---
*Source: [https://regen-network.medium.com/bringing-the-full-eco-credit-lifecycle-on-chain-with-regen-ledger-v4-0-183ca96ea7c7](https://regen-network.medium.com/bringing-the-full-eco-credit-lifecycle-on-chain-with-regen-ledger-v4-0-183ca96ea7c7)*
*Indexed: 2025-08-13*
