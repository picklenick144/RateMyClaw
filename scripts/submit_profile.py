"""
Submit a generated profile to RateMyClaw API.
Generates a privacy-preserving embedding locally before submission.

Prerequisites:
    pip install sentence-transformers

Usage:
    RATEMYCLAW_API_KEY=rmc_xxx python3 submit_profile.py [profile.json]
    
    If no API key is provided, the script will ask before generating one.
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "https://ratemyclaw.com"
KEY_FILE = Path(__file__).parent.parent / ".ratemyclaw_key"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def get_api_key() -> str:
    """Get API key from env var or saved file. Prompts before generating a new one."""
    # 1. Check env var
    env_key = os.environ.get("RATEMYCLAW_API_KEY", "")
    if env_key.startswith("rmc_"):
        return env_key
    
    # 2. Check saved key file
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text().splitlines():
            if line.startswith("RATEMYCLAW_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key.startswith("rmc_"):
                    return key
    
    # 3. No key found — ask before generating
    print("  ⚠️  No API key found.")
    print(f"     This will POST to {API_BASE}/v1/keys to generate a free key")
    print(f"     and save it to {KEY_FILE}")
    print()
    
    # Support non-interactive mode via --yes flag
    if "--yes" not in sys.argv:
        answer = input("     Generate a key? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  ❌ Aborted. Set RATEMYCLAW_API_KEY env var or pass --yes to auto-generate.")
            sys.exit(1)
    
    print("  🔑 Generating API key...")
    data = json.dumps({"label": "auto"}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/keys",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        key = result["api_key"]
        
        # Save it
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(KEY_FILE, "w") as f:
            f.write(f"RATEMYCLAW_API_KEY={key}\n")
        os.chmod(str(KEY_FILE), 0o600)
        print(f"  ✓ Key saved to {KEY_FILE}")
        return key
    except Exception as e:
        print(f"  ❌ Could not generate key: {e}")
        sys.exit(1)


def generate_embedding(profile: dict) -> list[float]:
    """Generate a 384-dim embedding locally from the profile's tag data.
    
    Builds a text summary from tags, skill slugs, and metadata,
    then embeds it using sentence-transformers. Only the resulting
    384 float array is returned — no raw text is ever transmitted.
    
    Note: While embeddings cannot be trivially reversed into text,
    they do encode semantic meaning. Treat them as potentially sensitive.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("❌ sentence-transformers is required but not installed.")
        print("   Install it with: pip install sentence-transformers")
        sys.exit(1)
    
    # Build text from structured tags only (not raw file contents)
    parts = []
    for key in ["domains", "tools", "patterns", "integrations"]:
        vals = profile.get(key, [])
        if vals:
            parts.append(f"{key}: {', '.join(vals)}")
    
    if profile.get("skills_installed"):
        parts.append(f"installed skills: {', '.join(profile['skills_installed'])}")
    
    parts.append(f"automation level: {profile.get('automation_level', 'unknown')}")
    parts.append(f"stage: {profile.get('stage', 'unknown')}")
    
    text = ". ".join(parts)
    
    print("  ⏳ Loading embedding model (first run downloads ~80MB, may take a minute)...")
    sys.stdout.flush()
    model = SentenceTransformer(EMBEDDING_MODEL)
    print("  ✓ Model loaded")
    
    print("  ⏳ Generating embedding...")
    sys.stdout.flush()
    embedding = model.encode(text).tolist()
    print(f"  ✓ Generated {len(embedding)}-dim embedding locally")
    return embedding


def submit(profile_path: str):
    api_key = get_api_key()
    
    with open(profile_path) as f:
        profile = json.load(f)
    
    print("🔐 Generating embedding locally...")
    sys.stdout.flush()
    embedding = generate_embedding(profile)
    
    # Build the submission payload
    payload = {
        "profile": {
            "domains": profile.get("domains", []),
            "tools": profile.get("tools", []),
            "patterns": profile.get("patterns", []),
            "integrations": profile.get("integrations", []),
            "skills_installed": profile.get("skills_installed", []),
            "automation_level": profile.get("automation_level", "manual"),
            "stage": profile.get("stage", "building"),
        },
        "embedding": embedding,
        "maturity": profile.get("maturity", {}),
    }
    
    print("📤 Submitting to ratemyclaw.com (tags + embedding only)...")
    sys.stdout.flush()
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/profile",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ API error ({e.code}): {body}")
        sys.exit(1)
    
    overall = result["score"]
    grade = result["grade"]
    score_url = result["score_url"]
    
    print()
    print(f"  🦞 RateMyClaw Score: {overall}/100  (Grade: {grade})")
    print(f"  {'━' * 40}")
    print()
    print(f"  🔗 View full breakdown: {score_url}")
    print()


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        path = sys.argv[1]
    else:
        path = str(Path(__file__).parent.parent / "generated_profile.json")
    
    if not os.path.exists(path):
        print(f"❌ Profile not found: {path}")
        print("   Run profile_generator.py first")
        sys.exit(1)
    
    submit(path)
