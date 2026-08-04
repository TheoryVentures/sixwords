"""Command-line interface for writing and reading six-word stories."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sentree import render

from sixwords import story as story_mod
from sixwords.interview import DraftCandidate, InterviewEngine, Turn
from sixwords.reader import reveal

DEFAULT_STORIES_DIR = Path("stories")


@click.group()
def main() -> None:
    """Six words on the surface; the thinking that produced them is the subtext."""


@main.command()
@click.option("--author", default=getpass.getuser, help="Name recorded as the human author.")
@click.option(
    "--stories-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_STORIES_DIR,
    help="Directory where stories are saved.",
)
def write(author: str, stories_dir: Path) -> None:
    """Package a concept into six words with the coach."""
    console = Console()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise click.ClickException("ANTHROPIC_API_KEY is not set.")

    engine = InterviewEngine()
    console.print(
        Panel(
            "Six words on the surface, the whole idea underneath.\n"
            "Answer the coach's questions; pick a draft, edit it, or write your own. "
            "Type [bold]/quit[/bold] to abandon.",
            title="sixwords",
        )
    )

    session = _Session(engine=engine, console=console, author=author)
    with console.status("[dim]the coach is thinking…[/dim]"):
        turn = engine.start()

    while True:
        if turn.final is not None:
            path = session.finish(turn.final, stories_dir)
            if path is None:
                console.print(
                    "[red]The coach finalized without a story text; nothing to save.[/red]"
                )
                return
            console.print(f"\nSaved to [bold]{path}[/bold]")
            console.print(f"Read it back with: [bold]sixwords read {path}[/bold]")
            return

        if turn.text:
            console.print(f"\n[bold cyan]coach[/bold cyan]  {turn.text.strip()}")
        if turn.drafts:
            _show_drafts(console, turn.drafts)

        turn = session.next_turn(turn)
        if turn is None:
            console.print("[dim]Abandoned. Nothing was saved.[/dim]")
            return


class _Session:
    """Tracks the document and the subtext buffers across the write loop."""

    def __init__(self, engine: InterviewEngine, console: Console, author: str) -> None:
        self.engine = engine
        self.console = console
        self.author = author
        self.doc = None
        self.interview: list[tuple[str, str]] = []
        self.candidates: list[dict] = []
        self.pending_question: str | None = None

    def next_turn(self, turn: Turn) -> Turn | None:
        """Read the user's reaction to *turn* and advance the conversation."""
        if turn.text:
            self.pending_question = turn.text.strip()

        raw = self.console.input("\n[bold]you[/bold]  ").strip()
        if not raw:
            return self._send("(no answer)")
        if raw.lower() in ("/quit", "/q"):
            return None

        if turn.drafts and raw.isdigit() and 1 <= int(raw) <= len(turn.drafts):
            return self._pick_candidate(turn.drafts, int(raw) - 1)

        if story_mod.word_count(raw) == 6 and not raw.endswith("?"):
            if click.confirm("Treat that as your own six-word draft?", default=True):
                return self._own_draft(raw)

        if self.pending_question is not None:
            self.interview.append((self.pending_question, raw))
            self.pending_question = None
        return self._send(raw)

    def _send(self, message: str) -> Turn:
        with self.console.status("[dim]the coach is thinking…[/dim]"):
            return self.engine.send(message)

    def _pick_candidate(self, drafts: list[DraftCandidate], index: int) -> Turn | None:
        chosen = drafts[index]
        for i, candidate in enumerate(drafts):
            self.candidates.append(
                {
                    "story": candidate.story,
                    "appeal": candidate.appeal,
                    "chosen": i == index,
                }
            )
        self._apply_draft(
            chosen.story,
            by=self.engine.model,
            author_type="agent",
            rationale=chosen.appeal,
            requested_by=self.author,
        )
        story_mod.set_word_choices(self.doc, chosen.word_choices)
        return self._settle(chosen.story, f'I picked candidate {index + 1}: "{chosen.story}".')

    def _own_draft(self, text: str) -> Turn | None:
        self._apply_draft(text, by=self.author, author_type="human", rationale=None)
        return self._settle(text, f'I wrote my own six words: "{text}".')

    def _settle(self, text: str, context: str) -> Turn | None:
        """After a draft lands on the document, lock it in or keep working."""
        self.console.print(f'\nCurrent story: [bold]"{text}"[/bold]')
        if click.confirm("Lock it in as final?", default=False):
            return self._send(
                f'{context} I accept "{text}" as my final story. Call finalize_story now.'
            )
        feedback = self.console.input("[bold]what would you change?[/bold]  ").strip()
        if feedback.lower() in ("/quit", "/q"):
            return None
        return self._send(f"{context} But I want changes: {feedback}")

    def _apply_draft(
        self,
        text: str,
        *,
        by: str,
        author_type: str,
        rationale: str | None,
        requested_by: str | None = None,
    ) -> None:
        if self.doc is None:
            self.doc = story_mod.new_story(
                title="Untitled",
                text=text,
                authored_by=by,
                author_type=author_type,
                rationale=rationale,
                requested_by=requested_by,
            )
        else:
            story_mod.revise(
                self.doc,
                text,
                by=by,
                author_type=author_type,
                rationale=rationale,
                requested_by=requested_by,
            )

    def finish(self, final, stories_dir: Path) -> Path | None:
        """Apply the finalized package and save.

        The coach may finalize at any point — including when the accepted six
        words only ever existed in conversation — so this reconciles the
        document with the finalized text before saving.
        """
        if final.story:
            by, author_type = self._final_attribution(final.final_author)
            if self.doc is None:
                self._apply_draft(
                    final.story,
                    by=by,
                    author_type=author_type,
                    rationale=None,
                    requested_by=self.author if author_type == "agent" else None,
                )
            elif final.story != story_mod.story_text(self.doc):
                story_mod.revise(
                    self.doc,
                    final.story,
                    by=by,
                    author_type=author_type,
                    rationale="Final text as accepted in conversation.",
                    requested_by=self.author if author_type == "agent" else None,
                )
        if self.doc is None:
            return None

        doc = self.doc
        doc.metadata["title"] = final.title
        doc.sections[0].heading = final.title
        story_mod.set_backstory(doc, final.backstory)
        if final.word_choices:
            story_mod.set_word_choices(doc, final.word_choices)
        for question, answer in self.interview:
            story_mod.add_interview_exchange(doc, question, answer)
        story_mod.add_candidates(doc, self.candidates)
        story_mod.finalize(doc, by=self.author)
        path = story_mod.story_path(stories_dir, final.title)
        story_mod.save(doc, path)
        return self._show_saved(doc, final, path)

    def _final_attribution(self, final_author: str | None) -> tuple[str, str]:
        if final_author == "human":
            return self.author, "human"
        return self.engine.model, "agent"

    def _show_saved(self, doc, final, path: Path) -> Path:
        self.console.print()
        self.console.print(
            Panel(
                f'[bold]"{story_mod.story_text(doc)}"[/bold]',
                title=f"[italic]{final.title}[/italic]",
                padding=(1, 4),
            )
        )
        return path


def _show_drafts(console: Console, drafts: list[DraftCandidate]) -> None:
    console.print()
    for i, candidate in enumerate(drafts, 1):
        console.print(f'  [bold]{i}.[/bold]  [bold]"{candidate.story}"[/bold]')
        if candidate.appeal:
            console.print(f"      [dim italic]{candidate.appeal}[/dim italic]")
    console.print(
        "\n[dim]Pick a number, type your own six words, or say what you'd change.[/dim]"
    )


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--all", "show_all", is_flag=True, help="Reveal every layer without pausing.")
def read(file: Path, show_all: bool) -> None:
    """Read six words first, then the subtext, layer by layer."""
    console = Console()
    doc = story_mod.load(file)
    reveal(doc, console, step=not show_all)


@main.command(name="list")
@click.option(
    "--stories-dir",
    type=click.Path(path_type=Path),
    default=DEFAULT_STORIES_DIR,
    help="Directory to scan for stories.",
)
def list_stories(stories_dir: Path) -> None:
    """List saved stories."""
    console = Console()
    files = sorted(stories_dir.glob(f"*{story_mod.FILE_SUFFIX}")) if stories_dir.is_dir() else []
    if not files:
        console.print(f"[dim]No stories in {stories_dir}/ yet. Try: sixwords write[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Story")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("File")
    for path in files:
        doc = story_mod.load(path)
        table.add_row(
            story_mod.story_text(doc),
            doc.metadata.get("title", ""),
            doc.metadata.get("status", ""),
            str(path),
        )
    console.print(table)


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Write markdown here.")
def export(file: Path, output: Path | None) -> None:
    """Render the human-facing markdown (just the surface text)."""
    doc = story_mod.load(file)
    # The section heading already carries the title; dropping metadata.title
    # keeps the renderer from emitting the H1 twice.
    doc.metadata.pop("title", None)
    markdown = render(doc)
    if output:
        output.write_text(markdown, encoding="utf-8")
        click.echo(f"Wrote {output}")
    else:
        click.echo(markdown)


if __name__ == "__main__":
    main()
