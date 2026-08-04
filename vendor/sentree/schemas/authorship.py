"""Authorship metadata schemas for sentence-level provenance tracking."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AuthorType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"


class AuthorshipAction(str, Enum):
    """Suggested values for ``AuthorshipContext.action``."""

    INITIAL_DRAFT = "initial_draft"
    REVISION = "revision"
    FACT_UPDATE = "fact_update"
    DATA_REFRESH = "data_refresh"
    REVIEW = "review"


class SourceTrigger(str, Enum):
    """Suggested values for ``AuthorshipContext.source_trigger``."""

    MANUAL = "manual"
    SCHEDULED_SCAN = "scheduled_scan"
    TEAM_REVIEW = "team_review"
    PIPELINE_INGEST = "pipeline_ingest"


class AuthorshipContext(BaseModel):
    """Audit record capturing the intent behind an authorship event.

    An open schema: ``action``, ``reason``, ``source_trigger``, and
    ``requested_by`` are the standard keys, and any extra keys round-trip
    losslessly. ``requested_by`` names the human who asked an agent to make
    the edit, preserving human intent alongside agent authorship.
    """

    model_config = ConfigDict(extra="allow")

    action: Optional[str] = None
    reason: Optional[str] = None
    source_trigger: Optional[str] = None
    requested_by: Optional[str] = None


class Authorship(BaseModel):
    """Sentence-level provenance metadata.

    These fields live directly on provenance-bearing nodes (``Sentence``,
    ``MathBlock``); this schema groups them for typed reads and writes.
    """

    authored_by: Optional[str] = None
    author_type: Optional[str] = None
    authored_at: Optional[str] = None
    authorship_context: Optional[AuthorshipContext] = None


class EditLogEntry(BaseModel):
    """One entry in ``metadata.edit_log`` recording a document mutation.

    ``turn_summary`` is set only on the first entry of a turn (one agent
    stream or one human save) and labels the prompt that produced it.
    """

    model_config = ConfigDict(extra="allow")

    at: str
    by: str
    action: str
    target_id: Optional[str] = None
    target_path: Optional[list[str]] = None
    reason: Optional[str] = None
    requested_by: Optional[str] = None
    turn_summary: Optional[str] = None
