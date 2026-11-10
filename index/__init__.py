"""Corpus and index management package.

Provides disk-based and in-memory indexing of local academic and web reference collections.
"""
from index.corpus import CorpusItem, LocalCorpusIndex

__all__ = ["LocalCorpusIndex", "CorpusItem"]
