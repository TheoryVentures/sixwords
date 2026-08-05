"""Static site generation for sixwordidea.com.

The site has one human-facing surface — the index of idea cards — and one
agent-facing surface: each card links to the idea's raw subtext JSON at
``/ideas/<slug>.json``, a plain URL that agents can fetch with no headers
or keys.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

SITE_DOMAIN = "sixwordidea.com"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_site(ideas: list[dict[str, Any]], output_dir: Path) -> Path:
    """Render the full static site for *ideas* into *output_dir*."""
    ideas_dir = output_dir / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)

    for idea in ideas:
        payload = json.dumps(idea["doc"], indent=2, ensure_ascii=False) + "\n"
        (ideas_dir / f"{idea['slug']}.json").write_text(payload, encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    index = env.get_template("index.html").render(ideas=ideas, domain=SITE_DOMAIN)
    (output_dir / "index.html").write_text(index, encoding="utf-8")
    (output_dir / "CNAME").write_text(SITE_DOMAIN + "\n", encoding="utf-8")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    return output_dir
