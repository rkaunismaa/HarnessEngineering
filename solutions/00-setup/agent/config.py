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
    # Sampling. None means "send nothing and use the server's default".
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None

    def sampling(self) -> dict:
        """The sampling settings that are set, as request keyword arguments."""
        return {name: value for name, value in (
            ("temperature", self.temperature), ("top_p", self.top_p), ("seed", self.seed),
        ) if value is not None}


_ENV = {
    "base_url": "AGENT_BASE_URL",
    "model": "AGENT_MODEL",
    "api_key": "AGENT_API_KEY",
    "context_window": "AGENT_CONTEXT_WINDOW",
    "log_dir": "AGENT_LOG_DIR",
    "temperature": "AGENT_TEMPERATURE",
    "top_p": "AGENT_TOP_P",
    "seed": "AGENT_SEED",
}


def _coerce(name: str, value):
    if name in ("context_window", "seed"):
        return int(value)
    if name in ("temperature", "top_p"):
        return float(value)
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
