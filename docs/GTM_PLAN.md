# AgentStream Go-To-Market Plan

## Positioning

> "AgentStream is `htop` for coding agents — a zero-config terminal UI that streams Claude Code and Codex sessions in real time, with no accounts, no SDKs, and no data leaving your machine."

### Key Messaging Pillars

- **Zero config**: Auto-discovers sessions. No API keys, no accounts, no proxy setup.
- **Terminal native**: Lives where coding agents live. No context switch to a browser.
- **Privacy first**: Everything stays local. No telemetry, no cloud.
- **Multi-agent**: The only tool that shows Claude Code and Codex side-by-side.

### Competitive Differentiation

| Competitor | What they are | AgentStream's differentiator |
|---|---|---|
| **LangSmith** | Cloud-hosted tracing/eval platform. Requires SDK integration, account signup. | Zero-config, local-only, no SDK needed. Reads native session files. |
| **Helicone** | Proxy-based LLM observability. Requires routing API calls through proxy. | No proxy, no API key wrapping. Works with agents as-is. |
| **W&B Weave** | ML experiment tracking adapted for LLM traces. Heavy, cloud-first. | Single `uv tool install`. No accounts, no dashboards, no browser. |
| **Raw terminal** | Scrolling JSON that disappears. No filtering, no cost tracking. | Structure, color, filtering, search, pause, bookmarks, cost tracking. |

---

## Target Audiences

### Primary: Individual developers using Claude Code or Codex daily

- **Pain points**: Walls of scrolling JSON, no real-time visibility, no cost tracking, no unified multi-agent view.
- **Channels**: Twitter/X AI dev community, r/ClaudeAI, Hacker News, Claude Code Discord, GitHub trending.

### Secondary: AI/ML team leads evaluating agent tooling

- **Pain points**: Need visibility across team, cost-per-task understanding, agent action auditing.
- **Upgrade path**: Future "AgentStream Pro/Server" opportunity.

### Tertiary: AI tool builders and agent framework authors

- **Pain points**: Need to debug custom agents, want reference parsing implementation, need demo visualization.

---

## Distribution Channels

### Immediate (Week 1-2)

- [ ] Publish to PyPI (`pip install agentstream`)
- [ ] Add high-quality GIF/video to README top
- [ ] Add GitHub topics: `claude-code`, `codex`, `tui`, `agent-observability`, `terminal-ui`, `textual`
- [ ] Submit to Console.dev, TerminalTrove, awesome-textual

### Short-term (Week 2-4)

- [ ] "Show HN" post: "AgentStream — htop for Claude Code and Codex agents (terminal UI)"
- [ ] Cross-post to r/ClaudeAI, r/ChatGPTCoding with real use case
- [ ] Tweet thread with embedded video demo

### Medium-term (Month 1-3)

- [ ] Brew formula (`brew install agentstream`)
- [ ] Submit PR to Claude Code docs "Ecosystem Tools" section
- [ ] Submit to Codex CLI community tools list
- [ ] Engage with Claude Code Discord

---

## Content Strategy

1. **"I watched 5 Claude Code agents work simultaneously"** — hero demo blog + video
2. **"The hidden cost of coding agents"** — cost tracking showcase
3. **"Debugging a runaway agent with AgentStream"** — operational value tutorial
4. **"AgentStream vs. raw terminal"** — side-by-side comparison
5. **Short-form video clips** — 30-second feature demos for Twitter/Shorts

---

## Launch Plan

### Pre-launch (1-2 weeks before)

- Publish to PyPI
- Record 60-90 second hero demo video
- Create 10-second GIF loop for README
- Write launch blog post
- Prepare 3-4 feature screenshots

### Launch Day (Tuesday/Wednesday, 9am ET)

| Channel | Action |
|---|---|
| **Hacker News** | "Show HN: AgentStream — terminal UI for watching Claude Code and Codex agents in real-time" |
| **Twitter/X** | Thread: hero GIF → problem → features → install |
| **Reddit** | r/ClaudeAI, r/ChatGPTCoding, r/commandline |
| **Dev newsletters** | TLDR, Changelog, Console.dev, Python Weekly |
| **Discord** | Claude Code, Textual, Python |

### Messaging

- **Headline**: "AgentStream: See what your coding agents are actually doing"
- "One command. Zero config. Real-time visibility into Claude Code and Codex sessions."
- "Like htop, but for AI coding agents."
- "Your data never leaves your machine."

---

## Growth Loops

1. **"What is that?" loop** — distinctive TUI prompts questions during screen shares
2. **Screenshot/GIF loop** — terminal screenshots are native dev Twitter content
3. **Workflow integration loop** — `agentstream` in tmux becomes part of dotfiles repos
4. **Cost tracking loop** — surprising cost data is inherently viral
5. **Multi-agent loop** — each new agent integration brings that tool's user base

---

## Competitive Moat

1. **Format expertise** — 5+ event formats parsed, edge cases handled
2. **Terminal-native identity** — browser tools can't compete in terminal workflows
3. **Zero-config auto-discovery** — reads session files directly, no proxy/SDK needed
4. **Open source + local-only** — permanent advantage over hosted platforms

---

## Highest-Leverage Actions (Top 5)

1. **Publish to PyPI** — `pip install agentstream` removes biggest adoption friction
2. **Record hero GIF/video** — dev tools live or die by their README demo
3. **"Show HN" post** — single highest-ROI launch channel
4. **Add Cursor/Aider parsers** — each new agent doubles addressable audience
5. **Get listed in Claude Code community tools** — permanent compounding distribution
