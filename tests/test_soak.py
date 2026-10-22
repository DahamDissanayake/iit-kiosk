from tools.soak import summarise


def test_summary_reports_cycles_failures_and_peak_temperature():
    rows = [
        {"ts": 0, "kind": "cycle", "ok": True, "seconds": 30.0, "temp_c": 61.0},
        {"ts": 60, "kind": "cycle", "ok": False, "seconds": 90.0, "temp_c": 72.5},
        {"ts": 180, "kind": "sample", "ok": True, "seconds": 0, "temp_c": 74.0},
    ]
    s = summarise(rows)
    assert s == {"cycles": 2, "failed": 1, "max_temp_c": 74.0, "hours": 0.05}
