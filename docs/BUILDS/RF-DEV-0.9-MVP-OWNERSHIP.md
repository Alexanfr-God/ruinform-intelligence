# RF-DEV-0.9 — MVP Ownership Core

## Product decision

RUINFORM MVP is the Artifact Passport and its on-chain ownership lifecycle.

Primary loop:

`VERIFY → MINT → PASSPORT → OWNER → TRANSFER → OWNERSHIP HISTORY`

Marketplace sale / escrow remains a future capability. Existing Devnet sale code is retained for research and compatibility, but it is not part of the MVP user flow.

## MVP rules

1. One physical Artifact maps to one RUINFORM Artifact Passport.
2. Mint creates the Passport once. A completed mint remains locked after reload.
3. The current Solana owner of the Passport is the source of truth for digital ownership.
4. RUINFORM provides a simple direct Passport transfer for current owners.
5. Transfers performed outside RUINFORM (for example directly in Phantom) must still be detected and appended to provenance as external on-chain transfers.
6. Creator provenance never changes when ownership changes.
7. A normal transfer is not a sale. No resale royalty is inferred from a wallet-to-wallet transfer.
8. The 5% RUINFORM resale royalty is reserved for future RUINFORM Marketplace settlement.
9. Marketplace / escrow is future scope and must not block mint, passport viewing, or direct ownership transfer in the MVP.
10. The active Phantom account must update immediately when the user changes accounts. RUINFORM must not keep a stale wallet address as the active identity.

## Wallet identity rule

The browser must treat Wallet Standard account-change events as authoritative. When Phantom switches from account A to account B:

- clear the authenticated RUINFORM session for A;
- replace the active account with B immediately;
- never restore A from localStorage as the active account;
- require a fresh RUINFORM message signature only for authenticated actions;
- refetch Passport permissions for B.

## Ownership event model

Every durable ownership change should be representable as an event:

- `MINT`
- `RUINFORM_TRANSFER`
- `EXTERNAL_TRANSFER`
- later: `MARKETPLACE_SALE`

Minimum provenance fields:

- object_id
- asset_address
- event_type
- from_wallet
- to_wallet
- transaction_signature when available
- detected_at
- network

RUINFORM direct transfers may include additional context. External transfers should never invent a physical handoff or sale reason.

## Deferred marketplace / escrow

Escrow exists to protect strangers exchanging money for a physical Artifact. It requires dispute, delivery and fraud rules and is therefore deferred from MVP.

Future Marketplace may use escrow so RUINFORM can atomically route:

- sale proceeds to seller;
- RUINFORM resale royalty;
- Artifact Passport ownership to buyer.

No marketplace assumptions should be imposed on ordinary wallet transfers.

## Acceptance criteria

- Minted Passport survives reload as `MINTED ✓`.
- Switching Phantom accounts updates RUINFORM without Disconnect.
- Current on-chain owner is visible on Passport.
- Current owner can transfer Passport directly from RUINFORM.
- Sending Passport outside RUINFORM is detected on next reconciliation and written into ownership history as `EXTERNAL TRANSFER`.
- Sale / escrow controls are not part of the default MVP Passport flow.
- Mainnet remains manually gated.
