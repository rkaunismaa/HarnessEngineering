import json
from pathlib import Path

import pytest

from agent.client import SmokeResult, make_client, smoke_test
from agent.config import Config, load_config
from testing.fake_model import FakeClient, call, reply


def test_defaults():
    assert load_config(env={}, file=Path("/nonexistent")) == Config()


def test_env_overrides_file(tmp_path):
    f = tmp_path / "agent.json"
    f.write_text(json.dumps({"model": "a", "base_url": "http://x/v1", "context_window": 1000}))
    cfg = load_config(env={"AGENT_MODEL": "b", "AGENT_CONTEXT_WINDOW": "8192"}, file=f)
    assert cfg.model == "b"
    assert cfg.base_url == "http://x/v1"
    assert cfg.context_window == 8192
    assert isinstance(cfg.context_window, int)


def test_env_log_dir_is_path():
    cfg = load_config(env={"AGENT_LOG_DIR": "/tmp/logs"}, file=Path("/nonexistent"))
    assert cfg.log_dir == Path("/tmp/logs")


def test_sampling_unset_by_default():
    cfg = load_config(env={}, file=Path("/nonexistent"))
    assert (cfg.temperature, cfg.top_p, cfg.seed) == (None, None, None)
    assert cfg.sampling() == {}


def test_sampling_from_file_and_env(tmp_path):
    f = tmp_path / "agent.json"
    f.write_text(json.dumps({"temperature": 0.2, "seed": 1}))
    cfg = load_config(env={"AGENT_TOP_P": "0.9", "AGENT_SEED": "7"}, file=f)
    assert cfg.sampling() == {"temperature": 0.2, "top_p": 0.9, "seed": 7}
    assert isinstance(cfg.top_p, float) and isinstance(cfg.seed, int)


def test_smoke_ok():
    client = FakeClient([reply(tool_calls=[call("read_file", {"path": "notes.txt"})],
                               prompt_tokens=329)])
    result = smoke_test(client, "m")
    assert isinstance(result, SmokeResult)
    assert result.ok
    assert result.tool_name == "read_file"
    assert result.arguments == {"path": "notes.txt"}
    assert result.prompt_tokens == 329
    assert len(client.requests) == 1
    tools = client.requests[0]["tools"]
    assert len(tools) == 1 and tools[0]["function"]["name"] == "read_file"
    assert client.requests[0]["model"] == "m"


def test_smoke_no_tool_call():
    result = smoke_test(FakeClient([reply(content="I can't")]), "m")
    assert result.ok is False
    assert "no tool call" in result.detail.lower()


def test_smoke_bad_json():
    result = smoke_test(FakeClient([reply(tool_calls=[call("read_file", "{not json")])]), "m")
    assert result.ok is False


def test_smoke_missing_path():
    result = smoke_test(FakeClient([reply(tool_calls=[call("read_file", {"file": "x"})])]), "m")
    assert result.ok is False


def test_make_client_uses_config():
    client = make_client(Config(base_url="http://example:9/v1", api_key="k"))
    assert str(client.base_url).startswith("http://example:9/v1")
    assert client.api_key == "k"


@pytest.mark.live
def test_live_smoke():
    cfg = load_config()
    result = smoke_test(make_client(cfg), cfg.model)
    assert result.ok, result.detail
