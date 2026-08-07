"""Story document layer.

Every read and write of the sentree ``Document`` for a six-word story goes
through this module. A story is a single-sentence document: the six words
live in sentence ``s-0001`` and everything that produced them lives in the
sentence's ``meta``, the document ``metadata``, and the sentree edit log.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sentree import Document, Paragraph, Section, Sentence, from_dict, to_dict

FORMAT = "contextdoc/nested-v1"
STORY_SENTENCE_ID = "s-0001"
FILE_SUFFIX = ".subtext.json"

LEGEND = {
    "what_this_is": (
        "A concept packaged into exactly six words, plus the full subtext of how "
        "they were written. The human-facing text is the six words in the single "
        "sentence; the full argument, iterations, and human/AI collaboration that "
        "produced them are recorded on the sentence's meta and the document "
        "metadata."
    ),
    "how_to_read": [
        "The six words are sentence s-0001. Its text is the entire human-facing artifact.",
        "sentence.meta.backstory is the full idea the six words compress — claim, "
        "mechanism, stakes.",
        "sentence.meta.word_choices explains, word by word, why each word earned "
        "its slot and what alternatives were rejected.",
        "sentence.meta.drafts is the chronological evolution of the six words, "
        "each entry stamped with who wrote it (human or agent) and why.",
        "metadata.interview is the question/answer exchange between the writing "
        "assistant and the author that pinned the idea down.",
        "metadata.candidates_considered lists every candidate the assistant "
        "proposed, including the ones that were not chosen.",
        "Sentence provenance (authored_by, author_type, authorship_context) and "
        "metadata.edit_log answer who wrote the final words, when, and why.",
    ],
    "voice": (
        "The author's answers in metadata.interview are their own words. When "
        "presenting or discussing this idea with people, match the author's tone, "
        "register, and vocabulary as evidenced there — channel their voice rather "
        "than a generic assistant's, where the answers give you enough voice to go "
        "on — while staying clear that you are an agent representing the idea, not "
        "the author."
    ),
    "learn_more": (
        "More six-word ideas, each published with its full subtext, live at "
        "https://sixwordidea.com. Every card on the index links to the idea's "
        "raw subtext JSON, fetchable at https://sixwordidea.com/ideas/<slug>.json."
    ),
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def word_count(text: str) -> int:
    return len(text.split())


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "story"


def new_story(
    *,
    title: str,
    text: str,
    authored_by: str,
    author_type: str,
    rationale: str | None = None,
    requested_by: str | None = None,
) -> Document:
    """Create a story document from the first accepted draft."""
    now = _now_iso()
    sentence = Sentence(
        id=STORY_SENTENCE_ID,
        text=text,
        authored_by=authored_by,
        authored_at=now,
        author_type=author_type,
        meta={"drafts": [_draft_entry(text, authored_by, author_type, now, rationale)]},
    )
    doc = Document(
        metadata={
            "title": title,
            "status": "draft",
            "created_at": now,
            "purpose": (
                "A concept packaged into six words; the full argument and the "
                "process that produced them are the subtext."
            ),
            "interview": [],
            "candidates_considered": [],
        },
        sections=[
            Section(
                heading=title,
                level=1,
                blocks=[Paragraph(sentences=[sentence])],
            )
        ],
    )
    doc.record_edit(
        "create_story",
        by=authored_by,
        at=now,
        target_id=STORY_SENTENCE_ID,
        reason=rationale,
        requested_by=requested_by,
    )
    return doc


def revise(
    doc: Document,
    text: str,
    *,
    by: str,
    author_type: str,
    rationale: str | None = None,
    requested_by: str | None = None,
) -> None:
    """Apply a new draft of the six words, preserving the full history."""
    now = _now_iso()
    sentence = doc.update_sentence(
        STORY_SENTENCE_ID,
        text=text,
        authored_by=by,
        author_type=author_type,
        action="revise",
        reason=rationale,
        requested_by=requested_by,
        at=now,
    )
    sentence.meta.setdefault("drafts", []).append(
        _draft_entry(text, by, author_type, now, rationale)
    )


def _draft_entry(
    text: str, by: str, author_type: str, at: str, rationale: str | None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"text": text, "by": by, "author_type": author_type, "at": at}
    if rationale:
        entry["rationale"] = rationale
    return entry


def add_interview_exchange(doc: Document, question: str, answer: str) -> None:
    doc.metadata.setdefault("interview", []).append({"question": question, "answer": answer})


def add_candidates(doc: Document, candidates: list[dict[str, Any]]) -> None:
    """Record a round of proposed candidates, chosen or not."""
    doc.metadata.setdefault("candidates_considered", []).extend(candidates)


def set_backstory(doc: Document, backstory: str) -> None:
    _story_sentence(doc).meta["backstory"] = backstory


def set_word_choices(doc: Document, word_choices: list[dict[str, Any]]) -> None:
    _story_sentence(doc).meta["word_choices"] = word_choices


def finalize(doc: Document, *, by: str) -> None:
    doc.metadata["status"] = "final"
    doc.record_edit("finalize_story", by=by, target_id=STORY_SENTENCE_ID)


def story_text(doc: Document) -> str:
    return _story_sentence(doc).text


def story_sentence(doc: Document) -> Sentence:
    return _story_sentence(doc)


def _story_sentence(doc: Document) -> Sentence:
    sentence = doc.get_sentence(STORY_SENTENCE_ID)
    if sentence is None:
        raise ValueError(f"Document has no story sentence {STORY_SENTENCE_ID!r}")
    return sentence


def save(doc: Document, path: Path) -> Path:
    """Write the story as nested subtext JSON with format marker and legend."""
    data = {"$format": FORMAT, "$legend": LEGEND, **to_dict(doc)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Document:
    data = json.loads(path.read_text(encoding="utf-8"))
    payload = {k: v for k, v in data.items() if not k.startswith("$")}
    return from_dict(payload)


def story_path(stories_dir: Path, title: str) -> Path:
    """A non-clobbering file path for a new story titled *title*."""
    base = slugify(title)
    path = stories_dir / f"{base}{FILE_SUFFIX}"
    n = 2
    while path.exists():
        path = stories_dir / f"{base}-{n}{FILE_SUFFIX}"
        n += 1
    return path
