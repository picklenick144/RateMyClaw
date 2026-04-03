---
name: ratemyclaw
description: Score your OpenClaw agent setup against similar agents. Scans your workspace, generates a local embedding for privacy-preserving semantic matching, and submits tags + embedding to ratemyclaw.com for scoring and cluster comparison.
metadata:
  version: 0.3.0
  author: picklenick144
  homepage: https://ratemyclaw.com
  repository: https://github.com/picklenick144/RateMyClaw
  env:
    - name: RATEMYCLAW_API_KEY
      description: "API key for ratemyclaw.com (format: rmc_...). If not set, the submit script will prompt before generating one."
      required: false
---

# RateMyClaw

Score your OpenClaw agent and see how it compares to others working on similar problems.

## What It Does

1. Scans your workspace (SOUL.md, MEMORY.md, skills, scripts, integrations, etc.)
2. Maps files to a fixed taxonomy of ~230 tags — no raw file content is extracted
3. Generates a 384-dim semantic embedding **locally** using sentence-transformers
4. Submits only tags + embedding (float array) + maturity counts to ratemyclaw.com
5. Returns your score, grade, and a link to your full breakdown on the web

## Prerequisites

```bash
pip install sentence-transformers
```

Required for local embedding generation (~80MB one-time model download). The submit script will **not** auto-install this — it exits with an error if the package is missing.

## Quick Start

When the user asks to "rate my claw", "score my agent", "check my setup", or similar:

### Step 1: Scan the workspace

```bash
python3 scripts/profile_generator.py ~/.openclaw/workspace
```

This produces a `generated_profile.json` in the skill directory.

### Step 2: Review the profile with the user

Show them what tags were detected and what skills were found. They can correct false positives before submission.

### Step 3: Submit to RateMyClaw

```bash
python3 scripts/submit_profile.py generated_profile.json
```

If no `RATEMYCLAW_API_KEY` env var is set and no saved key exists, the script will **ask for confirmation** before generating a free key via `POST /v1/keys`. Pass `--yes` to skip the prompt in automated contexts.

The submit script will:
- Generate a 384-dim embedding **locally** using sentence-transformers
- Submit tags + embedding + maturity counts to ratemyclaw.com
- Print your score, grade, and a link to the full breakdown

### Step 4: View results!

The full breakdown, insights, and recommendations are on the website at your score URL — not in the terminal.

## What Gets Sent

**Sent to ratemyclaw.com:**
- Taxonomy tags (domains, tools, patterns, integrations) — structured labels only
- Skill slugs (names of installed skills)
- 384 floating-point numbers (the embedding vector)
- Maturity counts (number of memory files, scripts, etc.)
- Automation level and stage

**Never sent:**
- Raw file contents (SOUL.md, MEMORY.md, scripts, secrets, etc.)
- Workspace text of any kind

**About embeddings:** The 384-float embedding is generated locally from your tag data using sentence-transformers (all-MiniLM-L6-v2). While embeddings encode semantic meaning and cannot be trivially reversed into text, they should be treated as potentially sensitive — they represent a condensed fingerprint of your agent's focus areas.

## Credentials

- **`RATEMYCLAW_API_KEY`** — optional env var. If not set, the script checks for a saved key in `.ratemyclaw_key` (inside the skill directory). If no key exists anywhere, it prompts before generating one.
- Keys are free and generated via `POST /v1/keys` on ratemyclaw.com
- Saved key file (`.ratemyclaw_key`) is created with `chmod 600` and listed in `.gitignore`

## Files

- `scripts/profile_generator.py` — Workspace scanner (runs locally, produces JSON)
- `scripts/submit_profile.py` — Embedding generation + API submission (prompts before any network calls if no key exists)
- `references/taxonomy.json` — The fixed tag taxonomy (233 tags)
