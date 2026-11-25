import json

from backend.v20_master_pause import is_paused, may_submit_automatic_order


def test_missing_corrupt_or_ambiguous_state_stays_paused(tmp_path):
    p = tmp_path / "pause.json"
    assert is_paused(p)
    for data in ("", "{broken", "{}", '{"version":1,"paused":"false"}',
                 '{"version":2,"paused":false}', '{"version":1,"paused":true}'):
        p.write_text(data)
        assert is_paused(p)


def test_explicit_persisted_resume_survives_repeated_reads(tmp_path):
    p = tmp_path / "pause.json"
    p.write_text(json.dumps({"version": 1, "paused": False}))
    assert not is_paused(p)
    assert may_submit_automatic_order(legacy_enabled=True, emergency_stop=False,
                                      manual_override=False, path=p)
    p.write_text(json.dumps({"version": 1, "paused": True}))
    assert is_paused(p)
    assert not may_submit_automatic_order(legacy_enabled=True, emergency_stop=False,
                                          manual_override=False, path=p)


def test_legacy_guards_remain_required(tmp_path):
    p = tmp_path / "pause.json"
    p.write_text('{"version":1,"paused":false}')
    for enabled, stop, manual in [(False,False,False),(True,True,False),(True,False,True)]:
        assert not may_submit_automatic_order(legacy_enabled=enabled,
                                               emergency_stop=stop,
                                               manual_override=manual,path=p)
