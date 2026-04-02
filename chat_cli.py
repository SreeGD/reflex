#!/usr/bin/env python3
"""Reflex Chat CLI — terminal REPL over POST /chat.

Usage:
    python chat_cli.py                          # connects to localhost:8000
    python chat_cli.py --url http://host:8000   # custom server
    python chat_cli.py --local                  # run engine directly (no server needed)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()


def print_header():
    console.print(Panel(
        "[bold white]Reflex Chat[/bold white]\n"
        "[dim]AI-powered incident management assistant[/dim]\n"
        "[dim]Type 'quit' or 'exit' to leave. Ctrl+C to interrupt.[/dim]",
        border_style="bright_blue",
        padding=(1, 4),
    ))


async def run_local(session_id: str):
    """Run the chat engine directly without a server."""
    from backend.app.chat.engine import create_chat_engine

    engine = create_chat_engine()
    print_header()
    console.print("[dim]Mode: local (no server needed)[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if user_input.strip().lower() in ("quit", "exit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if not user_input.strip():
            continue

        with console.status("[dim]Thinking...[/dim]"):
            response = await engine.chat(session_id, user_input)

        console.print()
        console.print("[bold green]Reflex:[/bold green]", Markdown(response.text))
        console.print()


async def run_remote(base_url: str, session_id: str):
    """Run as a client calling POST /chat on the server."""
    import json
    from urllib.request import Request, urlopen

    print_header()
    console.print(f"[dim]Mode: remote ({base_url})[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold cyan]You:[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if user_input.strip().lower() in ("quit", "exit"):
            console.print("[dim]Goodbye.[/dim]")
            break

        if not user_input.strip():
            continue

        with console.status("[dim]Thinking...[/dim]"):
            payload = json.dumps({
                "session_id": session_id,
                "message": user_input,
                "user_id": "cli",
            }).encode()
            req = Request(
                f"{base_url}/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            try:
                resp = urlopen(req, timeout=60)
                data = json.loads(resp.read())
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                continue

        console.print()
        console.print("[bold green]Reflex:[/bold green]", Markdown(data["text"]))
        console.print()


def main():
    parser = argparse.ArgumentParser(description="Reflex Chat CLI")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Server URL (default: http://localhost:8000)")
    parser.add_argument("--local", action="store_true",
                        help="Run engine directly without a server")
    parser.add_argument("--session", default=None,
                        help="Session ID (default: random)")
    args = parser.parse_args()

    session_id = args.session or f"cli-{uuid.uuid4().hex[:8]}"

    if args.local:
        asyncio.run(run_local(session_id))
    else:
        asyncio.run(run_remote(args.url, session_id))


if __name__ == "__main__":
    main()
