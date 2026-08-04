from types import SimpleNamespace

from sixwords.interview import InterviewEngine


def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(name, input, id="toolu_01"):
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id)


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot the message list: the engine keeps appending to the same
        # list object after the call returns.
        kwargs["messages"] = list(kwargs["messages"])
        self.requests.append(kwargs)
        return SimpleNamespace(content=self._responses.pop(0))


DRAFTS_INPUT = {
    "candidates": [
        {
            "story": "Six words, chosen one by one.",
            "appeal": "Meta and true.",
            "word_choices": [{"word": "chosen", "reason": "agency", "alternatives": ["picked"]}],
        }
    ]
}

FINAL_INPUT = {
    "story": "Six words, chosen one by one.",
    "final_author": "human",
    "title": "Chosen",
    "backstory": "Every word fought for its place.",
    "word_choices": [{"word": "chosen", "reason": "agency"}],
}


def test_text_turn_parsed():
    client = FakeClient([[_text_block("What moment are you circling?")]])
    engine = InterviewEngine(client=client, model="test-model")
    turn = engine.start()
    assert turn.text == "What moment are you circling?"
    assert turn.drafts == []
    assert turn.final is None
    assert client.requests[0]["model"] == "test-model"


def test_drafts_turn_parsed_and_reaction_sent_as_tool_result():
    client = FakeClient(
        [
            [
                _text_block("Here are three."),
                _tool_block("propose_drafts", DRAFTS_INPUT, id="tu_9"),
            ],
            [_text_block("Good pick.")],
        ]
    )
    engine = InterviewEngine(client=client)
    turn = engine.start()
    assert len(turn.drafts) == 1
    assert turn.drafts[0].story == "Six words, chosen one by one."
    assert turn.drafts[0].word_choices[0]["alternatives"] == ["picked"]

    engine.send("I pick candidate 1.")
    last_user = client.requests[1]["messages"][-1]
    assert last_user["role"] == "user"
    assert last_user["content"][0]["type"] == "tool_result"
    assert last_user["content"][0]["tool_use_id"] == "tu_9"
    assert last_user["content"][0]["content"] == "I pick candidate 1."


def test_finalize_turn_parsed():
    client = FakeClient(
        [
            [_tool_block("finalize_story", FINAL_INPUT)],
        ]
    )
    engine = InterviewEngine(client=client)
    turn = engine.send("Call finalize_story now.")
    assert turn.final is not None
    assert turn.final.title == "Chosen"
    assert turn.final.backstory == "Every word fought for its place."
    assert turn.final.word_choices[0]["word"] == "chosen"
    assert turn.final.story == "Six words, chosen one by one."
    assert turn.final.final_author == "human"


def test_finalize_without_story_field_still_parses():
    sparse = {k: v for k, v in FINAL_INPUT.items() if k not in ("story", "final_author")}
    client = FakeClient([[_tool_block("finalize_story", sparse)]])
    engine = InterviewEngine(client=client)
    turn = engine.send("Call finalize_story now.")
    assert turn.final is not None
    assert turn.final.story is None
    assert turn.final.final_author is None


def test_plain_messages_alternate_without_tool_results():
    client = FakeClient([[_text_block("Q1?")], [_text_block("Q2?")]])
    engine = InterviewEngine(client=client)
    engine.start()
    engine.send("An answer.")
    messages = client.requests[1]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"] == "An answer."
