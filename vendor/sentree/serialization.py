"""JSON serialization and deserialization for sentree documents."""

from __future__ import annotations

import json
from typing import Any

from sentree.models import Document

_SENTENCE_CORE_KEYS = {
    "id",
    "text",
    "citations",
    "meta",
    "authored_by",
    "authored_at",
    "author_type",
    "authorship_context",
}

# Optional model fields whose ``None`` value means "absent"; pruned from
# serialized output so documents stay clean and round-trip byte-stable.
_PRUNE_NONE_KEYS = {
    "authored_by",
    "authored_at",
    "author_type",
    "authorship_context",
    "language",
    "display",
    "id",
    "action",
    "reason",
    "source_trigger",
    "requested_by",
    "target_id",
    "target_path",
    "turn_summary",
}


def _collect_extra_into_meta(data: Any) -> Any:
    """Walk a raw dict tree and fold extra sentence keys into ``meta``.

    This lets ``from_json`` accept both the sentree native format and
    documents carrying non-standard sentence keys, which are collected
    into ``meta``.
    """
    if isinstance(data, dict):
        if "id" in data and "text" in data:
            meta = dict(data.get("meta", {}))
            extra_keys = set(data.keys()) - _SENTENCE_CORE_KEYS
            for key in extra_keys:
                meta[key] = data[key]
            cleaned = {k: v for k, v in data.items() if k in _SENTENCE_CORE_KEYS}
            cleaned["meta"] = meta
            return {k: _collect_extra_into_meta(v) for k, v in cleaned.items()}
        return {k: _collect_extra_into_meta(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_collect_extra_into_meta(item) for item in data]
    return data


def _flatten_meta(data: Any) -> Any:
    """Walk a serialized dict tree and inline ``meta`` keys onto the parent.

    Produces the flat format where sentence metadata fields sit
    alongside ``id`` / ``text`` / ``citations``.
    """
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k == "meta" and isinstance(v, dict):
                for mk, mv in v.items():
                    result[mk] = _flatten_meta(mv)
            else:
                result[k] = _flatten_meta(v)
        return result
    if isinstance(data, list):
        return [_flatten_meta(item) for item in data]
    return data


def to_dict(doc: Document, *, flat_meta: bool = False) -> dict[str, Any]:
    """Serialize a Document to a plain dict.

    With *flat_meta=True*, sentence metadata fields are inlined
    alongside ``id`` / ``text`` / ``citations`` instead of nested
    under a ``meta`` key.
    """
    data = doc.model_dump(mode="json")
    if flat_meta:
        data = _flatten_meta(data)
    data = _clean_output(data)
    return data


def to_json(doc: Document, *, indent: int = 2, flat_meta: bool = False) -> str:
    """Serialize a Document to a JSON string."""
    return json.dumps(
        to_dict(doc, flat_meta=flat_meta),
        indent=indent,
        ensure_ascii=False,
    )


def from_dict(data: dict[str, Any]) -> Document:
    """Deserialize a Document from a plain dict.

    Accepts the sentree native format with provenance fields directly on
    sentences; any non-standard sentence keys are automatically collected
    into ``meta``.
    """
    normalized = _collect_extra_into_meta(data)
    return Document.model_validate(normalized)


def from_json(text: str) -> Document:
    """Deserialize a Document from a JSON string."""
    return from_dict(json.loads(text))


def _clean_output(data: Any) -> Any:
    """Drop empty ``meta`` dicts and absent (``None``) optional fields."""
    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if k == "meta" and isinstance(v, dict) and not v:
                continue
            if v is None and k in _PRUNE_NONE_KEYS:
                continue
            result[k] = _clean_output(v)
        return result
    if isinstance(data, list):
        return [_clean_output(item) for item in data]
    return data
