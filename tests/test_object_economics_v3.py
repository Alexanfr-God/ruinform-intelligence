from __future__ import annotations

from types import SimpleNamespace

from ruinform_intelligence import object_economics_v2 as v2
from ruinform_intelligence import object_economics_v3 as v3


def _base_economics():
    return SimpleNamespace(
        creator_wallet="creator-wallet",
        agreement_status="NOT_SIGNED",
        terms_version="",
        terms_hash="",
        terms_text="",
        royalty_bps=500,
        royalty_percent=5.0,
        signed_at_iso=None,
        nft_status="NOT_MINTED",
        blockers=[],
        eligible_to_mint=False,
    )


def test_valid_live_proof_allows_mint_independent_of_ai_match_score(monkeypatch) -> None:
    """The 14/100 RuF-0004 case must remain mint-eligible.

    Object Match is provenance. The economics gate intentionally does not read or
    threshold the AI score; only the live-proof result is a physical-proof gate.
    """

    monkeypatch.setattr(v2, "_legacy_read_object_economics", lambda _object_id: _base_economics())
    monkeypatch.setattr(
        v3,
        "_read_current_agreement",
        lambda _object_id: ("creator-wallet", v3.TERMS_VERSION, v3.TERMS_HASH, 500, "2026-10-03T00:00:00Z"),
    )
    monkeypatch.setattr(v2, "_live_proof_status", lambda _object_id: "valid")

    result = v3.read_object_economics("RF-0004")

    assert result.eligible_to_mint is True
    assert result.blockers == []
    assert result.agreement_status == "SIGNED"
    assert result.terms_hash == v3.TERMS_HASH


def test_missing_live_proof_blocks_mint_even_with_signed_current_agreement(monkeypatch) -> None:
    monkeypatch.setattr(v2, "_legacy_read_object_economics", lambda _object_id: _base_economics())
    monkeypatch.setattr(
        v3,
        "_read_current_agreement",
        lambda _object_id: ("creator-wallet", v3.TERMS_VERSION, v3.TERMS_HASH, 500, "2026-10-03T00:00:00Z"),
    )
    monkeypatch.setattr(v2, "_live_proof_status", lambda _object_id: None)

    result = v3.read_object_economics("RF-0004")

    assert result.eligible_to_mint is False
    assert result.blockers == ["LIVE_PHYSICAL_PROOF_REQUIRED"]


def test_old_agreement_hash_does_not_unlock_current_terms(monkeypatch) -> None:
    monkeypatch.setattr(v2, "_legacy_read_object_economics", lambda _object_id: _base_economics())
    monkeypatch.setattr(v3, "_read_current_agreement", lambda _object_id: None)
    monkeypatch.setattr(v2, "_live_proof_status", lambda _object_id: "valid")

    result = v3.read_object_economics("RF-0004")

    assert result.agreement_status == "NOT_SIGNED"
    assert result.terms_version == v3.TERMS_VERSION
    assert result.terms_hash == v3.TERMS_HASH
    assert result.eligible_to_mint is False
    assert result.blockers == ["CREATOR_AGREEMENT_NOT_SIGNED"]
