from evals.metrics import error_rates, evidence_recall


def test_ocr_error_rates_and_evidence_recall():
    assert error_rates("cuti lima hari", "cuti lima hari") == {"cer": 0, "wer": 0}
    assert error_rates("cuti lima hari", "cuti enam hari")["wer"] == 1 / 3
    assert evidence_recall(["p1", "p2"], ["p1", "p3"]) == .5
