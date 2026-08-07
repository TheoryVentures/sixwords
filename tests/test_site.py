import json

from click.testing import CliRunner

from sixwords import story
from sixwords.cli import main
from sixwords.site import build_site


def _ideas():
    return [
        {
            "slug": "baby-shoes",
            "title": "Shoes",
            "story": "For sale: baby shoes, never worn.",
            "doc": {"$format": "contextdoc/nested-v1", "metadata": {"title": "Shoes"}},
            "published_at": "2026-08-04T21:35:42.874+00:00",
        }
    ]


def test_build_site_writes_index_and_json(tmp_path):
    build_site(_ideas(), tmp_path)

    index = (tmp_path / "index.html").read_text()
    assert "For sale: baby shoes, never worn." in index
    assert 'href="/ideas/baby-shoes.json"' in index
    assert "2026-08-04" in index

    published = json.loads((tmp_path / "ideas" / "baby-shoes.json").read_text())
    assert published["$format"] == "contextdoc/nested-v1"
    assert (tmp_path / "CNAME").read_text().strip() == "sixwordidea.com"
    assert (tmp_path / ".nojekyll").exists()


def test_build_site_renders_x_share_link(tmp_path):
    build_site(_ideas(), tmp_path)

    index = (tmp_path / "index.html").read_text()
    assert 'href="https://x.com/intent/post?text=' in index
    # The prefilled tweet carries the story, the @grok mention, and the subtext URL.
    assert "For%20sale%3A%20baby%20shoes%2C%20never%20worn." in index
    assert "%40grok" in index
    assert "sixwordidea.com/ideas/baby-shoes.json" in index


def test_build_site_empty(tmp_path):
    build_site([], tmp_path)
    assert "Nothing published yet" in (tmp_path / "index.html").read_text()


def test_publish_rejects_unfinalized_story(tmp_path):
    doc = story.new_story(
        title="Draft",
        text="One two three four five six.",
        authored_by="adam",
        author_type="human",
    )
    path = story.save(doc, tmp_path / "draft.subtext.json")
    result = CliRunner().invoke(main, ["publish", str(path)])
    assert result.exit_code != 0
    assert "finalized" in result.output


def test_publish_rejects_wrong_word_count(tmp_path):
    doc = story.new_story(
        title="Short",
        text="Only five words in here.",
        authored_by="adam",
        author_type="human",
    )
    story.finalize(doc, by="adam")
    path = story.save(doc, tmp_path / "short.subtext.json")
    result = CliRunner().invoke(main, ["publish", str(path)])
    assert result.exit_code != 0
    assert "exactly six words" in result.output
