"""Build the OpenAI client and run a one-request smoke test of tool calling."""
from __future__ import annotations

import json
from dataclasses import dataclass

import openai

from .config import Config

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
}


@dataclass
class SmokeResult:
    ok: bool
    tool_name: str | None
    arguments: dict | None
    prompt_tokens: int | None
    detail: str


def make_client(config: Config) -> openai.OpenAI:
    return openai.OpenAI(base_url=config.base_url, api_key=config.api_key)


def smoke_test(client, model: str) -> SmokeResult:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Please read the file notes.txt."}],
        tools=[READ_FILE_TOOL],
    )
    tokens = response.usage.prompt_tokens if response.usage else None
    message = response.choices[0].message
    if not message.tool_calls:
        return SmokeResult(False, None, None, tokens,
                           f"no tool call in the reply (content: {message.content!r})")
    tc = message.tool_calls[0]
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        return SmokeResult(False, name, None, tokens, f"arguments are not valid JSON: {e}")
    if not isinstance(args, dict):
        return SmokeResult(False, name, None, tokens, "arguments are not a JSON object")
    if name != "read_file":
        return SmokeResult(False, name, args, tokens, f"expected read_file, got {name}")
    if "path" not in args:
        return SmokeResult(False, name, args, tokens, "arguments have no 'path' key")
    return SmokeResult(True, name, args, tokens, f"read_file({args['path']!r})")
