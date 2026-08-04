from types import SimpleNamespace

from click.testing import CliRunner
from rich.console import Console

from sixwords import story
from sixwords.cli import _Session, main
from sixwords.interview import FinalStory


def _write_story(directory):
    doc = story.new_story(
        title="Shoes",
        text="For sale: baby shoes, never worn.",
        authored_by="claude-sonnet-5",
        author_type="agent",
        requested_by="adam",
    )
    story.set_backstory(doc, "The nursery stayed painted for a year.")
    story.add_interview_exchange(doc, "What happened?", "We lost the baby.")
    story.finalize(doc, by="adam")
    return story.save(doc, directory / "shoes.subtext.json")


def test_list_shows_saved_story(tmp_path):
    _write_story(tmp_path)
    result = CliRunner().invoke(main, ["list", "--stories-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "For sale: baby shoes," in result.output
    assert "final" in result.output


def test_list_empty_dir(tmp_path):
    result = CliRunner().invoke(main, ["list", "--stories-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No stories" in result.output


def test_export_renders_surface_markdown(tmp_path):
    path = _write_story(tmp_path)
    result = CliRunner().invoke(main, ["export", str(path)])
    assert result.exit_code == 0
    assert "For sale: baby shoes, never worn." in result.output
    assert "backstory" not in result.output


def test_read_all_reveals_subtext(tmp_path):
    path = _write_story(tmp_path)
    result = CliRunner().invoke(main, ["read", str(path), "--all"])
    assert result.exit_code == 0
    assert "For sale: baby shoes," in result.output
    assert "nursery" in result.output
    assert "We lost the baby." in result.output


def _session():
    return _Session(
        engine=SimpleNamespace(model="test-model"),
        console=Console(file=None, quiet=True),
        author="adam",
    )


def _final(story_text, final_author):
    return FinalStory(
        title="Struggle",
        backstory="Skipping the struggle skips the skill.",
        word_choices=[{"word": "struggle", "reason": "the whole process"}],
        story=story_text,
        final_author=final_author,
    )


def test_finish_recovers_when_no_draft_was_applied(tmp_path):
    """The coach may finalize words that only ever existed in conversation."""
    session = _session()
    path = session.finish(_final("Skipping the struggle skips the skill.", "human"), tmp_path)
    assert path is not None

    doc = story.load(path)
    sentence = story.story_sentence(doc)
    assert sentence.text == "Skipping the struggle skips the skill."
    assert sentence.authored_by == "adam"
    assert sentence.author_type == "human"
    assert doc.metadata["status"] == "final"


def test_finish_reconciles_document_with_finalized_text(tmp_path):
    session = _session()
    session._apply_draft(
        "AI finds features; humans find problems.",
        by="test-model",
        author_type="agent",
        rationale=None,
        requested_by="adam",
    )
    path = session.finish(_final("Skipping the struggle skips the skill.", "mixed"), tmp_path)

    doc = story.load(path)
    sentence = story.story_sentence(doc)
    assert sentence.text == "Skipping the struggle skips the skill."
    assert sentence.authored_by == "test-model"
    drafts = [d["text"] for d in sentence.meta["drafts"]]
    assert drafts == [
        "AI finds features; humans find problems.",
        "Skipping the struggle skips the skill.",
    ]


def test_finish_returns_none_without_story_or_document(tmp_path):
    session = _session()
    assert session.finish(_final(None, None), tmp_path) is None
