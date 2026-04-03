---
name: ratemyclaw
description: Score your OpenClaw agent setup against similar agents. Scans your workspace, generates a profile, and submits to ratemyclaw.com for scoring and cluster comparison. Privacy-first — only taxonomy tags leave your machine.
metadata:
  version: 0.1.0
  author: picklenick144
  homepage: https://ratemyclaw.com
  repository: https://github.com/picklenick144/ratemyclaw
---

# RateMyClaw

Score your OpenClaw agent and see how it compares to others working on similar problems.

## What It Does

1. Scans your workspace (SOUL.md, MEMORY.md, skills, scripts, integrations, etc.)
2. Generates a structured profile using a fixed taxonomy (no raw content leaves your machine)
3. Submits the profile to ratemyclaw.com
4. Returns your score + recommendations based on what similar agents do

## Quick Start

When the user asks to "rate my claw", "score my agent", "check my setup", or similar:

### Step 1: Scan the workspace

Run the profile generator script:

```bash
python3 scripts/profile_generator.py ~/.openclaw/workspace
```

This produces a `generated_profile.json` in the skill directory.

### Step 2: Review the profile with the user

Show them what tags were detected and ask if it looks right. They can remove false positives or add missing tags.

### Step 3: Submit to RateMyClaw

```bash
python3 scripts/submit_profile.py generated_profile.json
```

This requires a `RATEMYCLAW_API_KEY` environment variable. Users can get one at ratemyclaw.com.

The script will print:
- Overall score (0-100)
- Letter grade (S/A/B/C/D)
- Workspace maturity breakdown
- Cluster alignment (if enough similar agents exist)
- Recommendations
- Shareable score URL

### Step 4: Share!

Give the user their score URL. They can share it, tweet it, or just use the recommendations to improve their setup.

## Privacy

- Only taxonomy tags are submitted (e.g., "quantitative-trading", "python", "backtesting")
- No file contents, secrets, or personal data ever leave the machine
- The taxonomy is a fixed list of ~150 tags — no free-form text
- Embeddings are computed server-side and never returned to the client
- Users can delete their profile at any time via the API

## Files

- `scripts/profile_generator.py` — Workspace scanner (runs locally)
- `scripts/submit_profile.py` — API submission script
- `references/taxonomy.json` — The fixed tag taxonomy
