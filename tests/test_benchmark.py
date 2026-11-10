from eval.run_benchmark import run_benchmark


def test_benchmark_regression_gates():
    summary, details = run_benchmark(threshold_pct=15.0)

    # 1. Total samples check
    assert summary.total_samples >= 20

    # 2. Category checks
    cats = summary.per_category

    # Verbatim recall must be 100%
    assert cats["verbatim"]["recall"] == 100.0

    # Evasion recall must be 100%
    assert cats["evasion"]["recall"] == 100.0

    # Light edit recall must be 100%
    assert cats["light_edit"]["recall"] == 100.0

    # False positive rate on original text must be 0%
    assert cats["original"]["fp_rate"] == 0.0
    assert summary.false_positive_rate <= 5.0

    # Overall precision and F1 must be high
    assert summary.overall_precision >= 95.0
    assert summary.overall_f1 >= 85.0
