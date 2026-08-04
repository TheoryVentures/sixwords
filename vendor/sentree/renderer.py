"""Render a sentree Document back to Markdown text."""

from __future__ import annotations

import re
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
    Table,
)

_TRAILING_PUNCT_RE = re.compile(r"([.!?]+)$")


def _source_url(src: Any) -> str | None:
    """Resolve a sources-map value (URL string or info dict) to a URL."""
    if isinstance(src, str):
        return src or None
    if isinstance(src, dict):
        url = src.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _format_citations(citations: list[str], sources: dict[str, Any]) -> str:
    parts = []
    for cid in citations:
        url = _source_url(sources.get(cid))
        if url:
            parts.append(f"[[{cid}]]({url})")
        else:
            parts.append(f"[[{cid}]]")
    return ", ".join(parts)


def _render_sentences(sentences: list, sources: dict[str, Any]) -> str:
    parts = []
    for s in sentences:
        text = s.text
        if s.citations:
            cit_str = _format_citations(s.citations, sources)
            m = _TRAILING_PUNCT_RE.search(text)
            if m:
                text = text[: m.start()] + " " + cit_str + m.group()
            else:
                text = text + " " + cit_str
        parts.append(text)
    return " ".join(parts)


def _render_block(block: Block, sources: dict[str, Any]) -> str:
    if isinstance(block, Paragraph):
        return _render_sentences(block.sentences, sources)

    if isinstance(block, BoldHeading):
        return f"**{block.text}**"

    if isinstance(block, ListBlock):
        lines: list[str] = []
        for i, item in enumerate(block.items):
            text = _render_sentences(item.sentences, sources)
            prefix = f"{i + 1}." if block.ordered else "-"
            lines.append(f"{prefix} {text}")
        return "\n".join(lines)

    if isinstance(block, Table):
        if not block.headers:
            return ""
        header_line = "| " + " | ".join(block.headers) + " |"
        sep_line = "| " + " | ".join("---" for _ in block.headers) + " |"
        data_lines: list[str] = []
        for row in block.rows:
            cells = [row.get(h, "") for h in block.headers]
            data_lines.append("| " + " | ".join(cells) + " |")
        return "\n".join([header_line, sep_line, *data_lines])

    if isinstance(block, CodeBlock):
        fence_info = block.language or ""
        return f"```{fence_info}\n{block.text}\n```"

    if isinstance(block, MathBlock):
        return f"$$\n{block.latex.strip()}\n$$"

    return ""


def _render_section(section: Section, sources: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    prefix = "#" * section.level
    lines.append(f"{prefix} {section.heading}")
    lines.append("")

    for block in section.blocks:
        rendered = _render_block(block, sources)
        if rendered:
            lines.append(rendered)
            lines.append("")

    for sub in section.subsections:
        lines.extend(_render_section(sub, sources))

    return lines


def render(doc: Document) -> str:
    """Render a sentree Document back to a Markdown string."""
    source_markdown = doc.metadata.get("_source_markdown")
    if isinstance(source_markdown, str):
        return source_markdown

    parts: list[str] = []
    sources = doc.sources or {}

    title = doc.metadata.get("title")
    if title:
        parts.append(f"# {title}")
        parts.append("")

    for i, section in enumerate(doc.sections):
        if i > 0:
            parts.append("----")
            parts.append("")
        parts.extend(_render_section(section, sources))

    return "\n".join(parts).rstrip() + "\n"
