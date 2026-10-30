import io

from rich.console import Console

from agent.__main__ import build_parser
from agent.cli import ConsoleEvents, chat_loop, preview
from agent.log import format_entry
from agent.loop import Agent
from agent.tools import make_default_tools
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, reply


def test_preview_short_text_unchanged():
    assert preview("one line") == "one line"


def test_preview_collapses_long_output():
    text = "\n".join(f"line {i}" for i in range(50))
    shown = preview(text, max_lines=3)
    assert shown.splitlines()[:3] == ["line 0", "line 1", "line 2"]
    assert "47 more lines" in shown
    assert "line 10" not in shown


def test_preview_cuts_long_lines():
    assert len(preview("x" * 5000, max_chars=100)) < 110


def test_chat_subcommand_is_parsed():
    args = build_parser().parse_args(["chat", "--root", "/tmp"])
    assert args.command == "chat" and args.root == "/tmp"


def run_chat(tmp_path, script, lines):
    out = io.StringIO()
    console = Console(file=out, width=80, force_terminal=False)
    events = ConsoleEvents(console)
    agent = Agent(FakeClient(script), "m", make_default_tools(Workspace(tmp_path)),
                  events=events, stream=True)
    feed = iter(lines)

    def read(prompt):
        item = next(feed, EOFError)
        if item is EOFError:
            raise EOFError
        if item is KeyboardInterrupt:
            raise KeyboardInterrupt
        return item

    code = chat_loop(agent, events, console, read_input=read)
    return code, out.getvalue(), agent


def test_chat_streams_answer_and_shows_tool_call(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    code, out, _ = run_chat(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(content="It says hello", reasoning="let me think"),
    ], ["what is in a.txt?", "/exit"])
    assert code == 0
    assert "read_file" in out and "a.txt" in out
    assert "It says hello" in out
    assert "let me think" in out


def test_reasoning_toggle(tmp_path):
    code, out, _ = run_chat(tmp_path, [reply(content="hi", reasoning="secret thoughts")],
                            ["/reasoning", "hello", "/exit"])
    assert "secret thoughts" not in out
    assert "hi" in out


def test_ctrl_c_at_prompt_and_eof_quit(tmp_path):
    assert run_chat(tmp_path, [], [KeyboardInterrupt])[0] == 0
    assert run_chat(tmp_path, [], [])[0] == 0


def test_interrupted_turn_returns_to_prompt(tmp_path):
    def broken():
        raise KeyboardInterrupt
        yield  # pragma: no cover

    client_script = [reply(content="second answer")]
    out = io.StringIO()
    console = Console(file=out, width=80, force_terminal=False)
    events = ConsoleEvents(console)
    client = FakeClient(client_script)
    client.script.insert(0, broken())
    agent = Agent(client, "m", make_default_tools(Workspace(tmp_path)), events=events, stream=True)
    lines = iter(["first", "second", "/exit"])
    assert chat_loop(agent, events, console, read_input=lambda p: next(lines)) == 0
    assert "Interrupted" in out.getvalue()
    assert "second answer" in out.getvalue()


def test_format_entry_handles_streamed_entries():
    entry = {"ts": "t", "agent": "main", "duration_s": 1.0,
             "request": {"messages": [{}]},
             "response": {"streamed": True, "finish_reason": "stop",
                          "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                          "message": {"role": "assistant", "content": "hello"}}}
    text = format_entry(entry)
    assert "prompt=5 completion=2" in text and "finish=stop" in text and "content: hello" in text


def test_reasoning_and_text_are_on_separate_lines(tmp_path):
    _, out, _ = run_chat(tmp_path, [reply(content="the answer", reasoning="the thinking")],
                         ["hello", "/exit"])
    assert "the thinking\nthe answer" in out.replace("\r", "")
