"""
Submit a generated profile to RateMyClaw API.
Generates a privacy-preserving embedding locally before submission.

Requirements:
    pip install sentence-transformers
    
Usage:
    RATEMYCLAW_API_KEY=your-key python3 submit_profile.py [profile.json]
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "https://ratemyclaw.com"
KEY_FILE = Path(__file__).parent.parent.parent.parent / ".secrets" / "ratemyclaw.env"


def get_or_create_key() -> str:
    """Get saved API key or silently generate a new one."""
    # Check env var first
    env_key = os.environ.get("RATEMYCLAW_API_KEY", "")
    if env_key.startswith("rmc_"):
        return env_key
    
    # Check saved key file
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text().splitlines():
            if line.startswith("RATEMYCLAW_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key.startswith("rmc_"):
                    return key
    
    # Generate new key silently
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
        print("  ✓ Key saved")
        return key
    except Exception as e:
        print(f"  ❌ Could not generate key: {e}")
        sys.exit(1)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def generate_embedding(profile: dict) -> list[float]:
    """Generate a 384-dim embedding locally from workspace summary text.
    
    The text is generated from the profile + any local context,
    then embedded using sentence-transformers. The text NEVER leaves
    this machine — only the resulting float array is submitted.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("⚠️  Installing sentence-transformers (one-time, ~80MB)...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "sentence-transformers", "-q"])
        from sentence_transformers import SentenceTransformer
    
    # Build a rich text summary from the profile
    # This captures the semantic meaning of the workspace
    parts = []
    
    for key in ["domains", "tools", "patterns", "integrations"]:
        vals = profile.get(key, [])
        if vals:
            parts.append(f"{key}: {', '.join(vals)}")
    
    if profile.get("skills_installed"):
        parts.append(f"installed skills: {', '.join(profile['skills_installed'])}")
    
    parts.append(f"automation level: {profile.get('automation_level', 'unknown')}")
    parts.append(f"stage: {profile.get('stage', 'unknown')}")
    
    # If there's a workspace summary from the profile generator, include it
    if profile.get("_workspace_summary"):
        parts.append(profile["_workspace_summary"])
    
    text = ". ".join(parts)
    
    model = SentenceTransformer(EMBEDDING_MODEL)
    embedding = model.encode(text).tolist()
    
    print(f"  ✓ Generated {len(embedding)}-dim embedding locally (text never left this machine)")
    return embedding


def submit(profile_path: str):
    API_KEY = get_or_create_key()
    
    with open(profile_path) as f:
        profile = json.load(f)
    
    print("🔐 Generating embedding locally...")
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
    
    print("📤 Submitting profile (tags + embedding only, no raw content)...")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API_BASE}/v1/profile",
        data=data,
        headers={
            "Authorization": f"Bearer {API_KEY}",
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
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = str(Path(__file__).parent.parent / "generated_profile.json")
    
    if not os.path.exists(path):
        print(f"❌ Profile not found: {path}")
        print("   Run profile_generator.py first")
        sys.exit(1)
    
    submit(path)
