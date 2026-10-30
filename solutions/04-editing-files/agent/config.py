"""Configuration: defaults, then an optional JSON file, then environment variables."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Config:
    base_url: str = "http://localhost:1234/v1"
    model: str = "qwen/qwen3.8-27b"
    api_key: str = "lm-studio"
    context_window: int = 32768
    log_dir: Path = Path(".agent/logs")


_ENV = {
    "base_url": "AGENT_BASE_URL",
    "model": "AGENT_MODEL",
    "api_key": "AGENT_API_KEY",
    "context_window": "AGENT_CONTEXT_WINDOW",
    "log_dir": "AGENT_LOG_DIR",
}


def _coerce(name: str, value):
    if name == "context_window":
        return int(value)
    if name == "log_dir":
        return Path(value)
    return str(value)


def load_config(env: Mapping[str, str] | None = None, file: Path | None = None) -> Config:
    env = os.environ if env is None else env
    file = Path("agent.json") if file is None else Path(file)
    values: dict = {}
    if file.is_file():
        data = json.loads(file.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{file}: expected a JSON object")
        known = {f.name for f in fields(Config)}
        for name, value in data.items():
            if name in known:
                values[name] = _coerce(name, value)
    for name, var in _ENV.items():
        if var in env:
            values[name] = _coerce(name, env[var])
    return Config(**values)
