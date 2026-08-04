# sixwords

Package a concept into exactly six words with an LLM coach. The six words
are the human-facing text; everything that went into them — the full
argument they compress, the interview, the drafts, the reason every word
earned its slot — is the subtext, stored in a [sentree](../sentree)
`.subtext.json` document.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). The `sentree`
package is resolved from the sibling checkout at `../sentree`.

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
uv run sixwords write            # interview → drafts → accept → saved story
uv run sixwords read stories/my-story.subtext.json   # six words, then the reveal
uv run sixwords list             # stories written so far
uv run sixwords export stories/my-story.subtext.json # surface markdown only
```

`write` runs a short interview (the coach asks one question at a time to pin
the idea down), then proposes three candidate packagings with per-word
rationale. Pick one, type your own six words, or ask for changes. When you
lock the words in, the coach writes the title and the full prose version of
the argument, and everything is saved.

`read` shows only the six words first, then reveals the subtext layer by
layer: the idea in full, the word-by-word rationale, the draft evolution,
the interview, and the human/AI provenance. Pass `--all` to skip the pauses.

## The artifact

Each story is one nested-JSON sentree document with a single sentence
(`s-0001`):

- `sentence.text` — the six words
- `sentence.meta.backstory` — the full idea they compress (claim, mechanism, stakes)
- `sentence.meta.word_choices` — per-word rationale and rejected alternatives
- `sentence.meta.drafts` — every draft, stamped with author and rationale
- `metadata.interview` — the coach's questions and your answers
- `metadata.candidates_considered` — every candidate proposed, chosen or not
- provenance + `metadata.edit_log` — who wrote the final words (human vs
  agent), when, and why, maintained by sentree's mutation API

The default model is `claude-sonnet-5`; override with `SIXWORDS_MODEL`.

## Development

```bash
uv run pytest        # tests use a fake Anthropic client; no key needed
uv run ruff check .
```
