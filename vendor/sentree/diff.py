"""Compute sentence-level diffs between two sentree Documents."""

from __future__ import annotations

from difflib import SequenceMatcher
from enum import Enum

from pydantic import BaseModel, Field

from sentree.models import Document, Sentence


class ChangeType(str, Enum):
    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    ADDED = "added"
    REMOVED = "removed"


class SentenceChange(BaseModel):
    """A single change between two document versions."""

    change_type: ChangeType
    old: Sentence | None = None
    new: Sentence | None = None
    similarity: float = 0.0


class DiffSummary(BaseModel):
    """Aggregate counts by change type."""

    unchanged: int = 0
    modified: int = 0
    added: int = 0
    removed: int = 0

    @property
    def total(self) -> int:
        return self.unchanged + self.modified + self.added + self.removed


class DocumentDiff(BaseModel):
    """Result of comparing two Documents at the sentence level."""

    changes: list[SentenceChange] = Field(default_factory=list)
    summary: DiffSummary = Field(default_factory=DiffSummary)

    def filter(self, *types: ChangeType) -> list[SentenceChange]:
        """Return only changes matching the given types."""
        type_set = set(types)
        return [c for c in self.changes if c.change_type in type_set]


def diff(
    old: Document,
    new: Document,
    *,
    similarity_threshold: float = 0.98,
) -> DocumentDiff:
    """Compute a sentence-level diff between two Documents.

    Matches sentences by text content using sequence alignment, so
    positional ID shifts from insertions or deletions don't produce
    false change reports.

    *similarity_threshold* controls the minimum ``SequenceMatcher``
    ratio for two sentences to be considered a modification rather
    than an unrelated add/remove pair.
    """
    old_sentences = list(old.walk_sentences())
    new_sentences = list(new.walk_sentences())

    old_texts = [s.text for s in old_sentences]
    new_texts = [s.text for s in new_sentences]

    matcher = SequenceMatcher(None, old_texts, new_texts, autojunk=False)
    changes: list[SentenceChange] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                changes.append(
                    SentenceChange(
                        change_type=ChangeType.UNCHANGED,
                        old=old_sentences[i1 + k],
                        new=new_sentences[j1 + k],
                        similarity=1.0,
                    )
                )
        elif tag == "insert":
            for k in range(j2 - j1):
                changes.append(
                    SentenceChange(
                        change_type=ChangeType.ADDED,
                        new=new_sentences[j1 + k],
                    )
                )
        elif tag == "delete":
            for k in range(i2 - i1):
                changes.append(
                    SentenceChange(
                        change_type=ChangeType.REMOVED,
                        old=old_sentences[i1 + k],
                    )
                )
        elif tag == "replace":
            changes.extend(
                _match_replace_block(
                    old_sentences[i1:i2],
                    new_sentences[j1:j2],
                    similarity_threshold,
                )
            )

    summary = DiffSummary(
        unchanged=sum(1 for c in changes if c.change_type == ChangeType.UNCHANGED),
        modified=sum(1 for c in changes if c.change_type == ChangeType.MODIFIED),
        added=sum(1 for c in changes if c.change_type == ChangeType.ADDED),
        removed=sum(1 for c in changes if c.change_type == ChangeType.REMOVED),
    )

    return DocumentDiff(changes=changes, summary=summary)


def _match_replace_block(
    old_chunk: list[Sentence],
    new_chunk: list[Sentence],
    threshold: float,
) -> list[SentenceChange]:
    """Resolve a replace block into modified, added, and removed changes.

    Computes pairwise similarity and greedily matches the
    highest-scoring pairs above *threshold*.  Unmatched old sentences
    become removals; unmatched new sentences become additions.
    """
    candidates: list[tuple[float, int, int]] = []
    for i, old_s in enumerate(old_chunk):
        for j, new_s in enumerate(new_chunk):
            sim = SequenceMatcher(None, old_s.text, new_s.text).ratio()
            if sim >= threshold:
                candidates.append((sim, i, j))

    candidates.sort(reverse=True)

    matched_old: set[int] = set()
    matched_new: set[int] = set()
    modifications: list[SentenceChange] = []

    for sim, i, j in candidates:
        if i in matched_old or j in matched_new:
            continue
        modifications.append(
            SentenceChange(
                change_type=ChangeType.MODIFIED,
                old=old_chunk[i],
                new=new_chunk[j],
                similarity=sim,
            )
        )
        matched_old.add(i)
        matched_new.add(j)

    changes: list[SentenceChange] = []

    for i, s in enumerate(old_chunk):
        if i not in matched_old:
            changes.append(
                SentenceChange(change_type=ChangeType.REMOVED, old=s)
            )

    changes.extend(modifications)

    for j, s in enumerate(new_chunk):
        if j not in matched_new:
            changes.append(
                SentenceChange(change_type=ChangeType.ADDED, new=s)
            )

    return changes
