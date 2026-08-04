"""Pydantic models for the sentree document tree."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Iterator, Literal, TypeVar

from pydantic import BaseModel, Discriminator, Field, Tag, field_validator

from sentree.schemas.authorship import AuthorshipContext, EditLogEntry

T = TypeVar("T", bound=BaseModel)

_ID_RE = re.compile(r"^s-(\d+)$")
_BLOCK_ID_RE = re.compile(r"^b-(\d+)$")

_UNICODE_NORMALIZE = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00a0": " ",
})


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Base with metadata support
# ---------------------------------------------------------------------------


class Node(BaseModel):
    """Base for any tree node that can carry user-defined metadata."""

    meta: dict[str, Any] = Field(default_factory=dict)

    def set_meta(self, schema: BaseModel) -> None:
        """Merge a typed Pydantic model's fields into this node's meta dict."""
        self.meta.update(schema.model_dump(mode="python"))

    def get_meta(self, schema_type: type[T]) -> T:
        """Read this node's meta dict as a typed Pydantic model."""
        return schema_type.model_validate(self.meta)


# ---------------------------------------------------------------------------
# Sentence — the atomic unit
# ---------------------------------------------------------------------------


class Sentence(Node):
    """A single sentence with an ID, text, citation refs, and provenance."""

    id: str
    text: str
    citations: list[str] = Field(default_factory=list)
    authored_by: str | None = None
    authored_at: str | None = None
    author_type: str | None = None
    authorship_context: AuthorshipContext | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_text(cls, v: str) -> str:
        if isinstance(v, str):
            return v.translate(_UNICODE_NORMALIZE)
        return v


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------


class Paragraph(Node):
    """A paragraph of prose, split into sentences."""

    type: Literal["paragraph"] = "paragraph"
    sentences: list[Sentence]


class ListItem(Node):
    """A single item within a list block."""

    sentences: list[Sentence]


class ListBlock(Node):
    """An ordered or unordered list of items, each containing sentences."""

    type: Literal["list"] = "list"
    ordered: bool = False
    items: list[ListItem]

    @property
    def sentences(self) -> list[Sentence]:
        return [s for item in self.items for s in item.sentences]


class Table(Node):
    """A data table with named columns."""

    type: Literal["table"] = "table"
    headers: list[str]
    rows: list[dict[str, str]]

    @property
    def sentences(self) -> list[Sentence]:
        return []


class BoldHeading(Node):
    """A bold sub-heading used to label groups within a section."""

    type: Literal["bold_heading"] = "bold_heading"
    text: str

    @property
    def sentences(self) -> list[Sentence]:
        return []


class CodeBlock(Node):
    """A fenced or indented code block with an optional language."""

    type: Literal["code"] = "code"
    text: str
    language: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _accept_legacy_type(cls, v: Any) -> Any:
        return "code" if v == "code_block" else v

    @property
    def sentences(self) -> list[Sentence]:
        return []


class MathBlock(Node):
    """A display LaTeX equation — a provenance-bearing unit like a sentence.

    Carries a stable ``b-NNNN`` id (parallel to a sentence's ``s-NNNN``) and
    the same authorship fields a sentence has.
    """

    type: Literal["math"] = "math"
    id: str | None = None
    latex: str
    display: bool | None = None
    authored_by: str | None = None
    authored_at: str | None = None
    author_type: str | None = None
    authorship_context: AuthorshipContext | None = None

    @property
    def sentences(self) -> list[Sentence]:
        return []


def _block_discriminator(v: Any) -> str | None:
    t = v.get("type") if isinstance(v, dict) else getattr(v, "type", None)
    return "code" if t == "code_block" else t


Block = Annotated[
    Annotated[Paragraph, Tag("paragraph")]
    | Annotated[ListBlock, Tag("list")]
    | Annotated[Table, Tag("table")]
    | Annotated[BoldHeading, Tag("bold_heading")]
    | Annotated[CodeBlock, Tag("code")]
    | Annotated[MathBlock, Tag("math")],
    Discriminator(_block_discriminator),
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SentenceNotFoundError(KeyError):
    """Raised when a sentence ID does not exist in the document."""


# ---------------------------------------------------------------------------
# Internal context for mutations
# ---------------------------------------------------------------------------


@dataclass
class _SentenceContext:
    sentence: Sentence
    sentences_list: list[Sentence]
    block: Paragraph | ListBlock
    blocks_list: list  # list[Block] — typed loosely to avoid forward ref issues
    list_item: ListItem | None = None


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


class Section(Node):
    """A document section defined by a heading, containing blocks and subsections."""

    heading: str
    level: int
    blocks: list[Block] = Field(default_factory=list)
    subsections: list[Section] = Field(default_factory=list)

    def walk_sentences(self) -> Iterator[Sentence]:
        """Yield every sentence in this section and its subsections."""
        for block in self.blocks:
            yield from block.sentences
        for sub in self.subsections:
            yield from sub.walk_sentences()

    def walk_blocks(self) -> Iterator[Block]:
        """Yield every block in this section and its subsections, in order."""
        yield from self.blocks
        for sub in self.subsections:
            yield from sub.walk_blocks()


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class Document(Node):
    """Root of the sentree document tree."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, Any] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list)

    def walk_sentences(self) -> Iterator[Sentence]:
        """Yield every sentence in the document in order."""
        for section in self.sections:
            yield from section.walk_sentences()

    def walk_blocks(self) -> Iterator[Block]:
        """Yield every block in the document in reading order."""
        for section in self.sections:
            yield from section.walk_blocks()

    def get_sentence(self, sentence_id: str) -> Sentence | None:
        """Look up a sentence by ID, or return None."""
        for s in self.walk_sentences():
            if s.id == sentence_id:
                return s
        return None

    def sentence_count(self) -> int:
        """Total number of sentences in the document."""
        return sum(1 for _ in self.walk_sentences())

    # ------------------------------------------------------------------
    # Edit log
    # ------------------------------------------------------------------

    def record_edit(
        self,
        action: str,
        *,
        by: str,
        at: str | None = None,
        target_id: str | None = None,
        target_path: list[str] | None = None,
        reason: str | None = None,
        requested_by: str | None = None,
        turn_summary: str | None = None,
    ) -> EditLogEntry:
        """Append an entry to ``metadata.edit_log``.

        Also sets ``metadata.last_edited_at`` and bumps ``metadata.version``.
        """
        self._clear_source_markdown()
        entry = EditLogEntry(
            at=at or _now_iso(),
            by=by,
            action=action,
            target_id=target_id,
            target_path=target_path,
            reason=reason,
            requested_by=requested_by,
            turn_summary=turn_summary,
        )
        log = self.metadata.get("edit_log")
        if not isinstance(log, list):
            log = []
        self.metadata["edit_log"] = [
            *log,
            entry.model_dump(mode="json", exclude_none=True),
        ]
        self.metadata["last_edited_at"] = entry.at
        prev = self.metadata.get("version")
        if isinstance(prev, (int, float)) and not isinstance(prev, bool):
            version = int(prev)
        elif isinstance(prev, str):
            try:
                version = int(float(prev))
            except ValueError:
                version = 0
        else:
            version = 0
        self.metadata["version"] = version + 1
        return entry

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def update_sentence(
        self,
        sentence_id: str,
        *,
        text: str | None = None,
        citations: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        authored_by: str | None = None,
        author_type: str | None = None,
        action: str = "revise",
        reason: str | None = None,
        requested_by: str | None = None,
        at: str | None = None,
    ) -> Sentence:
        """Update an existing sentence's text, citations, or metadata.

        When *authored_by* is given, the sentence is stamped with full
        provenance (author, timestamp, context) and the edit is appended to
        ``metadata.edit_log``.
        """
        sentence = self.get_sentence(sentence_id)
        if sentence is None:
            raise SentenceNotFoundError(sentence_id)
        self._clear_source_markdown()
        if text is not None:
            sentence.text = text
        if citations is not None:
            sentence.citations = citations
        if meta is not None:
            sentence.meta.update(meta)
        if authored_by is not None:
            self._stamp_provenance(
                sentence,
                authored_by=authored_by,
                author_type=author_type,
                action=action,
                reason=reason,
                requested_by=requested_by,
                at=at,
            )
            self.record_edit(
                "edit_sentence",
                by=authored_by,
                at=sentence.authored_at,
                target_id=sentence_id,
                reason=reason,
                requested_by=requested_by,
            )
        return sentence

    def insert_after(
        self,
        sentence_id: str,
        text: str,
        *,
        citations: list[str] | None = None,
        meta: dict[str, Any] | None = None,
        authored_by: str | None = None,
        author_type: str | None = None,
        action: str = "insert",
        reason: str | None = None,
        requested_by: str | None = None,
        at: str | None = None,
    ) -> Sentence:
        """Insert a new sentence immediately after *sentence_id*.

        When *authored_by* is given, the new sentence is stamped with full
        provenance and the edit is appended to ``metadata.edit_log``.
        """
        ctx = self._find_context(sentence_id)
        self._clear_source_markdown()
        new_id = self._next_id()
        new_sentence = Sentence(
            id=new_id,
            text=text,
            citations=citations or [],
            meta=meta or {},
        )
        if authored_by is not None:
            self._stamp_provenance(
                new_sentence,
                authored_by=authored_by,
                author_type=author_type,
                action=action,
                reason=reason,
                requested_by=requested_by,
                at=at,
            )
        idx = ctx.sentences_list.index(ctx.sentence)
        ctx.sentences_list.insert(idx + 1, new_sentence)
        if authored_by is not None:
            self.record_edit(
                "insert_sentence",
                by=authored_by,
                at=new_sentence.authored_at,
                target_id=new_id,
                reason=reason,
                requested_by=requested_by,
            )
        return new_sentence

    def delete_sentence(
        self,
        sentence_id: str,
        *,
        by: str | None = None,
        reason: str | None = None,
        requested_by: str | None = None,
        at: str | None = None,
    ) -> Sentence:
        """Remove a sentence by ID, cleaning up empty containers.

        When *by* is given, the deletion is appended to ``metadata.edit_log``.
        """
        ctx = self._find_context(sentence_id)
        self._clear_source_markdown()
        ctx.sentences_list.remove(ctx.sentence)

        if not ctx.sentences_list:
            if isinstance(ctx.block, ListBlock) and ctx.list_item is not None:
                ctx.block.items.remove(ctx.list_item)
                if not ctx.block.items:
                    ctx.blocks_list.remove(ctx.block)
            elif isinstance(ctx.block, Paragraph):
                ctx.blocks_list.remove(ctx.block)

        if by is not None:
            self.record_edit(
                "delete_sentence",
                by=by,
                at=at,
                target_id=sentence_id,
                reason=reason,
                requested_by=requested_by,
            )
        return ctx.sentence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_source_markdown(self) -> None:
        self.metadata.pop("_source_markdown", None)

    @staticmethod
    def _stamp_provenance(
        node: Sentence | MathBlock,
        *,
        authored_by: str,
        author_type: str | None,
        action: str,
        reason: str | None,
        requested_by: str | None,
        at: str | None,
    ) -> None:
        """Stamp a provenance-bearing node with author, timestamp, and context."""
        node.authored_by = authored_by
        node.authored_at = at or _now_iso()
        if author_type is not None:
            node.author_type = author_type
        existing = node.authorship_context
        data = existing.model_dump(mode="python") if existing else {}
        data["action"] = action
        if reason is not None:
            data["reason"] = reason
        if requested_by is not None:
            data["requested_by"] = requested_by
        else:
            data.pop("requested_by", None)
        node.authorship_context = AuthorshipContext.model_validate(
            {k: v for k, v in data.items() if v is not None}
        )

    def _next_id(self) -> str:
        """Return the next sequential sentence ID."""
        max_n = 0
        for s in self.walk_sentences():
            m = _ID_RE.match(s.id)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"s-{max_n + 1:04d}"

    def _next_block_id(self) -> str:
        """Return the next sequential block ID (used by math blocks)."""
        max_n = 0
        for block in self.walk_blocks():
            block_id = getattr(block, "id", None)
            if isinstance(block_id, str):
                m = _BLOCK_ID_RE.match(block_id)
                if m:
                    max_n = max(max_n, int(m.group(1)))
        return f"b-{max_n + 1:04d}"

    def _find_context(self, sentence_id: str) -> _SentenceContext:
        """Locate a sentence and its parent containers."""
        for ctx in self._walk_contexts():
            if ctx.sentence.id == sentence_id:
                return ctx
        raise SentenceNotFoundError(sentence_id)

    def _walk_contexts(self) -> Iterator[_SentenceContext]:
        """Yield a ``_SentenceContext`` for every sentence in the tree."""
        for section in self.sections:
            yield from self._section_contexts(section)

    def _section_contexts(self, section: Section) -> Iterator[_SentenceContext]:
        for block in section.blocks:
            if isinstance(block, Paragraph):
                for s in block.sentences:
                    yield _SentenceContext(
                        sentence=s,
                        sentences_list=block.sentences,
                        block=block,
                        blocks_list=section.blocks,
                    )
            elif isinstance(block, ListBlock):
                for item in block.items:
                    for s in item.sentences:
                        yield _SentenceContext(
                            sentence=s,
                            sentences_list=item.sentences,
                            block=block,
                            blocks_list=section.blocks,
                            list_item=item,
                        )
        for sub in section.subsections:
            yield from self._section_contexts(sub)
