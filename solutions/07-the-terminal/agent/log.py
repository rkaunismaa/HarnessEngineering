"""The request log: one JSON line per model request."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class RequestLog:
    def __init__(self, path: Path, agent: str = "main"):
        self.path = Path(path)
        self.agent = agent

    @classmethod
    def for_session(cls, log_dir: Path) -> "RequestLog":
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        return cls(log_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl")

    def with_agent(self, name: str) -> "RequestLog":
        return RequestLog(self.path, name)

    def record(self, request: dict, response: dict, duration_s: float) -> None:
        entry = {"ts": datetime.now().isoformat(), "agent": self.agent,
                 "duration_s": round(duration_s, 3), "request": request, "response": response}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def latest_log(log_dir: Path) -> Path | None:
    files = sorted(Path(log_dir).glob("*.jsonl")) if Path(log_dir).is_dir() else []
    return files[-1] if files else None


def format_entry(entry: dict) -> str:
    request, response = entry["request"], entry["response"]
    usage = response.get("usage") or {}
    if response.get("streamed"):  # streamed requests log the assembled message
        message = response.get("message") or {}
        choice = {"finish_reason": "interrupted" if response.get("interrupted")
                  else response.get("finish_reason")}
    else:
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
    lines = [f"[{entry['agent']}] {entry['ts']}  {entry['duration_s']}s  "
             f"{len(request.get('messages', []))} messages  "
             f"prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}  "
             f"finish={choice.get('finish_reason')}"]
    if message.get("reasoning_content"):
        lines.append(f"  reasoning: {message['reasoning_content']}")
    if message.get("content"):
        lines.append(f"  content: {message['content']}")
    for tc in message.get("tool_calls") or []:
        fn = tc["function"]
        lines.append(f"  tool call {tc['id']}: {fn['name']}({fn['arguments']})")
    return "\n".join(lines)
