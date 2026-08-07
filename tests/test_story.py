import json

from sentree import render

from sixwords import story


def _make_story():
    return story.new_story(
        title="Untitled",
        text="For sale: baby shoes, never worn.",
        authored_by="claude-sonnet-5",
        author_type="agent",
        rationale="Classic compression of loss into commerce.",
        requested_by="adam",
    )


def test_new_story_provenance_and_edit_log():
    doc = _make_story()
    sentence = story.story_sentence(doc)
    assert sentence.text == "For sale: baby shoes, never worn."
    assert sentence.authored_by == "claude-sonnet-5"
    assert sentence.author_type == "agent"
    assert sentence.meta["drafts"][0]["text"] == sentence.text

    log = doc.metadata["edit_log"]
    assert len(log) == 1
    assert log[0]["action"] == "create_story"
    assert log[0]["requested_by"] == "adam"
    assert doc.metadata["version"] == 1


def test_revise_appends_draft_and_stamps_provenance():
    doc = _make_story()
    story.revise(
        doc,
        "For sale: crib, assembly interrupted forever.",
        by="adam",
        author_type="human",
        rationale="Wanted my own image.",
    )
    sentence = story.story_sentence(doc)
    assert sentence.text == "For sale: crib, assembly interrupted forever."
    assert sentence.authored_by == "adam"
    assert sentence.author_type == "human"
    assert [d["text"] for d in sentence.meta["drafts"]] == [
        "For sale: baby shoes, never worn.",
        "For sale: crib, assembly interrupted forever.",
    ]
    assert doc.metadata["edit_log"][-1]["action"] == "edit_sentence"


def test_save_load_round_trip(tmp_path):
    doc = _make_story()
    story.set_backstory(doc, "The nursery stayed painted for a year.")
    story.set_word_choices(
        doc, [{"word": "sale", "reason": "commerce as grief", "alternatives": ["offer"]}]
    )
    story.add_interview_exchange(doc, "What happened?", "We lost the baby.")
    story.add_candidates(
        doc, [{"story": "Nursery repainted. Nobody talks about it.", "chosen": False}]
    )
    story.finalize(doc, by="adam")

    path = story.save(doc, tmp_path / "shoes.subtext.json")
    raw = json.loads(path.read_text())
    assert raw["$format"] == story.FORMAT
    assert "$legend" in raw
    assert "author's tone" in raw["$legend"]["voice"]

    loaded = story.load(path)
    sentence = story.story_sentence(loaded)
    assert sentence.text == "For sale: baby shoes, never worn."
    assert sentence.meta["backstory"] == "The nursery stayed painted for a year."
    assert sentence.meta["word_choices"][0]["word"] == "sale"
    assert loaded.metadata["interview"][0]["answer"] == "We lost the baby."
    assert loaded.metadata["candidates_considered"][0]["chosen"] is False
    assert loaded.metadata["status"] == "final"
    assert loaded.metadata["edit_log"][-1]["action"] == "finalize_story"


def test_rendered_markdown_is_only_the_surface():
    doc = _make_story()
    doc.metadata["title"] = "Shoes"
    doc.sections[0].heading = "Shoes"
    markdown = render(doc)
    assert "For sale: baby shoes, never worn." in markdown
    assert "Shoes" in markdown
    assert "backstory" not in markdown


def test_word_count_and_slugify():
    assert story.word_count("For sale: baby shoes, never worn.") == 6
    assert story.slugify("Baby Shoes!") == "baby-shoes"
    assert story.slugify("???") == "story"


def test_story_path_does_not_clobber(tmp_path):
    first = story.story_path(tmp_path, "Shoes")
    first.write_text("{}")
    second = story.story_path(tmp_path, "Shoes")
    assert first.name == "shoes.subtext.json"
    assert second.name == "shoes-2.subtext.json"
