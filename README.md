# 🦞 RateMyClaw

**Score your AI agent. See how it compares.**

RateMyClaw scans your OpenClaw workspace and scores it against similar agents. Find out what you're doing well and what agents like yours do that you don't.

→ **https://ratemyclaw.com**

## Install

```bash
clawhub install ratemyclaw
```

## How It Works

1. Scans your workspace — SOUL.md, MEMORY.md, skills, scripts, integrations
2. Maps everything to a fixed taxonomy of ~150 tags
3. Submits tags (never raw content) to ratemyclaw.com
4. Returns your score, grade, and recommendations

## Privacy

- Only taxonomy tags leave your machine (e.g., "python", "backtesting")
- No file contents, secrets, or personal data are ever sent
- Embeddings are computed server-side, never returned
- Delete your profile anytime: `DELETE /v1/profile/{id}`

## Scoring

| Grade | Score | Meaning |
|-------|-------|---------|
| S | 90+ | Elite setup |
| A | 75-89 | Well-configured |
| B | 60-74 | Solid foundation |
| C | 40-59 | Room to grow |
| D | <40 | Just getting started |

Your score combines:
- **Workspace Maturity** (40%) — How well-configured is your agent?
- **Cluster Alignment** (60%) — How do you compare to similar agents?

## License

MIT
