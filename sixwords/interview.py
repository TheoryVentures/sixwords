"""Claude-powered interview and drafting loop.

The engine holds the conversation with the model. It surfaces three kinds of
turns to the caller: a conversational question (text), a round of structured
draft candidates, or the final story package. Structured output arrives via
tool use, so draft text and rationale are never scraped out of prose.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = os.environ.get("SIXWORDS_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
You help people package a concept into exactly six words — a thesis \
compressed to its sharpest form, in the tradition of "Humans read the \
text, agents operate on the subtext." The six words are not a plot; they \
are an idea with everything inessential burned away.

Work in two phases:

PHASE 1 — INTERVIEW. Ask one short question at a time, three to five \
questions total. Pin the idea down precisely: the claim itself, the \
mechanism behind it, who needs to hear it, what it gets confused with, and \
what reaction the six words should provoke (recognition, alarm, argument). \
Prefer questions that force the person to say the idea more plainly than \
they have said it before. Keep each question to a sentence or two.

PHASE 2 — DRAFTS. When the idea is pinned down, call the propose_drafts \
tool with exactly three candidates. Each candidate must be exactly six \
words. Candidates should differ in strategy — a diagnosis, a warning, an \
aphorism — not just word swaps. For every word, give the reason it earned \
its slot and the alternatives you rejected. After proposing, respond to \
the user's reaction: revise, propose a new round, or ask one more question \
if something is still fuzzy.

FINALIZING. When the user accepts a final text — whether they picked a \
candidate, typed their own six words, or proposed them mid-conversation — \
call the finalize_story tool with: the final six words exactly as accepted \
(story), who wrote them (final_author: human if they are the user's own \
words, agent if yours, mixed if a blend), a short title for the concept, a \
backstory that states the full idea the six words compress — the claim, \
the mechanism, the stakes, written as the clearest prose version of the \
argument (2-4 paragraphs) — and word_choices for the final text as \
accepted, including any words the user wrote themselves; for those, infer \
the reason from context and note the word was the author's own.

Style: sharp, curious, allergic to vagueness. Visible text stays brief and \
conversational — all structured content goes through the tools. Never pad \
the six words to seven or trim them to five.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "propose_drafts",
        "description": (
            "Propose exactly three candidate six-word packagings of the concept, "
            "with per-word rationale."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "story": {
                                "type": "string",
                                "description": "The candidate packaging, exactly six words.",
                            },
                            "appeal": {
                                "type": "string",
                                "description": "One sentence on why this candidate works.",
                            },
                            "word_choices": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "word": {"type": "string"},
                                        "reason": {
                                            "type": "string",
                                            "description": "Why this word earned its slot.",
                                        },
                                        "alternatives": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Words considered and rejected.",
                                        },
                                    },
                                    "required": ["word", "reason"],
                                },
                            },
                        },
                        "required": ["story", "appeal", "word_choices"],
                    },
                }
            },
            "required": ["candidates"],
        },
    },
    {
        "name": "finalize_story",
        "description": (
            "Package the accepted six words: title, the full argument they compress, "
            "and final word choices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "story": {
                    "type": "string",
                    "description": "The final six words, exactly as the user accepted them.",
                },
                "final_author": {
                    "type": "string",
                    "enum": ["human", "agent", "mixed"],
                    "description": (
                        "Who wrote the final six words: the user (human), "
                        "you (agent), or a blend (mixed)."
                    ),
                },
                "title": {"type": "string", "description": "Short title for the concept."},
                "backstory": {
                    "type": "string",
                    "description": (
                        "The full idea the six words compress — claim, mechanism, "
                        "stakes — in 2-4 paragraphs."
                    ),
                },
                "word_choices": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "word": {"type": "string"},
                            "reason": {"type": "string"},
                            "alternatives": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["word", "reason"],
                    },
                },
            },
            "required": ["story", "final_author", "title", "backstory", "word_choices"],
        },
    },
]


@dataclass
class DraftCandidate:
    story: str
    appeal: str
    word_choices: list[dict[str, Any]]


@dataclass
class FinalStory:
    title: str
    backstory: str
    word_choices: list[dict[str, Any]]
    story: str | None = None
    final_author: str | None = None


@dataclass
class Turn:
    """One assistant turn: conversational text, drafts, a final package, or a mix."""

    text: str = ""
    drafts: list[DraftCandidate] = field(default_factory=list)
    final: FinalStory | None = None


class InterviewEngine:
    """Drives the conversation with Claude and parses each turn."""

    def __init__(self, client: Any = None, model: str = DEFAULT_MODEL) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self._messages: list[dict[str, Any]] = []
        self._pending_tool_id: str | None = None

    def start(self) -> Turn:
        return self.send("Hi — I'd like to write a six-word story.")

    def send(self, message: str) -> Turn:
        """Send the user's message (or reaction to drafts) and parse the reply."""
        if self._pending_tool_id is not None:
            # The previous assistant turn was a tool call; the user's reaction
            # travels back as the tool result.
            self._messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": self._pending_tool_id,
                            "content": message,
                        }
                    ],
                }
            )
            self._pending_tool_id = None
        else:
            self._messages.append({"role": "user", "content": message})
        return self._request()

    def _request(self) -> Turn:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self._messages,
        )
        self._messages.append({"role": "assistant", "content": response.content})

        turn = Turn()
        for block in response.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                self._pending_tool_id = block.id
                if block.name == "propose_drafts":
                    turn.drafts = [
                        DraftCandidate(
                            story=c["story"],
                            appeal=c.get("appeal", ""),
                            word_choices=c.get("word_choices", []),
                        )
                        for c in block.input["candidates"]
                    ]
                elif block.name == "finalize_story":
                    turn.final = FinalStory(
                        title=block.input["title"],
                        backstory=block.input["backstory"],
                        word_choices=block.input.get("word_choices", []),
                        story=block.input.get("story"),
                        final_author=block.input.get("final_author"),
                    )
        return turn
