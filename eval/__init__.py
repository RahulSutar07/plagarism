"""Benchmark dataset and evaluation scripts package.

Measures precision, recall, F1, and false-positive rates across plagiarism categories.
"""
from eval.run_benchmark import BenchmarkSummary, CategoryMetrics, run_benchmark

__all__ = ["run_benchmark", "BenchmarkSummary", "CategoryMetrics"]
