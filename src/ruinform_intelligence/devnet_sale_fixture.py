from __future__ import annotations

"""Narrow DEVNET-only mint eligibility fixture for the RF-DEV-0.8 sale test.

This module does not change Object Passport verification data and does not claim
that physical proof exists. It only removes the live-proof mint blocker for one
known DEVNET test object owned by one known creator wallet so the end-to-end
sale/fee ledger can be exercised. The NFT snapshot still records the real raw
live_proof_status from the passport (for this fixture that can remain unknown).
"""

from . import nft_devnet
from . import object_economics as legacy
from . import object_economics_v2 as v2
from . import object_economics_v3 as v3


TARGET_OBJECT_ID = "RF-0006"
TARGET_CREATOR_WALLET = "2CaJKT5PXSYYJtz8oZK5An7EFPDNtpTonMv1PETcTCgY"
LIVE_PROOF_BLOCKER = "LIVE_PHYSICAL_PROOF_REQUIRED"

_base_read_object_economics = v3.read_object_economics


def read_object_economics(object_id: str):
    result = _base_read_object_economics(object_id)
    backend_id = legacy._backend_object_id(object_id)

    is_fixture = (
        backend_id == TARGET_OBJECT_ID
        and result.creator_wallet == TARGET_CREATOR_WALLET
        and result.nft_status != "MINTED"
    )
    if not is_fixture:
        return result

    # Preserve every other requirement: registered creator, signed current
    # Creator Agreement, and one-canonical-NFT rule all remain mandatory.
    result.blockers = [item for item in result.blockers if item != LIVE_PROOF_BLOCKER]
    result.eligible_to_mint = not result.blockers
    return result


# The public economics routes and the Devnet NFT mint snapshot resolve these
# module globals at request time. Patch only the DEVNET runtime path.
legacy.read_object_economics = read_object_economics
v2.read_object_economics = read_object_economics
v3.read_object_economics = read_object_economics
nft_devnet.read_object_economics = read_object_economics
