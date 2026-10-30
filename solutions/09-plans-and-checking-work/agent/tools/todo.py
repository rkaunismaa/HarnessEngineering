"""The todo_write tool: the model's own plan, kept in the workspace."""
from __future__ import annotations

from ..workspace import Workspace
from .registry import Tool

STATUSES = ["pending", "in_progress", "completed"]
MARKS = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}


def render(todos: list[dict]) -> str:
    return "\n".join(f"{MARKS[t['status']]} {t['content']}" for t in todos)


def make_todo_write(ws: Workspace) -> Tool:
    def todo_write(todos: list[dict]) -> str:
        for t in todos:
            if t["status"] not in STATUSES:
                return f"Error: invalid status '{t['status']}'."
        if sum(t["status"] == "in_progress" for t in todos) > 1:
            return "Error: only one item can be in_progress at a time."
        ws.todos = [{"content": t["content"], "status": t["status"]} for t in todos]
        return render(ws.todos)

    return Tool(
        name="todo_write",
        description="Write your plan for a task with several steps. Send the complete list "
                    "every time; it replaces the previous one. Keep exactly one item "
                    "in_progress while you work, and mark items completed as soon as they "
                    "are done. Skip it for simple one-step requests.",
        parameters={
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The whole list, in order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "What to do"},
                            "status": {"type": "string", "enum": STATUSES},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
        fn=todo_write,
        read_only=True,  # it changes only harness state
    )
