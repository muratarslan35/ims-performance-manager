from pathlib import Path


def test_live_gate_distinguishes_semantic_and_physical_raw_counts():
    text = (Path(__file__).resolve().parents[1] / "verify_live_ims_gate.py").read_text(encoding="utf-8")

    assert 'actual_counts["raw"] >= semantic_raw' in text
    assert 'actual_counts["raw"] == int(upload.raw_record_count' not in text
    assert 'sheet_type="official_brick_spread_master"' in text
    assert '"official_target_aggregate", "official_actual_aggregate"' in text
    assert '"raw_side_channel_delta"' in text


def test_live_gate_keeps_positive_side_channel_audit_counts_strict():
    text = (Path(__file__).resolve().parents[1] / "verify_live_ims_gate.py").read_text(encoding="utf-8")

    assert 'if expected > 0:' in text
    assert 'current == expected' in text
    assert 'post-import side-channel unaccounted' in text
    assert 'raw_side_channel_delta >= current' in text
    assert '"post_import_side_channels"' in text
