"""CLI entry point for AgentStream.

Usage:
    agentstream                              # Demo mode (default)
    agentstream --demo                       # Explicit demo mode

    # Pipe from headless CLI tools:
    claude -p "task" --output-format stream-json | agentstream
    codex exec --json "task" | agentstream
    some_tool | agentstream --stdin auto      # Force stdin + auto-detect

    # Run a CLI tool as subprocess:
    agentstream --exec codex "codex exec --json 'task'"
    agentstream --exec claude "claude -p 'task' --output-format stream-json"

    # Watch log files:
    agentstream --file codex ~/.codex/sessions/2025/01/01/rollout-abc.jsonl

    # Combine multiple sources:
    agentstream --exec codex "codex exec --json 'task'" \\
                --exec claude "claude -p 'task' --output-format stream-json"
"""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agentstream",
        description="Stream and visualize Claude and Codex agent events in a TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  agentstream                                             Demo mode
  claude -p "task" --output-format stream-json \\
    | agentstream                                         Pipe Claude CLI
  codex exec --json "task" | agentstream                  Pipe Codex CLI
  agentstream --exec codex "codex exec --json 'task'"     Run Codex subprocess
  agentstream --file codex /path/to/session.jsonl         Watch log file

keyboard:
  space  Pause/Resume    s    Toggle sidebar    1/2  Filter agents
  c      Clear log       ?    Help              q    Quit
""",
    )

    parser.add_argument(
        "--demo", action="store_true",
        help="Run with simulated demo data (default when no input)",
    )
    parser.add_argument(
        "--stdin", choices=["claude", "codex", "auto"],
        help="Read stream from stdin (specify agent format or auto-detect)",
    )
    parser.add_argument(
        "--file", nargs=2, action="append", metavar=("AGENT", "PATH"),
        help="Watch a JSONL/SSE file. AGENT is claude|codex|auto",
    )
    parser.add_argument(
        "--exec", nargs=2, action="append", metavar=("AGENT", "CMD"),
        help="Run a command and stream its JSON output. AGENT is claude|codex|auto",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.2.0",
    )

    args = parser.parse_args()

    sources: list[tuple[str, object]] = []

    if args.demo:
        sources.append(("demo", None))

    if args.stdin:
        sources.append(("stdin", args.stdin))

    if args.file:
        for agent, path in args.file:
            sources.append(("file", {"agent": agent, "path": path}))

    if getattr(args, "exec"):
        for agent, cmd in getattr(args, "exec"):
            sources.append(("exec", {"agent": agent, "cmd": cmd}))

    # Default: demo if tty, auto-detect stdin if piped
    if not sources:
        if sys.stdin.isatty():
            sources.append(("demo", None))
        else:
            sources.append(("stdin", "auto"))

    try:
        from agentstream.app import AgentStreamApp
        app = AgentStreamApp(sources=sources)
        app.run()
    except ImportError as e:
        print(f"Missing dependency: {e}", file=sys.stderr)
        print("Install with: pip install -e .", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
