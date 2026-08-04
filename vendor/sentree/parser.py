"""Parse Markdown text into a sentree Document."""

from __future__ import annotations

import re
from typing import Any

import marko
from marko.ext.gfm import GFM

from sentree.models import (
    BoldHeading,
    CodeBlock,
    Document,
    ListBlock,
    ListItem,
    MathBlock,
    Paragraph,
    Section,
    Sentence,
    Table,
)
from sentree.tokenizer import sent_tokenize

# ---------------------------------------------------------------------------
# Citation markers
# ---------------------------------------------------------------------------

_CIT_FMT = "\x01CIT:{}\x01"
_CIT_RE = re.compile(r"\x01CIT:([\w-]+)\x01")

_collected_sources: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Display math extraction
# ---------------------------------------------------------------------------

_MATH_FMT = "\x01MATH:{}\x01"
_MATH_RE = re.compile(r"^\x01MATH:(\d+)\x01$")

_collected_math: list[str] = []


def _extract_math(markdown: str) -> str:
    """Replace ``$$ … $$`` display-math blocks with placeholder paragraphs.

    The LaTeX source is collected into ``_collected_math`` verbatim, keeping
    it out of the Markdown parser's reach (so underscores and asterisks in
    equations survive untouched).
    """
    lines = markdown.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        trimmed = lines[i].strip()
        if trimmed.startswith("$$"):
            if len(trimmed) > 2 and trimmed.endswith("$$"):
                latex = trimmed[2:-2].strip()
            else:
                math_lines: list[str] = []
                first_rest = trimmed[2:]
                if first_rest.strip():
                    math_lines.append(first_rest)
                i += 1
                while i < len(lines):
                    lt = lines[i].strip()
                    if lt.endswith("$$"):
                        before = lt[: len(lt) - 2]
                        if before.strip():
                            math_lines.append(before)
                        break
                    math_lines.append(lines[i])
                    i += 1
                latex = "\n".join(math_lines).strip()
            _collected_math.append(latex)
            out.extend(["", _MATH_FMT.format(len(_collected_math) - 1), ""])
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Inline text extraction
# ---------------------------------------------------------------------------


def _inline(node: Any) -> str:
    name = type(node).__name__

    if name == "RawText":
        t = node.children if isinstance(node.children, str) else ""
        return re.sub(r"\[\[([\w-]+)\]\]", lambda m: _CIT_FMT.format(m.group(1)), t)

    if name in ("LineBreak", "SoftBreak"):
        return " "

    if name == "StrongEmphasis":
        return f"**{_children_text(node)}**"

    if name == "Emphasis":
        return f"*{_children_text(node)}*"

    if name == "CodeSpan":
        c = getattr(node, "children", "")
        code = c if isinstance(c, str) else ""
        return f"`{code}`"

    if name == "Link":
        ct = _children_text(node)
        m = re.match(r"^\[([\w-]+)\]$", ct)
        if m:
            cit_id = m.group(1)
            dest = getattr(node, "dest", "")
            if dest:
                _collected_sources[cit_id] = dest
            return _CIT_FMT.format(cit_id)
        dest = getattr(node, "dest", "")
        if dest:
            return f"[{ct}]({dest})"
        return ct

    if name == "Image":
        return getattr(node, "title", "") or _children_text(node)

    return _children_text(node)


def _children_text(node: Any) -> str:
    c = getattr(node, "children", None)
    if isinstance(c, str):
        return c
    if c:
        return "".join(_inline(child) for child in c)
    return ""


def _block_text(node: Any) -> str:
    return _children_text(node)


# ---------------------------------------------------------------------------
# Sentence construction
# ---------------------------------------------------------------------------


def _clean_sentence(text: str) -> str:
    text = re.sub(r"\([\s,]*\)", "", text)
    text = re.sub(r"\[[\s,]*\]", "", text)
    text = re.sub(r"(\s*,)+\s*(?=[;.!?])", "", text)
    text = re.sub(r"\s+([;.!?])", r"\1", text)
    text = re.sub(r"(\s*,\s*)+$", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _make_sentences(marked: str, counter: dict[str, int]) -> list[Sentence]:
    parts = sent_tokenize(marked)
    out: list[Sentence] = []
    for raw in parts:
        citation_ids = _CIT_RE.findall(raw)
        clean = _CIT_RE.sub("", raw)
        clean = _clean_sentence(clean)
        if not clean:
            continue
        counter["n"] += 1
        out.append(
            Sentence(
                id=f"s-{counter['n']:04d}",
                text=clean,
                citations=citation_ids,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Block detection helpers
# ---------------------------------------------------------------------------


def _is_bold_heading(node: Any) -> bool:
    if type(node).__name__ != "Paragraph":
        return False
    c = getattr(node, "children", None)
    if isinstance(c, str) or not c:
        return False
    real = [x for x in c if type(x).__name__ not in ("SoftBreak", "LineBreak")]
    if len(real) != 1 or type(real[0]).__name__ != "StrongEmphasis":
        return False
    return _children_text(real[0]).rstrip().endswith(":")


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


def _parse_table(node: Any) -> Table:
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for row_node in getattr(node, "children", []):
        if type(row_node).__name__ != "TableRow":
            continue
        is_header = False
        cells: list[str] = []
        for cell_node in getattr(row_node, "children", []):
            cells.append(_children_text(cell_node).strip())
            if getattr(cell_node, "header", False):
                is_header = True
        if is_header and not headers:
            headers = cells
        else:
            row_dict: dict[str, str] = {}
            for i, val in enumerate(cells):
                row_dict[headers[i] if i < len(headers) else f"col_{i}"] = val
            rows.append(row_dict)
    return Table(headers=headers, rows=rows)


# ---------------------------------------------------------------------------
# Block conversion
# ---------------------------------------------------------------------------


def _convert_block(
    node: Any,
    counter: dict[str, int],
) -> Paragraph | ListBlock | Table | BoldHeading | CodeBlock | MathBlock | None:
    name = type(node).__name__

    if name in ("BlankLine", "ThematicBreak"):
        return None

    if name == "Table":
        return _parse_table(node)

    if name == "Paragraph":
        math_match = _MATH_RE.match(_block_text(node).strip())
        if math_match:
            counter["b"] += 1
            return MathBlock(
                id=f"b-{counter['b']:04d}",
                latex=_collected_math[int(math_match.group(1))],
                display=True,
            )

        if _is_bold_heading(node):
            real = [
                x
                for x in getattr(node, "children", [])
                if type(x).__name__ not in ("SoftBreak", "LineBreak")
            ]
            return BoldHeading(text=_children_text(real[0]).strip())

        marked = _block_text(node)
        sentences = _make_sentences(marked, counter)
        return Paragraph(sentences=sentences) if sentences else None

    if name == "List":
        items: list[ListItem] = []
        ordered = bool(getattr(node, "ordered", False))
        for li in getattr(node, "children", []):
            if type(li).__name__ != "ListItem":
                continue
            parts: list[str] = []
            for child in getattr(li, "children", []):
                cn = type(child).__name__
                if cn == "Paragraph":
                    parts.append(_block_text(child))
                elif cn == "List":
                    for nested_item in getattr(child, "children", []):
                        for nested_child in getattr(nested_item, "children", []):
                            if type(nested_child).__name__ == "Paragraph":
                                parts.append(_block_text(nested_child))
            full = " ".join(parts)
            sentences = _make_sentences(full, counter)
            if sentences:
                items.append(ListItem(sentences=sentences))
        return ListBlock(ordered=ordered, items=items) if items else None

    if name in ("FencedCode", "CodeBlock"):
        language = getattr(node, "lang", "") or None
        c = getattr(node, "children", "")
        if isinstance(c, str):
            return CodeBlock(text=c, language=language)
        if isinstance(c, list):
            text = "".join(
                child.children if isinstance(getattr(child, "children", None), str) else ""
                for child in c
            )
            return CodeBlock(text=text, language=language) if text else None
        return None

    if name == "Heading":
        return None

    marked = _block_text(node)
    if marked.strip():
        sentences = _make_sentences(marked, counter)
        return Paragraph(sentences=sentences) if sentences else None

    return None


# ---------------------------------------------------------------------------
# Section grouping
# ---------------------------------------------------------------------------


def _build_section(
    heading_node: Any,
    content_nodes: list[Any],
    level: int,
    counter: dict[str, int],
) -> Section:
    sub_level = level + 1
    first_sub = next(
        (
            i
            for i, n in enumerate(content_nodes)
            if type(n).__name__ == "Heading"
            and getattr(n, "level", 0) == sub_level
        ),
        None,
    )
    direct = content_nodes[:first_sub] if first_sub is not None else content_nodes
    sub_nodes = content_nodes[first_sub:] if first_sub is not None else []

    blocks: list[Any] = []
    for node in direct:
        block = _convert_block(node, counter)
        if block is not None:
            blocks.append(block)

    subsections = (
        _group_sections(sub_nodes, sub_level, counter) if sub_nodes else []
    )

    return Section(
        heading=_children_text(heading_node).strip(),
        level=level,
        blocks=blocks,
        subsections=subsections,
    )


def _group_sections(
    nodes: list[Any],
    level: int,
    counter: dict[str, int],
) -> list[Section]:
    sections: list[Section] = []
    current_heading: Any = None
    current_content: list[Any] = []

    for node in nodes:
        if (
            type(node).__name__ == "Heading"
            and getattr(node, "level", 0) == level
        ):
            if current_heading is not None:
                sections.append(
                    _build_section(current_heading, current_content, level, counter)
                )
            current_heading = node
            current_content = []
        elif current_heading is not None:
            current_content.append(node)

    if current_heading is not None:
        sections.append(
            _build_section(current_heading, current_content, level, counter)
        )

    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(markdown: str) -> Document:
    """Parse a Markdown string into a sentree Document.

    Headings become sections. Paragraphs and lists are split into
    individual sentences. ``[[ref-id]]`` markers are extracted as
    citation references. ``$$ … $$`` blocks become display math blocks
    with stable ``b-NNNN`` ids.
    """
    _collected_sources.clear()
    _collected_math.clear()

    md_parser = marko.Markdown(extensions=[GFM])
    tree = md_parser.parse(_extract_math(markdown))
    children = list(getattr(tree, "children", []))

    h1_indices = [
        i
        for i, n in enumerate(children)
        if type(n).__name__ == "Heading" and n.level == 1
    ]

    metadata: dict[str, Any] = {}
    if h1_indices:
        title_idx = h1_indices[0]
        metadata["title"] = _children_text(children[title_idx]).strip()
    metadata["_source_markdown"] = markdown

    counter: dict[str, int] = {"n": 0, "b": 0}

    body = children[h1_indices[0] + 1 :] if h1_indices else children
    heading_levels = [
        getattr(n, "level", 0)
        for n in body
        if type(n).__name__ == "Heading"
    ]

    if heading_levels:
        min_level = min(heading_levels)
        first_at_level = next(
            i
            for i, n in enumerate(body)
            if type(n).__name__ == "Heading"
            and getattr(n, "level", 0) == min_level
        )
        sections = _group_sections(body[first_at_level:], min_level, counter)
    else:
        blocks = []
        for node in body:
            if type(node).__name__ == "Heading":
                continue
            block = _convert_block(node, counter)
            if block is not None:
                blocks.append(block)
        if blocks:
            sections = [
                Section(
                    heading=metadata.get("title", ""),
                    level=1,
                    blocks=blocks,
                )
            ]
        else:
            sections = []

    return Document(
        metadata=metadata,
        sources=dict(_collected_sources),
        sections=sections,
    )
