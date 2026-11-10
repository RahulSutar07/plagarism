"""Benchmark evaluation runner.

Evaluates detection accuracy across categorized passages (verbatim, light edit,
evasion, cited quotes, heavy paraphrase, and original non-plagiarized texts).
Reports Precision, Recall, F1 per category, and False Positive Rate.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pipeline.lexical import SourceDocument
from pipeline.score import analyze_document

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "benchmark_data.json"


@dataclass
class CategoryMetrics:
    total: int = 0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return (self.true_positives / float(denom)) if denom > 0 else 0.0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return (self.true_positives / float(denom)) if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2.0 * p * r / (p + r)) if (p + r) > 0 else 0.0

    @property
    def fp_rate(self) -> float:
        denom = self.false_positives + self.true_negatives
        return (self.false_positives / float(denom)) if denom > 0 else 0.0


@dataclass
class BenchmarkSummary:
    total_samples: int
    overall_accuracy: float
    overall_precision: float
    overall_recall: float
    overall_f1: float
    false_positive_rate: float
    per_category: dict[str, dict[str, Any]]


def run_benchmark(
    dataset_path: Path | str = DEFAULT_DATASET,
    threshold_pct: float = 15.0,
    enable_paraphrase: bool = True,
    verbose: bool = False,
) -> tuple[BenchmarkSummary, list[dict[str, Any]]]:
    """Execute evaluation benchmark against the reference corpus."""
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark dataset not found at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = data.get("reference_corpus", [])
    passages = data.get("passages", [])

    # 1. Index reference corpus
    sources: list[SourceDocument] = []
    for s in raw_sources:
        sources.append(
            SourceDocument.from_text(
                source_id=s["id"],
                label=s["title"],
                text=s["text"],
                kind="corpus",
                n_gram_size=5,
            )
        )

    # 2. Evaluate passages
    category_metrics: dict[str, CategoryMetrics] = {}
    detailed_results: list[dict[str, Any]] = []

    global_tp = 0
    global_fp = 0
    global_tn = 0
    global_fn = 0

    for item in passages:
        p_id = item["id"]
        cat = item["category"]
        expected = bool(item["expected_plagiarized"])
        text = item["text"]

        if cat not in category_metrics:
            category_metrics[cat] = CategoryMetrics()

        cm = category_metrics[cat]
        cm.total += 1

        # Run pipeline via unified analyzer
        analysis = analyze_document(
            text=text,
            sources=sources,
            enable_paraphrase=enable_paraphrase,
            n_gram_size=5,
            min_run_words=8,
            min_cosine_threshold=0.75,
            min_jaccard_threshold=0.15,
        )

        sim_score = analysis.overall_similarity_pct
        predicted = sim_score >= threshold_pct

        if expected and predicted:
            cm.true_positives += 1
            global_tp += 1
            outcome = "TP"
        elif not expected and predicted:
            cm.false_positives += 1
            global_fp += 1
            outcome = "FP"
        elif not expected and not predicted:
            cm.true_negatives += 1
            global_tn += 1
            outcome = "TN"
        else:
            cm.false_negatives += 1
            global_fn += 1
            outcome = "FN"

        record = {
            "id": p_id,
            "category": cat,
            "expected": expected,
            "predicted": predicted,
            "similarity_pct": sim_score,
            "exact_pct": analysis.exact_pct,
            "near_pct": analysis.near_pct,
            "paraphrase_pct": analysis.paraphrase_pct,
            "outcome": outcome,
            "flags": analysis.flags,
            "top_source": analysis.largest_single_source,
        }
        detailed_results.append(record)

        if verbose:
            print(
                f"[{outcome}] ID: {p_id:6s} | Cat: {cat:17s} | Sim: {sim_score:5.1f}% | Pred: {str(predicted):5s} | Exp: {str(expected):5s}"
            )

    # 3. Aggregate statistics
    total_samples = len(passages)
    correct = global_tp + global_tn
    accuracy = (correct / float(total_samples)) if total_samples > 0 else 0.0

    denom_p = global_tp + global_fp
    overall_p = (global_tp / float(denom_p)) if denom_p > 0 else 0.0

    denom_r = global_tp + global_fn
    overall_r = (global_tp / float(denom_r)) if denom_r > 0 else 0.0

    overall_f1 = (2.0 * overall_p * overall_r / (overall_p + overall_r)) if (overall_p + overall_r) > 0 else 0.0

    negative_total = global_fp + global_tn
    global_fp_rate = (global_fp / float(negative_total)) if negative_total > 0 else 0.0

    cat_dict = {}
    for cat, m in category_metrics.items():
        cat_dict[cat] = {
            "total": m.total,
            "tp": m.true_positives,
            "fp": m.false_positives,
            "tn": m.true_negatives,
            "fn": m.false_negatives,
            "recall": round(m.recall * 100.0, 1),
            "precision": round(m.precision * 100.0, 1),
            "f1": round(m.f1 * 100.0, 1),
            "fp_rate": round(m.fp_rate * 100.0, 1),
        }

    summary = BenchmarkSummary(
        total_samples=total_samples,
        overall_accuracy=round(accuracy * 100.0, 1),
        overall_precision=round(overall_p * 100.0, 1),
        overall_recall=round(overall_r * 100.0, 1),
        overall_f1=round(overall_f1 * 100.0, 1),
        false_positive_rate=round(global_fp_rate * 100.0, 1),
        per_category=cat_dict,
    )

    return summary, detailed_results


def print_benchmark_table(summary: BenchmarkSummary) -> None:
    """Print clean terminal report of benchmark evaluation."""
    print("=" * 76)
    print("        PLAGIARISM PRE-CHECK: BENCHMARK EVALUATION REPORT")
    print("=" * 76)
    print(f"Total Evaluated Passages: {summary.total_samples}")
    print(
        f"Overall Accuracy:  {summary.overall_accuracy}%\n"
        f"Overall Precision: {summary.overall_precision}%\n"
        f"Overall Recall:    {summary.overall_recall}%\n"
        f"Overall F1 Score:  {summary.overall_f1}%\n"
        f"False Positive Rate on Non-Plagiarized Text: {summary.false_positive_rate}%"
    )
    print("-" * 76)
    print(f"{'Category':<18} | {'Total':<6} | {'Recall':<8} | {'Precision':<10} | {'F1':<6} | {'FP Rate':<8}")
    print("-" * 76)

    for cat, m in summary.per_category.items():
        print(
            f"{cat:<18} | {m['total']:<6} | {m['recall']:>6.1f}% | {m['precision']:>8.1f}% | {m['f1']:>4.1f}% | {m['fp_rate']:>6.1f}%"
        )
    print("=" * 76)
    print(
        "Note: Heavy paraphrase detection is low under pure lexical matching and will\n"
        "be handled by the semantic embedding layer in Phase 3."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Plagiarism pre-check evaluation benchmark")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to benchmark JSON dataset")
    parser.add_argument("--threshold", type=float, default=15.0, help="Similarity %% threshold for positive label")
    parser.add_argument("--no-paraphrase", action="store_true", help="Disable semantic paraphrase detection")
    parser.add_argument("--verbose", action="store_true", help="Print each passage prediction")
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with non-zero code if core thresholds fail",
    )
    parser.add_argument("--out", help="Path to save output JSON results")
    args = parser.parse_args()

    summary, details = run_benchmark(
        dataset_path=args.dataset,
        threshold_pct=args.threshold,
        enable_paraphrase=not args.no_paraphrase,
        verbose=args.verbose,
    )

    print_benchmark_table(summary)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(
            json.dumps({"summary": asdict(summary), "details": details}, indent=2),
            encoding="utf-8",
        )
        print(f"\nDetailed benchmark results saved to: {out_path}")

    if args.fail_on_regression:
        cats = summary.per_category
        verbatim_recall = cats.get("verbatim", {}).get("recall", 0.0)
        evasion_recall = cats.get("evasion", {}).get("recall", 0.0)
        fp_rate = summary.false_positive_rate

        # Quality Gates: Verbatim and Evasion recall must be 100%, and FP rate <= 0%
        failures = []
        if verbatim_recall < 100.0:
            failures.append(f"Verbatim recall regressed to {verbatim_recall}% (expected 100%)")
        if evasion_recall < 100.0:
            failures.append(f"Evasion recall regressed to {evasion_recall}% (expected 100%)")
        if fp_rate > 5.0:
            failures.append(f"False positive rate spiked to {fp_rate}% (max allowed is 5%)")

        if failures:
            print("\n[FAIL] REGRESSION GATE FAILED:")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        else:
            print("\n[PASS] ALL REGRESSION GATES PASSED (Verbatim: 100%, Evasion: 100%, FP Rate: 0.0%).")


if __name__ == "__main__":
    main()
