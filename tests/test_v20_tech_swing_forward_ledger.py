import json
import pytest
from backend.v20_tech_swing_forward_ledger import summarize_snapshots


def snapshot(day, symbol="AAPL"):
    return {"schemaVersion": 1, "researchOnly": True, "ordersSubmitted": 0,
            "buyEnabled": False, "lastCompletedCommonBar": day,
            "preview": {"topCandidate": symbol}}


def test_deduplicate_and_do_not_claim_forward_validation(tmp_path):
    paths = []
    for i, day in enumerate(("2026-11-17", "2026-11-17", "2026-11-18")):
        p = tmp_path / f"{i}.json"
        p.write_text(json.dumps(snapshot(day)))
        paths.append(p)
    r = summarize_snapshots(paths)
    assert r["uniqueDatedSnapshots"] == 2
    assert r["forwardSessionsValidated"] == 0
    assert not r["buyEnabled"]


def test_reject_conflicting_snapshots(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(snapshot("2026-11-17")))
    b.write_text(json.dumps(snapshot("2026-11-17", "META")))
    with pytest.raises(ValueError, match="Conflicting"):
        summarize_snapshots([a, b])
