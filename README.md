```
   ▄▀█ █▀▀ █▀▀ █▄░█ ▀█▀   █▀ ▀█▀ █▀█ █▀▀ ▄▀█ █▀▄▀█
   █▀█ █▄█ ██▄ █░▀█ ░█░   ▄█ ░█░ █▀▄ ██▄ █▀█ █░▀░█
```
**your agents streaming by @ncklrs**

A terminal UI that streams and visualizes agent events from **Claude Code** and **OpenAI Codex** in a single unified view.

## Install

```bash
uv tool install git+https://github.com/ncklrs/Agent-Stream.git
```

Or with [pipx](https://pipx.pypa.io/):

```bash
pipx install git+https://github.com/ncklrs/Agent-Stream.git
```

Requires Python 3.10+. Install [uv](https://docs.astral.sh/uv/) with `curl -LsSf https://astral.sh/uv/install.sh | sh`

For development: `git clone` then `uv pip install -e .`

## Usage

### Pipe from CLI tools (most common)

```bash
# Claude Code
claude -p "refactor auth module" --output-format stream-json | agentstream

# Codex
codex exec --json "add unit tests" | agentstream
```

AgentStream auto-detects which format is being piped.

### Run agents as subprocesses

```bash
# Single agent
agentstream --exec claude "claude -p 'task' --output-format stream-json"

# Multiple agents side-by-side
agentstream \
  --exec claude "claude -p 'refactor auth' --output-format stream-json" \
  --exec codex "codex exec --json 'add tests'"
```

### Watch log files

```bash
agentstream --file codex ~/.codex/sessions/2025/01/01/session.jsonl
```

### Demo mode

```bash
agentstream --demo
```

Runs a simulated session showing both Claude and Codex events.

## Keyboard

| Key     | Action                        |
|---------|-------------------------------|
| `space` | Pause / Resume (buffers events while paused) |
| `s`     | Toggle sidebar (stream list)  |
| `1`     | Toggle Claude events on/off   |
| `2`     | Toggle Codex events on/off    |
| `c`     | Clear the stream log          |
| `?`     | Help overlay                  |
| `q`     | Quit                          |

Click sessions in the sidebar to toggle individual stream visibility.

## Features

- **Auto-detection** - Distinguishes Claude CLI JSONL, Codex JSONL, and Claude API SSE formats from the first line
- **Color-coded agents** - Claude in violet, Codex in green, distinct colors per action type
- **Session tracking** - Each agent session gets a sidebar entry with event counts
- **True pause** - Events buffer in memory while paused so nothing scrolls away; flushed on resume
- **Cost tracking** - Displays cumulative API cost from Claude result events
- **Crash-resistant** - Bad JSON, broken pipes, and unknown event types are handled gracefully

## Supported formats

| Source | Command | Format |
|--------|---------|--------|
| Claude Code CLI | `claude -p "..." --output-format stream-json` | JSONL with SDK message types |
| Codex CLI | `codex exec --json "..."` | JSONL with dot-separated event types |
| Claude API (raw) | `curl -N .../v1/messages` | Server-Sent Events (SSE) |

## License

MIT
