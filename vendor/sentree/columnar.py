"""Lossless, token-efficient "columnar" encoding of a sentree document.

Implements the ``contextdoc/columnar-v1`` format: instead of repeating every
field name on all N sentences, the prose lives in parallel arrays (``cols.*``)
and the low-cardinality provenance values (authors, timestamps, actions,
reasons, …) are dictionary-encoded into integer indices. The ``structure``
tree references each sentence by its position in those arrays. The embedded
``$legend`` tells an LLM how to read it.
"""

from __future__ import annotations

import json
from typing import Any

from sentree.models import (
    Block,
    BoldHeading,
    CodeBlock,
    Document,
    ListBlock,
    MathBlock,
    Paragraph,
    Section,
    Sentence,
    Table,
)
from sentree.serialization import from_dict

COLUMNAR_FORMAT = "contextdoc/columnar-v1"

_CTX_STANDARD_KEYS = ("action", "reason", "source_trigger", "requested_by")

_LEGEND: dict[str, Any] = {
    "what_this_is": (
        "A token-efficient, lossless 'columnar' encoding of a structured research "
        "document where every sentence carries authorship provenance. Prose lives "
        "in parallel arrays (one entry per sentence) instead of repeating field "
        "names on every sentence."
    ),
    "how_to_read": [
        "cols.* are parallel arrays. cols.id[n], cols.text[n], cols.by[n], etc. all describe the SAME sentence n (0-based).",
        "Most columns are dictionary-encoded: cols.by/at/type/action/reason/trigger/requested_by hold integer indices into the matching dict.* list. The author of sentence n is dict.by[ cols.by[n] ]; its rationale is dict.reason[ cols.reason[n] ]. A value of -1 means that field is absent on that sentence.",
        "cols.text[n] is the literal sentence; cols.cite[n] is a list of citation keys that resolve via the 'sources' map.",
        "cols.extra is a sparse map of sentence-index -> any extra fields not covered above; it is usually empty.",
        "'structure' is the section tree in reading order. Each block's 's' / 'items' arrays contain sentence indices (n) pointing into cols.*. To reconstruct the readable document, walk structure in order and emit cols.text for each referenced index.",
        "Block kinds (k): 'p'=paragraph, 'list'=bullet/numbered list (see 'ordered'), 'table' (headers+rows), 'bold_heading', 'code', 'math' (display LaTeX equation).",
        "A 'math' block holds its equation source in 'latex' and carries its own provenance INLINE, dictionary-encoded exactly like a sentence: math.by/at/type/action/reason/trigger/requested_by are indices into the same dict.* lists (-1 = absent). So 'who wrote this equation / when / human vs AI' is answered the same way as for a sentence.",
    ],
    "answering_provenance": (
        "To answer 'who wrote sentence X / when / why / how much is AI-generated', "
        "read cols.by/at/type/reason via the dictionaries — no document body needed "
        "beyond cols.text. author_type 'human' vs 'agent' distinguishes "
        "human-written from AI-written sentences. requested_by names the human who "
        "asked the agent to make an edit. Display LaTeX equations ('math' blocks in "
        "structure) are authored units too: they carry the same "
        "by/at/type/action/reason indices inline, so equation authorship is read "
        "identically."
    ),
    "rendering_to_markdown": [
        "If you believe it would be helpful for the user to see this document as Markdown, here is how to render it. Walk 'structure' in reading order and emit blocks using cols.text verbatim (never paraphrase):",
        "Section heading: '#' repeated `level` times, a space, then the heading. Separate consecutive top-level sections with a '----' divider line.",
        "Block k='p' (paragraph): join cols.text[n] for each index n in the block's 's' array with single spaces.",
        "Block k='list': one line per entry in 'items', prefixed '1.' when ordered is true, otherwise '-'; join that entry's sentence texts with spaces.",
        "Block k='bold_heading': '**' + text + '**'. Block k='code': a fenced code block containing text (use 'language' for the fence info string when present).",
        "Block k='math': a display equation — emit '$$' on its own line, then 'latex', then '$$' on its own line.",
        "Block k='table': a standard Markdown pipe table built from 'headers' and 'rows'.",
        "Citations: after a sentence, append each key in cols.cite[n] as '[[KEY]](url)' when sources[KEY] has a url, otherwise '[[KEY]]'.",
    ],
}


class _Interner:
    """Assigns stable integer indices to strings in first-seen order."""

    def __init__(self) -> None:
        self._index: dict[str, int] = {}
        self.values: list[str] = []

    def intern(self, value: str | None) -> int:
        """Return the dict index for *value*, or -1 when absent."""
        if value is None:
            return -1
        existing = self._index.get(value)
        if existing is not None:
            return existing
        nxt = len(self.values)
        self._index[value] = nxt
        self.values.append(value)
        return nxt


def _ctx_parts(
    node: Sentence | MathBlock,
) -> tuple[dict[str, str | None], dict[str, Any] | None]:
    """Split a node's authorship context into standard keys and extras."""
    ctx = node.authorship_context
    if ctx is None:
        return {k: None for k in _CTX_STANDARD_KEYS}, None
    standard: dict[str, str | None] = {}
    for k in _CTX_STANDARD_KEYS:
        v = getattr(ctx, k)
        standard[k] = v if isinstance(v, str) else None
    return standard, dict(ctx.model_extra or {})


def to_columnar(doc: Document) -> dict[str, Any]:
    """Encode a Document into the ``contextdoc/columnar-v1`` format."""
    by = _Interner()
    at = _Interner()
    type_ = _Interner()
    action = _Interner()
    reason = _Interner()
    trigger = _Interner()
    requested_by = _Interner()

    cols: dict[str, Any] = {
        "id": [],
        "text": [],
        "cite": [],
        "by": [],
        "at": [],
        "type": [],
        "action": [],
        "reason": [],
        "trigger": [],
        "requested_by": [],
        "extra": {},
    }

    def push_sentence(s: Sentence) -> int:
        n = len(cols["id"])
        cols["id"].append(s.id)
        cols["text"].append(s.text)
        cols["cite"].append(list(s.citations))
        cols["by"].append(by.intern(s.authored_by))
        cols["at"].append(at.intern(s.authored_at))
        cols["type"].append(type_.intern(s.author_type))

        standard, ctx_extra = _ctx_parts(s)
        cols["action"].append(action.intern(standard["action"]))
        cols["reason"].append(reason.intern(standard["reason"]))
        cols["trigger"].append(trigger.intern(standard["source_trigger"]))
        cols["requested_by"].append(requested_by.intern(standard["requested_by"]))

        # Preserve anything the columns above don't capture, so the encoding
        # stays lossless for documents that carry extra/non-standard fields.
        extra: dict[str, Any] = {}
        if s.meta:
            extra["meta"] = s.meta
        if s.authorship_context is not None:
            coded_ctx_present = (
                cols["action"][n] != -1
                or cols["reason"][n] != -1
                or cols["trigger"][n] != -1
                or cols["requested_by"][n] != -1
            )
            # Record ctx existence only when the coded columns wouldn't
            # otherwise imply it (so a ctx with only extra keys, or an empty
            # ctx, round-trips).
            if ctx_extra or not coded_ctx_present:
                extra["authorship_context"] = ctx_extra or {}
        if extra:
            cols["extra"][str(n)] = extra

        return n

    def strip_block(block: Block) -> dict[str, Any]:
        if isinstance(block, Paragraph):
            out: dict[str, Any] = {
                "k": "p",
                "s": [push_sentence(s) for s in block.sentences],
            }
        elif isinstance(block, ListBlock):
            out = {
                "k": "list",
                "ordered": block.ordered,
                "items": [
                    [push_sentence(s) for s in item.sentences]
                    for item in block.items
                ],
            }
        elif isinstance(block, Table):
            out = {"k": "table", "headers": block.headers, "rows": block.rows}
        elif isinstance(block, BoldHeading):
            out = {"k": "bold_heading", "text": block.text}
        elif isinstance(block, CodeBlock):
            out = {"k": "code", "text": block.text}
            if block.language:
                out["language"] = block.language
        elif isinstance(block, MathBlock):
            standard, ctx_extra = _ctx_parts(block)
            out = {
                "k": "math",
                "latex": block.latex,
                "by": by.intern(block.authored_by),
                "at": at.intern(block.authored_at),
                "type": type_.intern(block.author_type),
                "action": action.intern(standard["action"]),
                "reason": reason.intern(standard["reason"]),
                "trigger": trigger.intern(standard["source_trigger"]),
                "requested_by": requested_by.intern(standard["requested_by"]),
            }
            if block.id:
                out["id"] = block.id
            if block.display is not None:
                out["display"] = block.display
            if ctx_extra:
                out["extra"] = {"authorship_context": ctx_extra}
        else:  # pragma: no cover - exhaustive over the Block union
            raise TypeError(f"unknown block type: {type(block).__name__}")
        if block.meta:
            out["meta"] = block.meta
        return out

    def strip_section(section: Section) -> dict[str, Any]:
        out: dict[str, Any] = {
            "heading": section.heading,
            "level": section.level,
            "blocks": [strip_block(b) for b in section.blocks],
            "subsections": [strip_section(s) for s in section.subsections],
        }
        if section.meta:
            out["meta"] = section.meta
        return out

    structure = [strip_section(s) for s in doc.sections]

    return {
        "$format": COLUMNAR_FORMAT,
        "$legend": _LEGEND,
        "metadata": doc.metadata,
        "sources": doc.sources,
        "dict": {
            "by": by.values,
            "at": at.values,
            "type": type_.values,
            "action": action.values,
            "reason": reason.values,
            "trigger": trigger.values,
            "requested_by": requested_by.values,
        },
        "cols": cols,
        "structure": structure,
    }


def to_columnar_json(doc: Document, *, indent: int | None = None) -> str:
    """Serialize a Document to a columnar-v1 JSON string."""
    return json.dumps(to_columnar(doc), indent=indent, ensure_ascii=False)


def from_columnar(data: dict[str, Any]) -> Document:
    """Decode a ``contextdoc/columnar-v1`` dict back into a Document."""
    fmt = data.get("$format")
    if fmt != COLUMNAR_FORMAT:
        raise ValueError(f"unsupported columnar format: {fmt!r}")

    dicts: dict[str, list[str]] = data.get("dict", {})
    cols: dict[str, Any] = data["cols"]
    extras: dict[str, dict[str, Any]] = cols.get("extra", {})

    def lookup(dict_name: str, idx: int) -> str | None:
        if idx is None or idx < 0:
            return None
        return dicts.get(dict_name, [])[idx]

    def build_ctx(
        coded: dict[str, str | None],
        ctx_extra: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        present = {k: v for k, v in coded.items() if v is not None}
        if ctx_extra is None and not present:
            return None
        return {**present, **(ctx_extra or {})}

    def build_sentence(n: int) -> dict[str, Any]:
        extra = dict(extras.get(str(n), {}))
        ctx_extra = extra.pop("authorship_context", None)
        sentence: dict[str, Any] = {
            "id": cols["id"][n],
            "text": cols["text"][n],
            "citations": cols["cite"][n],
        }
        for field, dict_name in (
            ("authored_by", "by"),
            ("authored_at", "at"),
            ("author_type", "type"),
        ):
            value = lookup(dict_name, cols[dict_name][n])
            if value is not None:
                sentence[field] = value
        coded = {
            "action": lookup("action", cols["action"][n]),
            "reason": lookup("reason", cols["reason"][n]),
            "source_trigger": lookup("trigger", cols["trigger"][n]),
            "requested_by": lookup("requested_by", cols["requested_by"][n]),
        }
        ctx = build_ctx(coded, ctx_extra)
        if ctx is not None:
            sentence["authorship_context"] = ctx
        sentence.update(extra)
        return sentence

    def build_block(block: dict[str, Any]) -> dict[str, Any]:
        kind = block["k"]
        if kind == "p":
            out: dict[str, Any] = {
                "type": "paragraph",
                "sentences": [build_sentence(n) for n in block["s"]],
            }
        elif kind == "list":
            out = {
                "type": "list",
                "ordered": block["ordered"],
                "items": [
                    {"sentences": [build_sentence(n) for n in item]}
                    for item in block["items"]
                ],
            }
        elif kind == "table":
            out = {
                "type": "table",
                "headers": block["headers"],
                "rows": block["rows"],
            }
        elif kind == "bold_heading":
            out = {"type": "bold_heading", "text": block["text"]}
        elif kind == "code":
            out = {"type": "code", "text": block["text"]}
            if "language" in block:
                out["language"] = block["language"]
        elif kind == "math":
            out = {"type": "math", "latex": block["latex"]}
            if "id" in block:
                out["id"] = block["id"]
            if "display" in block:
                out["display"] = block["display"]
            for field, dict_name in (
                ("authored_by", "by"),
                ("authored_at", "at"),
                ("author_type", "type"),
            ):
                value = lookup(dict_name, block.get(dict_name, -1))
                if value is not None:
                    out[field] = value
            coded = {
                "action": lookup("action", block.get("action", -1)),
                "reason": lookup("reason", block.get("reason", -1)),
                "source_trigger": lookup("trigger", block.get("trigger", -1)),
                "requested_by": lookup(
                    "requested_by", block.get("requested_by", -1)
                ),
            }
            ctx_extra = (block.get("extra") or {}).get("authorship_context")
            ctx = build_ctx(coded, ctx_extra)
            if ctx is not None:
                out["authorship_context"] = ctx
        else:
            raise ValueError(f"unknown columnar block kind: {kind!r}")
        if "meta" in block:
            out["meta"] = block["meta"]
        return out

    def build_section(section: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "heading": section["heading"],
            "level": section["level"],
            "blocks": [build_block(b) for b in section["blocks"]],
            "subsections": [build_section(s) for s in section["subsections"]],
        }
        if "meta" in section:
            out["meta"] = section["meta"]
        return out

    return from_dict(
        {
            "metadata": data.get("metadata", {}),
            "sources": data.get("sources", {}),
            "sections": [build_section(s) for s in data.get("structure", [])],
        }
    )


def from_columnar_json(text: str) -> Document:
    """Decode a columnar-v1 JSON string back into a Document."""
    return from_columnar(json.loads(text))
