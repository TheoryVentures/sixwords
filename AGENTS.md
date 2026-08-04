# sixwords

A CLI for packaging a concept into exactly six words with an LLM coach. The
six words are the human-facing text; everything that produced them — the full
argument they compress, the coach interview, every draft, per-word rationale —
is stored as subtext in a sentree `.subtext.json` document. The project is a
demonstration of the subtext format's thesis: humans read the text, agents
operate on the subtext.

## Architecture

Four modules under `sixwords/`, with a strict boundary around document writes:

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

The `sentree` dependency is an editable install from the sibling checkout at
`../sentree` (see `[tool.uv.sources]` in `pyproject.toml`). It stays a pure
library; editor/app logic never lands there.

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
strips `$`-prefixed keys before `from_dict`. Saved stories live in `stories/`.

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
uv sync                # deps, including sentree from ../sentree
uv run pytest          # tests use a fake Anthropic client; no key or network
uv run ruff check .    # lint (line length 100)
```

Run both after any nontrivial change. Interactive testing of the write loop
requires a real key: `uv run sixwords write`.
