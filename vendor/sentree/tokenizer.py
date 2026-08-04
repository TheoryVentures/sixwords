"""Sentence tokenization via PySBD."""

from __future__ import annotations

from pysbd import Segmenter

_segmenter = Segmenter(language="en", clean=False)


def sent_tokenize(text: str) -> list[str]:
    """Split *text* into sentences using PySBD."""
    text = text.strip()
    if not text:
        return []

    sentences = _segmenter.segment(text)
    return [s.strip() for s in sentences if s.strip()]
