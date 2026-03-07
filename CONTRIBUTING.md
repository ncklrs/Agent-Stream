# Contributing to Agent-Stream

## Quick Setup

```bash
git clone https://github.com/ncklrs/Agent-Stream.git
cd Agent-Stream
uv pip install -e ".[dev]"
```

## Architecture

| File | Purpose |
|------|---------|
| `agentstream/app.py` | Textual TUI app, event handling, UI widgets |
| `agentstream/parsers.py` | Format parsers (Claude CLI, Codex CLI, Claude SSE, Aider, interactive sessions) |
| `agentstream/events.py` | Event model (`Agent`, `ActionType`, `AgentEvent` dataclasses) |
| `agentstream/streams.py` | Stream sources (stdin, file, exec, watch, demo) |
| `agentstream/theme.py` | Colors, icons, rendering |
| `agentstream/__main__.py` | CLI entry point |

## Adding a New Agent Parser

This is the main extension point for community contributions.

1. Subclass `BaseParser` in `parsers.py`
2. Implement `parse_line(line: str) -> Optional[AgentEvent]`
3. Register in `create_parser()` and `AutoDetectParser`
4. Add detection logic in `AutoDetectParser.__init__`

Example skeleton:

```python
class MyToolParser(BaseParser):
    def parse_line(self, line: str) -> Optional[AgentEvent]:
        # Parse line into an AgentEvent or return None to skip
        ...
```

## Running Tests

```bash
pytest
```

## Code Style

- Python 3.10+ with type hints
- Keep it simple — no over-engineering
- No new dependencies without discussion

## Submitting Changes

1. Fork the repo and create a feature branch
2. Include tests for new parsers
3. Keep PRs focused — one feature or fix per PR
4. Open a pull request against `main`
