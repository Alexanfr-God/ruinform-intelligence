__version__ = "0.2.8"

# Keep the deployed immutable Devnet Sale V0 program and backend verifier aligned.
# Imported at package load so every artifact-sales route reads the v2 chain state.
from . import artifact_sales_v2_patch as _artifact_sales_v2_patch  # noqa: F401,E402

# RF-FEES-v2 applies a 0.01 SOL RUINFORM service fee to each normal on-chain
# Sale step in DEVNET LAB only. RF-DEV-0.8 additionally persists an auditable
# per-sale fee ledger. Mainnet remains gated and unchanged.
from . import artifact_sales_fee_v2_patch as _artifact_sales_fee_v2_patch  # noqa: F401,E402

# Recover a LIST transaction that succeeded on Solana but was not registered in
# RUINFORM because the HTTP/backend step failed afterwards. Recovery verifies
# the deployed escrow state and the already-paid RF-FEES-v2 listing fee.
from . import artifact_sale_recovery as _artifact_sale_recovery  # noqa: F401,E402

# Human moderation for creator verification appeals. The module adds protected
# admin resolution routes to the existing verification-disputes router.
from . import manual_appeal_review as _manual_appeal_review  # noqa: F401,E402

# RF-DEV-0.9 makes Artifact Passport ownership the MVP core. Marketplace/escrow
# stays preserved as future functionality; ownership routes are registered here
# without changing the legacy Sale implementation.
from . import ownership_bootstrap as _ownership_bootstrap  # noqa: F401,E402

# RF-ID-1.0 links a verified Soulbound RUINFORM ID into the immutable snapshot
# and public metadata of every future Artifact Passport minted by that wallet.
from . import identity_provenance_patch as _identity_provenance_patch  # noqa: F401,E402

# RF-NFT-MEDIA-v1 seals marketplace-safe raster media into every future Artifact
# Passport snapshot. PNG is the primary marketplace image; SVG remains secondary.
from . import nft_media_contract as _nft_media_contract  # noqa: F401,E402
