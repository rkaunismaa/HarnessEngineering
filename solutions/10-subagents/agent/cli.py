"""The interactive terminal: ``python -m agent chat``."""
from __future__ import annotations

from typing import Callable

from rich.console import Console
from rich.markup import escape

from .events import AgentEvents
from .loop import Agent

HELP = "Commands: /reasoning toggles showing the model's reasoning, /exit quits."


def preview(text: str, max_lines: int = 3, max_chars: int = 200) -> str:
    """A short version of a tool result for the screen: the first lines, cut to length, with a
    note saying how much was left out. The model still gets the full text."""
    lines = text.splitlines() or [""]
    shown = "\n".join(lines[:max_lines])
    cut = len(shown) > max_chars
    if cut:
        shown = shown[:max_chars]
    hidden = len(lines) - max_lines
    if hidden > 0:
        return f"{shown}\n... ({hidden} more lines)"
    return shown + ("..." if cut else "")


class ConsoleEvents(AgentEvents):
    """Print the agent's progress with rich: text as it streams, reasoning dimmed, one line per
    tool call, and a short preview of each result."""

    def __init__(self, console: Console, show_reasoning: bool = True):
        self.console = console
        self.show_reasoning = show_reasoning
        self._mid_line = False  # streamed text has been printed without a trailing newline
        self._kind = ""  # "text" or "reasoning": what the unfinished line holds

    def _end_line(self) -> None:
        if self._mid_line:
            self.console.print()
            self._mid_line = False

    def on_text(self, delta: str) -> None:
        if self._kind != "text":
            self._end_line()
        self._kind = "text"
        self.console.print(delta, end="", markup=False, highlight=False, soft_wrap=True)
        self._mid_line = True

    def on_reasoning(self, delta: str) -> None:
        if self.show_reasoning:
            if self._kind != "reasoning":
                self._end_line()
            self._kind = "reasoning"
            self.console.print(delta, end="", style="dim", markup=False, highlight=False,
                               soft_wrap=True)
            self._mid_line = True

    def on_tool_call(self, name: str, arguments: str) -> None:
        self._end_line()
        self.console.print(f"[bold cyan]> {escape(name)}[/bold cyan] {escape(arguments)}",
                           highlight=False, soft_wrap=True)

    def on_tool_result(self, name: str, result: str) -> None:
        if name == "todo_write" and not result.startswith("Error"):
            self.console.print(escape(result), style="magenta", highlight=False, soft_wrap=True)
            return
        self.console.print(escape(preview(result)), style="dim", highlight=False, soft_wrap=True)

    def on_compact(self, before: int, after: int) -> None:
        self._end_line()
        self.console.print(f"[yellow]Context compacted: about {before} -> {after} tokens.[/yellow]",
                           highlight=False, soft_wrap=True)

    def on_verify(self, passed: bool, output: str) -> None:
        self._end_line()
        if passed:
            self.console.print("[green]Check passed.[/green]", highlight=False)
        else:
            self.console.print("[yellow]Check failed:[/yellow]", highlight=False)
            self.console.print(escape(preview(output)), style="dim", highlight=False,
                               soft_wrap=True)

    def finish_turn(self) -> None:
        self._end_line()


def chat_loop(agent: Agent, events: ConsoleEvents, console: Console,
              read_input: Callable[[str], str] | None = None) -> int:
    """Read a line, run the agent on it, repeat. Ctrl-C during a turn interrupts that turn;
    Ctrl-C at the prompt, end of input or ``/exit`` quits."""
    read = read_input or (lambda prompt: console.input(prompt))
    console.print(f"Chat with the agent. {HELP}", highlight=False)
    while True:
        try:
            line = read("[bold green]you>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/reasoning":
            events.show_reasoning = not events.show_reasoning
            console.print(f"Reasoning is {'shown' if events.show_reasoning else 'hidden'}.")
            continue
        if line.startswith("/"):
            console.print(f"Unknown command. {HELP}")
            continue
        result = agent.run(line)
        events.finish_turn()
        if result.stop_reason == "interrupted":
            console.print("[yellow]Interrupted.[/yellow]")
        elif result.stop_reason == "error":
            console.print(f"[red]{escape(result.error or 'error')}[/red]")
        elif result.stop_reason == "max_turns":
            console.print(f"[yellow]Stopped after {result.turns} requests without a final "
                          "answer.[/yellow]")
        console.print(f"[dim]({result.usage.prompt_tokens} prompt + "
                      f"{result.usage.completion_tokens} completion tokens)[/dim]")
