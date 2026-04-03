# 🦞 RateMyClaw

**Score your AI agent. See how it compares.**

RateMyClaw scans your OpenClaw workspace and scores it against similar agents. Find out what you're doing well and what agents like yours do that you don't.

→ **https://ratemyclaw.com**

## Install

```bash
clawhub install ratemyclaw
pip install sentence-transformers
```

Then tell your agent: "rate my claw" or "score my agent"

## How It Works

1. **Scan your workspace** — the agent reads your files locally, maps them to ~230 taxonomy tags
2. **Review before submitting** — the agent shows you what it detected, you can correct false positives
3. **Generate embedding locally** — a small model ([all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)) runs on your machine to create a 384-dim semantic fingerprint
4. **Get scored** — see your grade and score, then visit your score page for the full breakdown

## What Gets Submitted

| Data | Purpose |
|------|---------|
| Taxonomy tags (e.g., "python", "backtesting") | Recommendation matching |
| 384 floats (embedding vector) | Semantic cluster discovery |
| Installed skill slugs | Skill recommendations |
| Maturity counts (file counts, booleans) | Workspace scoring |

**What NEVER leaves your machine:** File contents, SOUL.md, MEMORY.md, secrets, personal data, raw text of any kind.

## Privacy

- Embeddings are generated **locally** using `sentence-transformers` — your text never touches any API
- While embeddings encode semantic meaning and can't be trivially reversed, treat them as potentially sensitive
- We never see your files, only structured tags and numbers
- Individual profiles are never exposed to other users — only aggregate cluster patterns
- Delete your profile anytime: `DELETE /v1/profile/{id}`

## Scoring

| Grade | Score | Meaning |
|-------|-------|---------|
| S | 90+ | Elite setup |
| A | 75-89 | Well-configured |
| B | 60-74 | Solid foundation |
| C | 40-59 | Room to grow |
| D | <40 | Just getting started |

Full breakdown available on your score page at ratemyclaw.com.

## Requirements

- Python 3.10+
- `sentence-transformers` — install with `pip install sentence-transformers` (~80MB model download on first use)

## License

MIT
