"""The reveal experience: six words first, then the subtext, layer by layer."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sentree import Document

from sixwords import story as story_mod


def reveal(doc: Document, console: Console, *, step: bool = True) -> None:
    """Show the story, then peel back its subtext one layer at a time."""
    sentence = story_mod.story_sentence(doc)
    title = doc.metadata.get("title", "Untitled")

    console.print()
    console.print(
        Panel(
            Text(sentence.text, style="bold", justify="center"),
            title=f"[italic]{title}[/italic]",
            padding=(2, 6),
        )
    )

    layers = [
        ("The idea in full", _render_backstory),
        ("Word by word", _render_word_choices),
        ("How it evolved", _render_drafts),
        ("The interview", _render_interview),
        ("Provenance", _render_provenance),
    ]
    for heading, render in layers:
        if not render.has_content(doc):
            continue
        if step:
            console.input(f"[dim]press enter to reveal — {heading.lower()}[/dim] ")
        console.print(f"\n[bold underline]{heading}[/bold underline]\n")
        render(doc, console)


def _layer(has_content):
    def decorate(fn):
        fn.has_content = has_content
        return fn

    return decorate


@_layer(lambda doc: bool(story_mod.story_sentence(doc).meta.get("backstory")))
def _render_backstory(doc: Document, console: Console) -> None:
    console.print(story_mod.story_sentence(doc).meta["backstory"], style="italic")


@_layer(lambda doc: bool(story_mod.story_sentence(doc).meta.get("word_choices")))
def _render_word_choices(doc: Document, console: Console) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Word")
    table.add_column("Why it earned its slot")
    table.add_column("Roads not taken")
    for choice in story_mod.story_sentence(doc).meta["word_choices"]:
        table.add_row(
            choice.get("word", ""),
            choice.get("reason", ""),
            ", ".join(choice.get("alternatives", [])),
        )
    console.print(table)


@_layer(
    lambda doc: bool(
        story_mod.story_sentence(doc).meta.get("drafts")
        or doc.metadata.get("candidates_considered")
    )
)
def _render_drafts(doc: Document, console: Console) -> None:
    drafts: list[dict[str, Any]] = story_mod.story_sentence(doc).meta.get("drafts", [])
    for i, draft in enumerate(drafts, 1):
        who = f"{draft.get('by', '?')} ({draft.get('author_type', '?')})"
        console.print(f"  {i}. [bold]{draft.get('text', '')}[/bold]  [dim]— {who}[/dim]")
        if draft.get("rationale"):
            console.print(f"     [dim italic]{draft['rationale']}[/dim italic]")
    rejected = [
        c
        for c in doc.metadata.get("candidates_considered", [])
        if not c.get("chosen") and c.get("story")
    ]
    if rejected:
        console.print("\n  [dim]Candidates that didn't make it:[/dim]")
        for c in rejected:
            console.print(f"  [dim]· {c['story']}[/dim]")


@_layer(lambda doc: bool(doc.metadata.get("interview")))
def _render_interview(doc: Document, console: Console) -> None:
    for exchange in doc.metadata["interview"]:
        console.print(f"  [bold]Q:[/bold] {exchange.get('question', '')}")
        console.print(f"  [bold]A:[/bold] {exchange.get('answer', '')}\n")


@_layer(lambda doc: True)
def _render_provenance(doc: Document, console: Console) -> None:
    sentence = story_mod.story_sentence(doc)
    edit_log = doc.metadata.get("edit_log", [])
    ctx = sentence.authorship_context
    lines = [
        f"Final words by [bold]{sentence.authored_by}[/bold] ({sentence.author_type})"
        + (f", requested by {ctx.requested_by}" if ctx and ctx.requested_by else ""),
        f"Last touched {sentence.authored_at}",
        f"Version {doc.metadata.get('version', '?')} — {len(edit_log)} recorded edits",
    ]
    for line in lines:
        console.print(f"  {line}")
