# sixwords

A CLI for packaging a concept into exactly six words with an LLM coach. The
six words are the human-facing text; everything that produced them — the full
argument they compress, the coach interview, every draft, per-word rationale —
is stored as subtext in a sentree `.subtext.json` document. The project is a
demonstration of the subtext format's thesis: humans read the text, agents
operate on the subtext.

## Architecture

Six modules under `sixwords/`, with a strict boundary around document writes:

- `story.py` — the only module that reads or mutates the sentree `Document`.
  All drafts go through `Document.update_sentence` so provenance and the edit
  log are maintained by the library, never by hand. If you need a new document
  operation, add it here.
- `interview.py` — the Claude conversation loop (`InterviewEngine`).
  Structured content (draft candidates, the final package) arrives via tool
  use (`propose_drafts`, `finalize_story`), never parsed out of prose. Each
  `Turn` surfaces text, drafts, and/or a `FinalStory`.
- `cli.py` — click commands (`write`, `read`, `list`, `export`). `_Session`
  owns the write-loop state: the document, interview buffer, and candidate
  log. The coach may call `finalize_story` at any point, including when the
  accepted words only ever existed in conversation — `_Session.finish`
  reconciles the document with the finalized text before saving.
- `reader.py` — the reveal experience: six words first, then subtext layer by
 layer.
- `publish.py` — the sixwordidea.com backend client (Supabase): email
 one-time-code sign-in with a session cached at
 `~/.sixwords/credentials.json`, and inserts into the `ideas` table. Reads
 are anonymous; publishing requires a signed-in user (enforced by
 row-level security in `supabase/schema.sql`).
- `site.py` — the static site generator for sixwordidea.com (Jinja template
 in `sixwords/templates/`): an index of idea cards, each linking to the raw
 subtext JSON at `/ideas/<slug>.json` so agents can fetch it with a plain
 URL. Deployed to GitHub Pages by `.github/workflows/site.yml`.

The `sentree` library is vendored at `vendor/sentree` and shipped as a
top-level package inside the sixwords wheel (see `vendor/README.md` for the
source commit and update procedure). It stays a pure library; editor/app
logic never lands there — upstream changes go to the sentree repo first,
then get re-vendored.

## The artifact

Each story is one nested-JSON sentree document (`contextdoc/nested-v1`) with a
single sentence, `s-0001`:

| Where                            | What                                            |
| -------------------------------- | ----------------------------------------------- |
| `sentence.text`                  | the six words                                   |
| `sentence.meta.backstory`        | the full idea: claim, mechanism, stakes         |
| `sentence.meta.word_choices`     | per-word rationale and rejected alternatives    |
| `sentence.meta.drafts`           | chronological drafts with author and rationale  |
| `metadata.interview`             | coach/author Q&A, `{question, answer}` pairs    |
| `metadata.candidates_considered` | every proposed candidate, chosen or not         |
| provenance + `metadata.edit_log` | who wrote the final words (human vs agent), when, why |

Files carry a top-level `$format` and `$legend` (see `story.LEGEND`); `load()`
strips `$`-prefixed keys before `from_dict`. Stories are saved to
`~/.sixwords/stories` by default (`--stories-dir` / `SIXWORDS_STORIES_DIR`
override); the repo's `stories/` directory holds example stories.

## Conventions

- Provenance is honest: `authored_by`/`author_type` reflect who actually wrote
  the words (the model ID for agent drafts, the user for their own), with
  `requested_by` naming the human when an agent wrote them.
- Exactly six words is the product's contract. Don't add code that silently
  pads or trims; the human is always asked before their input is treated as a
  draft.
- The Anthropic model default is `claude-sonnet-5`, overridable via
  `SIXWORDS_MODEL`. The API key comes from `ANTHROPIC_API_KEY`.

## Development

```bash
uv sync                # deps; sentree is vendored, no sibling checkout needed
uv run pytest          # tests use a fake Anthropic client; no key or network
uv run ruff check .    # lint (line length 100)
```

Run both after any nontrivial change. Interactive testing of the write loop
requires a real key: `uv run sixwords write`.
