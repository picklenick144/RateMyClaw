---
name: ratemyclaw
description: Score your OpenClaw agent setup against similar agents. Scans your workspace, generates a local embedding for privacy-preserving semantic matching, and submits to ratemyclaw.com for scoring and cluster comparison. Your text never leaves your machine.
metadata:
  version: 0.2.0
  author: picklenick144
  homepage: https://ratemyclaw.com
  repository: https://github.com/picklenick144/RateMyClaw
---

# RateMyClaw

Score your OpenClaw agent and see how it compares to others working on similar problems.

## What It Does

1. Scans your workspace (SOUL.md, MEMORY.md, skills, scripts, integrations, etc.)
2. Maps files to a fixed taxonomy of ~230 tags (no raw content leaves your machine)
3. Generates a 384-dim semantic embedding **locally** using sentence-transformers
4. Submits only tags + embedding (float array) + maturity counts to ratemyclaw.com
5. Returns your score, grade, and recommendations based on similar agents

## Quick Start

When the user asks to "rate my claw", "score my agent", "check my setup", or similar:

### Step 1: Scan the workspace

```bash
python3 scripts/profile_generator.py ~/.openclaw/workspace
```

This produces a `generated_profile.json` in the skill directory.

### Step 2: Review the profile with the user

Show them what tags were detected and what skills were found. They can correct false positives.

### Step 3: Submit to RateMyClaw

```bash
RATEMYCLAW_API_KEY=your-key python3 scripts/submit_profile.py generated_profile.json
```

The submit script will:
- Auto-install `sentence-transformers` if needed (one-time, ~80MB)
- Generate a 384-dim embedding **locally** (text never leaves the machine)
- Submit tags + embedding + maturity to ratemyclaw.com
- Print score, grade, recommendations, and a shareable URL

### Step 4: Share!

Give the user their score URL. They can share it, tweet it, or use the recommendations to improve.

## Privacy Architecture

```
Your workspace files
       ↓ (read locally)
Profile generator → taxonomy tags + skill slugs + maturity counts
       ↓ (embedded locally)  
sentence-transformers/all-MiniLM-L6-v2 → 384 floats
       ↓ (submitted)
ratemyclaw.com receives: tags + floats + counts
       ↓ (never receives)
❌ File contents, SOUL.md text, MEMORY.md, secrets, raw text
```

- Embeddings are generated CLIENT-SIDE — your text never touches any API
- The float array can't be reversed into text
- Individual profiles are never shared — only aggregate cluster patterns returned
- Users can delete their profile at any time

## Files

- `scripts/profile_generator.py` — Workspace scanner (runs locally)
- `scripts/submit_profile.py` — Embedding generation + API submission
- `references/taxonomy.json` — The fixed tag taxonomy (233 tags)
