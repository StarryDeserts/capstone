import pytest
from coo_agent.llm import LLM


class _Block:
    def __init__(self, text): self.type = "text"; self.text = text


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, text): self._text = text; self.calls = []
    async def create(self, **kwargs):
        self.calls.append(kwargs); return _Resp(self._text)


class _FakeClient:
    def __init__(self, text): self.messages = _FakeMessages(text)


async def test_generate_json_parses_fenced_output():
    c = _FakeClient('```json\n{"a": 1}\n```')
    out = await LLM(c, "m").generate_json(system="s", user="u")
    assert out == {"a": 1}
    assert c.messages.calls[0]["model"] == "m"


async def test_web_search_flag_adds_tools():
    c = _FakeClient('{"x": true}')
    await LLM(c, "m").generate_json(system="s", user="u", web_search=True)
    assert "tools" in c.messages.calls[0]


async def test_invalid_json_raises():
    c = _FakeClient("definitely not json")
    with pytest.raises(ValueError):
        await LLM(c, "m").generate_json(system="s", user="u")
