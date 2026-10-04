__version__ = "0.2.4"

# Keep the deployed immutable Devnet Sale V0 program and backend verifier aligned.
# Imported at package load so every artifact-sales route reads the v2 chain state.
from . import artifact_sales_v2_patch as _artifact_sales_v2_patch  # noqa: F401,E402

# RF-FEES-v2 applies a 0.01 SOL RUINFORM service fee to each normal on-chain
# Sale step in DEVNET LAB only. Mainnet remains gated and unchanged.
from . import artifact_sales_fee_v2_patch as _artifact_sales_fee_v2_patch  # noqa: F401,E402
