from audiosource_win_pkg.diagnostics import CheckResult, port_available, summarize_status


def test_check_result_aggregation():
    assert summarize_status([CheckResult("a", "OK", "ok")]) == "OK"
    assert summarize_status([CheckResult("a", "WARN", "warn")]) == "WARN"
    assert summarize_status([CheckResult("a", "FAIL", "fail")]) == "FAIL"


def test_port_available_with_free_port():
    assert port_available("127.0.0.1", 0)
