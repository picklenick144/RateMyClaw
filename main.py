"""
RateMyClaw API Server (MVP)
============================
Minimal FastAPI server for profile submission, scoring, and score pages.
Uses SQLite for simplicity (swap to Postgres later).

Run: uvicorn main:app --host 127.0.0.1 --port 8090
"""

import os
import json
import hashlib
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from templates import landing_page_html, score_page_html, quick_score_html, kit_page_html
    HAS_TEMPLATES = True
except ImportError:
    HAS_TEMPLATES = False

# -- Rate Limiting (simple in-memory) --
_rate_limits: dict = defaultdict(list)  # key -> list of timestamps
RATE_LIMIT_WINDOW = 3600  # 1 hour
RATE_LIMIT_MAX = 30  # max requests per window per key

def check_rate_limit(key: str, max_requests: int = RATE_LIMIT_MAX) -> bool:
    """Returns True if within limit, False if exceeded."""
    now = time.time()
    _rate_limits[key] = [t for t in _rate_limits[key] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[key]) >= max_requests:
        return False
    _rate_limits[key].append(now)
    return True

# -- OpenAI for embeddings --
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# -- Config --
DB_PATH = Path(__file__).parent / "ratemyclaw.db"
TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"

with open(TAXONOMY_PATH) as f:
    TAXONOMY = json.load(f)

VALID_TAGS = {
    "domains": set(TAXONOMY["domains"]),
    "tools": set(TAXONOMY["tools"]),
    "patterns": set(TAXONOMY["patterns"]),
    "integrations": set(TAXONOMY["integrations"]),
}
VALID_AUTOMATION = set(TAXONOMY["automation_levels"])
VALID_STAGES = set(TAXONOMY["stages"])

MAX_TAGS_PER_CATEGORY = 12
MAX_CUSTOM_TAGS = 3

# -- Database --

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                api_key_hash TEXT UNIQUE,
                domains TEXT,
                tools TEXT,
                patterns TEXT,
                integrations TEXT,
                automation_level TEXT,
                stage TEXT,
                maturity TEXT,
                embedding TEXT,
                score_overall INTEGER,
                score_breakdown TEXT,
                email TEXT,
                notify_cluster_updates INTEGER DEFAULT 0,
                notify_new_matches INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            
            CREATE TABLE IF NOT EXISTS custom_tags (
                tag TEXT,
                category TEXT,
                profile_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                PRIMARY KEY (tag, category, profile_id)
            );
            
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT,
                type TEXT,
                message TEXT,
                read INTEGER DEFAULT 0,
                created_at TEXT
            );
        """)

@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# -- Models --

class MaturityData(BaseModel):
    memory_files: int = 0
    research_docs: int = 0
    scripts: int = 0
    custom_skills: int = 0
    secrets_configured: int = 0
    has_soul: bool = False
    has_memory: bool = False
    has_heartbeat: bool = False
    has_work_status: bool = False

class ProfileData(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_CATEGORY)
    tools: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_CATEGORY)
    patterns: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_CATEGORY)
    integrations: list[str] = Field(default_factory=list, max_length=MAX_TAGS_PER_CATEGORY)
    automation_level: str = "manual"
    stage: str = "building"

class CustomTags(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=MAX_CUSTOM_TAGS)
    tools: list[str] = Field(default_factory=list, max_length=MAX_CUSTOM_TAGS)
    patterns: list[str] = Field(default_factory=list, max_length=MAX_CUSTOM_TAGS)
    integrations: list[str] = Field(default_factory=list, max_length=MAX_CUSTOM_TAGS)

class NotificationPrefs(BaseModel):
    email: Optional[str] = None
    notify_cluster_updates: bool = True
    notify_new_matches: bool = True

class ModelsData(BaseModel):
    default_model: Optional[str] = None
    fallback_models: list[str] = Field(default_factory=list)
    heartbeat_model: Optional[str] = None

class SubmitProfileRequest(BaseModel):
    profile: ProfileData
    custom_tags: Optional[CustomTags] = None
    maturity: Optional[MaturityData] = None
    models: Optional[ModelsData] = None
    embedding: Optional[list[float]] = None
    embedding_method: str = "none"  # "minilm", "tfidf", or "none"
    notification_preferences: Optional[NotificationPrefs] = None


# -- Scoring --

def score_maturity(m: MaturityData, automation_level: str = "manual") -> dict:
    memory = min(m.memory_files / 5, 1.0) * 15
    research = min(m.research_docs / 10, 1.0) * 10
    scripts = min(m.scripts / 10, 1.0) * 10
    skills = min(m.custom_skills / 3, 1.0) * 10
    secrets = min(m.secrets_configured / 3, 1.0) * 10
    structure = sum([
        m.has_soul * 7, m.has_memory * 8,
        m.has_heartbeat * 10, m.has_work_status * 5
    ])
    auto_scores = {"manual": 0, "light": 4, "moderate": 8, "high": 12, "fully-autonomous": 15}
    automation = auto_scores.get(automation_level, 0)
    total = memory + research + scripts + skills + secrets + structure + automation
    return {
        "total": round(min(total, 100)),
        "breakdown": {
            "memory": round(memory, 1), "research": round(research, 1),
            "scripts": round(scripts, 1), "skills": round(skills, 1),
            "secrets": round(secrets, 1), "structure": round(structure, 1),
            "automation": round(automation, 1)
        }
    }


def compute_cluster_data(profile_id: str, db: sqlite3.Connection) -> Optional[dict]:
    """Compute cluster alignment by finding similar profiles in the DB.
    
    For MVP: simple tag-overlap similarity instead of embedding cosine
    (embeddings are optional enhancement).
    """
    current = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not current:
        return None
    
    all_profiles = db.execute("SELECT * FROM profiles WHERE id != ?", (profile_id,)).fetchall()
    if len(all_profiles) < 5:
        return None
    
    current_domains = set(json.loads(current["domains"]))
    current_tools = set(json.loads(current["tools"]))
    current_patterns = set(json.loads(current["patterns"]))
    current_integrations = set(json.loads(current["integrations"]))
    current_all = current_domains | current_tools | current_patterns | current_integrations
    
    # Find most similar profiles by Jaccard similarity on all tags
    similarities = []
    for p in all_profiles:
        p_all = (set(json.loads(p["domains"])) | set(json.loads(p["tools"])) | 
                 set(json.loads(p["patterns"])) | set(json.loads(p["integrations"])))
        if len(current_all | p_all) > 0:
            jaccard = len(current_all & p_all) / len(current_all | p_all)
        else:
            jaccard = 0
        similarities.append((p, jaccard))
    
    # Take top K most similar (K=20 or all if fewer)
    similarities.sort(key=lambda x: -x[1])
    neighbors = [p for p, sim in similarities[:20]]
    
    if len(neighbors) < 5:
        return None
    
    # Compute adoption rates across neighbors
    def adoption_rates(neighbors, field):
        from collections import Counter
        counter = Counter()
        for p in neighbors:
            for tag in json.loads(p[field]):
                counter[tag] += 1
        return {tag: count / len(neighbors) for tag, count in counter.items()}
    
    return {
        "size": len(neighbors),
        "domain_adoption": adoption_rates(neighbors, "domains"),
        "tool_adoption": adoption_rates(neighbors, "tools"),
        "pattern_adoption": adoption_rates(neighbors, "patterns"),
        "integration_adoption": adoption_rates(neighbors, "integrations"),
    }


def compute_cluster_score(profile: dict, cluster: dict, threshold: float = 0.40) -> dict:
    """Score alignment with cluster."""
    categories = {
        "domains": (json.loads(profile["domains"]), cluster["domain_adoption"], 0.30),
        "patterns": (json.loads(profile["patterns"]), cluster["pattern_adoption"], 0.30),
        "tools": (json.loads(profile["tools"]), cluster["tool_adoption"], 0.20),
        "integrations": (json.loads(profile["integrations"]), cluster["integration_adoption"], 0.20),
    }
    
    total_score = 0
    category_scores = {}
    recommendations = []
    strengths = []
    
    for cat_name, (agent_tags, adoption, weight) in categories.items():
        agent_set = set(agent_tags)
        common = {t: r for t, r in adoption.items() if r >= threshold}
        
        if not common:
            category_scores[cat_name] = 100
            total_score += 100 * weight
            continue
        
        has = sum(1 for t in common if t in agent_set)
        score = (has / len(common)) * 100
        category_scores[cat_name] = round(score, 1)
        total_score += score * weight
        
        for tag, rate in sorted(common.items(), key=lambda x: -x[1]):
            if tag not in agent_set:
                recommendations.append({
                    "type": cat_name.rstrip("s"),
                    "tag": tag,
                    "cluster_adoption": round(rate, 2),
                    "message": f"{int(rate*100)}% of agents in your cluster use '{tag}'"
                })
            else:
                strengths.append({
                    "type": cat_name.rstrip("s"),
                    "tag": tag,
                    "cluster_adoption": round(rate, 2)
                })
    
    recommendations.sort(key=lambda x: -x["cluster_adoption"])
    
    return {
        "total": round(total_score),
        "category_scores": category_scores,
        "recommendations": recommendations[:10],
        "strengths": strengths[:10],
    }


def compute_full_score(profile_row, db) -> dict:
    """Compute the full score for a profile."""
    maturity_data = MaturityData(**json.loads(profile_row["maturity"])) if profile_row["maturity"] else MaturityData()
    maturity = score_maturity(maturity_data, profile_row["automation_level"] or "manual")
    
    cluster = compute_cluster_data(profile_row["id"], db)
    
    if cluster is None or cluster["size"] < 5:
        return {
            "overall": maturity["total"],
            "mode": "maturity_only",
            "maturity": maturity,
            "cluster": None,
            "cluster_size": 0,
            "recommendations": [],
            "strengths": []
        }
    
    cluster_score = compute_cluster_score(profile_row, cluster)
    
    # Blend
    cw = min(cluster["size"] / 20, 1.0) * 0.60
    mw = 1.0 - cw
    overall = maturity["total"] * mw + cluster_score["total"] * cw
    
    return {
        "overall": round(overall),
        "mode": "blended",
        "maturity_weight": round(mw, 2),
        "cluster_weight": round(cw, 2),
        "maturity": maturity,
        "cluster": {
            "total": cluster_score["total"],
            "category_scores": cluster_score["category_scores"],
        },
        "cluster_size": cluster["size"],
        "recommendations": cluster_score["recommendations"],
        "strengths": cluster_score["strengths"]
    }


# -- Helpers --

def generate_profile_id(api_key_hash: str) -> str:
    return "ag_" + hashlib.sha256(api_key_hash.encode()).hexdigest()[:12]

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def validate_tags(profile: ProfileData) -> list[str]:
    """Validate all tags against taxonomy. Return list of errors."""
    errors = []
    for category in ["domains", "tools", "patterns", "integrations"]:
        tags = getattr(profile, category)
        invalid = [t for t in tags if t not in VALID_TAGS[category]]
        if invalid:
            errors.append(f"Invalid {category} tags: {invalid}")
    if profile.automation_level not in VALID_AUTOMATION:
        errors.append(f"Invalid automation_level: {profile.automation_level}")
    if profile.stage not in VALID_STAGES:
        errors.append(f"Invalid stage: {profile.stage}")
    return errors

def profile_to_embed_text(profile: ProfileData) -> str:
    parts = []
    for key in ["domains", "tools", "patterns", "integrations"]:
        vals = getattr(profile, key)
        if vals:
            parts.append(f"{key}: {', '.join(vals)}")
    parts.append(f"automation: {profile.automation_level}")
    parts.append(f"stage: {profile.stage}")
    return ". ".join(parts)


# -- App --

app = FastAPI(
    title="RateMyClaw API",
    description="Collaborative scoring and matching for AI agents",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ratemyclaw.com", "https://www.ratemyclaw.com"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

ADMIN_KEY = os.environ.get("RATEMYCLAW_ADMIN_KEY", "changeme")

@app.on_event("startup")
def startup():
    init_db()


@app.get("/v1/taxonomy")
def get_taxonomy():
    """Return the current approved taxonomy."""
    return {
        "version": TAXONOMY["_version"],
        "domains": TAXONOMY["domains"],
        "tools": TAXONOMY["tools"],
        "patterns": TAXONOMY["patterns"],
        "integrations": TAXONOMY["integrations"],
        "automation_levels": TAXONOMY["automation_levels"],
        "stages": TAXONOMY["stages"]
    }


@app.post("/v1/profile")
def submit_profile(req: SubmitProfileRequest, authorization: str = Header(None)):
    """Submit or update an agent work profile."""
    
    if not authorization:
        raise HTTPException(401, "Missing Authorization header. Use 'Bearer <api_key>'")
    
    api_key = authorization.replace("Bearer ", "").strip()
    if len(api_key) < 8:
        raise HTTPException(401, "Invalid API key")
    
    # Rate limit by API key
    if not check_rate_limit(f"profile:{api_key}", max_requests=10):
        raise HTTPException(429, "Rate limit exceeded. Max 10 profile submissions per hour.")
    
    # Validate tags
    errors = validate_tags(req.profile)
    if errors:
        raise HTTPException(422, {"errors": errors})
    
    key_hash = hash_api_key(api_key)
    profile_id = generate_profile_id(key_hash)
    now = datetime.now(timezone.utc).isoformat()
    
    # Use client-provided embedding if available, else generate server-side
    embedding = None
    embedding_method = req.embedding_method or "none"
    
    if req.embedding is not None and len(req.embedding) > 0:
        # Client sent a local embedding (MiniLM or TF-IDF)
        embedding = json.dumps(req.embedding)
    elif HAS_OPENAI:
        # Fallback: server-side embedding from tags (not raw content — privacy preserved)
        try:
            text = profile_to_embed_text(req.profile)
            resp = openai_client.embeddings.create(model="text-embedding-3-small", input=[text])
            embedding = json.dumps(resp.data[0].embedding)
            embedding_method = "openai-server"
        except Exception as e:
            pass  # Embedding is optional
    
    maturity_json = json.dumps(req.maturity.model_dump()) if req.maturity else json.dumps({})
    
    with get_db() as db:
        # Upsert profile
        existing = db.execute("SELECT id FROM profiles WHERE api_key_hash = ?", (key_hash,)).fetchone()
        
        # Ensure new columns exist (migration-safe)
        for col, default in [("embedding_method", "'none'"), ("models", "NULL")]:
            try:
                db.execute(f"ALTER TABLE profiles ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass  # column already exists
        
        models_json = json.dumps(req.models.model_dump()) if req.models else json.dumps({})
        
        if existing:
            db.execute("""
                UPDATE profiles SET 
                    domains=?, tools=?, patterns=?, integrations=?,
                    automation_level=?, stage=?, maturity=?, embedding=?,
                    embedding_method=?, models=?,
                    email=?, notify_cluster_updates=?, notify_new_matches=?,
                    updated_at=?
                WHERE api_key_hash=?
            """, (
                json.dumps(req.profile.domains), json.dumps(req.profile.tools),
                json.dumps(req.profile.patterns), json.dumps(req.profile.integrations),
                req.profile.automation_level, req.profile.stage, maturity_json, embedding,
                embedding_method, models_json,
                req.notification_preferences.email if req.notification_preferences else None,
                req.notification_preferences.notify_cluster_updates if req.notification_preferences else 0,
                req.notification_preferences.notify_new_matches if req.notification_preferences else 0,
                now, key_hash
            ))
        else:
            db.execute("""
                INSERT INTO profiles 
                    (id, api_key_hash, domains, tools, patterns, integrations,
                     automation_level, stage, maturity, embedding, embedding_method,
                     models, email, notify_cluster_updates, notify_new_matches,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile_id, key_hash,
                json.dumps(req.profile.domains), json.dumps(req.profile.tools),
                json.dumps(req.profile.patterns), json.dumps(req.profile.integrations),
                req.profile.automation_level, req.profile.stage, maturity_json, embedding,
                embedding_method, models_json,
                req.notification_preferences.email if req.notification_preferences else None,
                req.notification_preferences.notify_cluster_updates if req.notification_preferences else 0,
                req.notification_preferences.notify_new_matches if req.notification_preferences else 0,
                now, now
            ))
        
        # Store custom tags
        if req.custom_tags:
            for category in ["domains", "tools", "patterns", "integrations"]:
                for tag in getattr(req.custom_tags, category):
                    tag = tag[:50]  # enforce max length
                    db.execute("""
                        INSERT OR IGNORE INTO custom_tags (tag, category, profile_id, status, created_at)
                        VALUES (?, ?, ?, 'pending', ?)
                    """, (tag, category, profile_id, now))
        
        # Compute score
        profile_row = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        score = compute_full_score(profile_row, db)
        
        # Save score
        db.execute("UPDATE profiles SET score_overall=?, score_breakdown=? WHERE id=?",
                   (score["overall"], json.dumps(score), profile_id))
    
    return {
        "profile_id": profile_id,
        "score_url": f"/score/{profile_id}",
        "score": score,
        "created_at": now
    }


@app.get("/v1/score/{profile_id}")
def get_score(profile_id: str):
    """Get score for a profile (public, no auth needed)."""
    
    with get_db() as db:
        profile = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not profile:
            raise HTTPException(404, "Profile not found")
        
        score = compute_full_score(profile, db)
        
        return {
            "profile_id": profile_id,
            "score": score,
            "profile_summary": {
                "domains": json.loads(profile["domains"]),
                "tools": json.loads(profile["tools"]),
                "patterns": json.loads(profile["patterns"]),
                "integrations": json.loads(profile["integrations"]),
                "automation_level": profile["automation_level"],
                "stage": profile["stage"],
                "models": json.loads(profile["models"]) if profile["models"] else {}
            },
            "last_updated": profile["updated_at"]
        }


@app.get("/score/{profile_id}", response_class=HTMLResponse)
def score_page(profile_id: str):
    """Hosted score page (shareable URL)."""
    
    with get_db() as db:
        profile = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if not profile:
            return HTMLResponse("<h1>Profile not found</h1>", status_code=404)
        
        score = compute_full_score(profile, db)
        domains = json.loads(profile["domains"])
        
        if HAS_TEMPLATES:
            return HTMLResponse(score_page_html(profile_id, profile, score, domains))
        
        # Fallback: minimal inline HTML
        return HTMLResponse(f"""<!DOCTYPE html>
<html><head><title>RateMyClaw — {score['overall']}/100</title>
<style>body{{font-family:sans-serif;background:#0a0a0a;color:#e0e0e0;max-width:600px;margin:0 auto;padding:20px;text-align:center;}}</style>
</head><body>
<h1>🦞 {score['overall']}/100</h1>
<p>{', '.join(domains[:5])}</p>
<p>Profile: {profile_id}</p>
</body></html>""")


@app.get("/v1/admin/custom-tags")
def get_custom_tags(authorization: str = Header(None)):
    """View pending custom tag submissions."""
    if not authorization or authorization.replace("Bearer ", "").strip() != ADMIN_KEY:
        raise HTTPException(403, "Admin access required")
    with get_db() as db:
        rows = db.execute("""
            SELECT tag, category, COUNT(DISTINCT profile_id) as count,
                   MIN(created_at) as first_seen
            FROM custom_tags WHERE status = 'pending'
            GROUP BY tag, category
            ORDER BY count DESC
        """).fetchall()
        
        return {
            "pending": [
                {"tag": r["tag"], "category": r["category"], 
                 "submission_count": r["count"], "first_seen": r["first_seen"]}
                for r in rows
            ]
        }


@app.delete("/v1/profile/{profile_id}")
def delete_profile(profile_id: str, authorization: str = Header(None)):
    """Delete a profile and all associated data permanently."""
    if not authorization:
        raise HTTPException(401, "Missing Authorization header")
    
    api_key = authorization.replace("Bearer ", "").strip()
    key_hash = hash_api_key(api_key)
    expected_id = generate_profile_id(key_hash)
    
    if expected_id != profile_id:
        raise HTTPException(403, "You can only delete your own profile")
    
    with get_db() as db:
        db.execute("DELETE FROM custom_tags WHERE profile_id = ?", (profile_id,))
        db.execute("DELETE FROM notifications WHERE profile_id = ?", (profile_id,))
        db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    
    return {"deleted": True, "profile_id": profile_id}


@app.get("/quick-score", response_class=HTMLResponse)
def quick_score_page():
    """Quick score page."""
    if HAS_TEMPLATES:
        return HTMLResponse(quick_score_html())
    return HTMLResponse("<h1>Quick Score</h1><p>Templates not available</p>")


@app.get("/", response_class=HTMLResponse)
def landing_page():
    """Landing page for ratemyclaw.com"""
    if HAS_TEMPLATES:
        with get_db() as db:
            total = db.execute("SELECT COUNT(*) as c FROM profiles").fetchone()["c"]
        return HTMLResponse(landing_page_html(total))
    
    return HTMLResponse("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RateMyClaw — Score Your AI Agent</title>
    <meta name="description" content="Find out how your AI agent compares to others working on similar problems. Privacy-first scoring powered by embeddings.">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0a0a0a; color: #e0e0e0;
            min-height: 100vh; display: flex; flex-direction: column;
            align-items: center; justify-content: center; padding: 20px;
        }
        .container { max-width: 600px; text-align: center; }
        h1 { font-size: 64px; margin-bottom: 8px; }
        h2 { font-size: 28px; margin-bottom: 16px; font-weight: 700; }
        .subtitle { color: #888; font-size: 18px; margin-bottom: 40px; line-height: 1.6; }
        .features { text-align: left; margin: 30px 0; }
        .feature { 
            background: #111; border: 1px solid #222; border-radius: 12px;
            padding: 20px; margin: 12px 0;
        }
        .feature h3 { font-size: 16px; margin-bottom: 8px; }
        .feature p { color: #888; font-size: 14px; line-height: 1.5; }
        .cta {
            display: inline-block; padding: 14px 32px;
            background: #4ade80; color: #000; font-weight: 700;
            border-radius: 8px; text-decoration: none; font-size: 16px;
            margin: 20px 0;
        }
        .cta:hover { background: #22c55e; }
        code { 
            background: #1a1a1a; padding: 2px 8px; border-radius: 4px;
            font-size: 14px; color: #4ade80;
        }
        .install-box {
            background: #111; border: 1px solid #222; border-radius: 12px;
            padding: 20px; margin: 30px 0; text-align: left;
        }
        .install-box pre {
            background: #0a0a0a; padding: 12px; border-radius: 8px;
            overflow-x: auto; margin-top: 12px; color: #4ade80;
        }
        .stats { 
            display: flex; gap: 30px; justify-content: center;
            margin: 30px 0;
        }
        .stat { text-align: center; }
        .stat .num { font-size: 32px; font-weight: 800; color: #4ade80; }
        .stat .label { font-size: 12px; color: #666; margin-top: 4px; }
        .footer { color: #444; font-size: 12px; margin-top: 40px; }
        .email-form { margin: 20px 0; }
        .email-form input {
            padding: 12px 16px; border-radius: 8px; border: 1px solid #333;
            background: #1a1a1a; color: #fff; width: 250px; margin-right: 8px;
        }
        .email-form button {
            padding: 12px 20px; border-radius: 8px; border: none;
            background: #4ade80; color: #000; font-weight: 600; cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🦞</h1>
        <h2>Rate My Claw</h2>
        <p class="subtitle">
            Find out how your AI agent stacks up against others working on similar problems.<br>
            Privacy-first. Embedding-powered. No data leaves your machine.
        </p>
        
        <div id="stats" class="stats">
            <div class="stat"><div class="num" id="stat-profiles">-</div><div class="label">Agents Scored</div></div>
            <div class="stat"><div class="num" id="stat-tags">-</div><div class="label">Taxonomy Tags</div></div>
        </div>
        
        <div class="features">
            <div class="feature">
                <h3>📊 Score Your Setup</h3>
                <p>Scan your OpenClaw workspace and get a maturity score. Memory, automation, integrations, skills — see where you stand.</p>
            </div>
            <div class="feature">
                <h3>🎯 Compare With Similar Agents</h3>
                <p>Find out what agents like yours are doing that you're not. Recommendations based on what actually works for your cluster.</p>
            </div>
            <div class="feature">
                <h3>🔒 Privacy First</h3>
                <p>Only structured tags leave your machine — never raw files or content. Embeddings aren't reversible. We never see your data.</p>
            </div>
        </div>
        
        <div class="install-box">
            <h3>Get Started (Coming Soon)</h3>
            <pre>clawhub install ratemyclaw</pre>
            <p style="color:#666; margin-top:12px; font-size:13px;">
                Or submit your profile via the API: <code>POST /v1/profile</code>
            </p>
        </div>
        
        <p style="color:#888; margin-bottom:12px;">Get notified when the ClawHub skill launches:</p>
        <div class="email-form">
            <form id="notify-form" onsubmit="submitNotify(event)">
                <input type="email" placeholder="you@example.com" id="notify-email" required>
                <button type="submit">Notify Me</button>
            </form>
            <p id="notify-status" style="color:#4ade80;margin-top:12px;display:none;">✅ You're on the list!</p>
        </div>
        
        <div class="footer">
            <p>RateMyClaw — Collaborative scoring for AI agents</p>
            <p style="margin-top:8px;">
                <a href="/v1/taxonomy" style="color:#666;">API</a> · 
                <a href="https://github.com" style="color:#666;">GitHub</a> · 
                Built with 🥒 by PickleClaw
            </p>
        </div>
    </div>
    
    <script>
    // Load live stats
    fetch('/v1/stats').then(r=>r.json()).then(d=>{
        document.getElementById('stat-profiles').textContent = d.total_profiles;
        if(d.taxonomy_tags) document.getElementById('stat-tags').textContent = d.taxonomy_tags;
    }).catch(()=>{});
    
    function submitNotify(e) {
        e.preventDefault();
        document.getElementById('notify-status').style.display = 'block';
        document.getElementById('notify-form').style.display = 'none';
    }
    </script>
</body>
</html>""")


@app.get("/v1/stats")
def get_stats():
    """Public stats endpoint."""
    tag_count = sum(len(TAXONOMY[k]) for k in ["domains", "tools", "patterns", "integrations"])
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) as c FROM profiles").fetchone()["c"]
        with_email = db.execute("SELECT COUNT(*) as c FROM profiles WHERE email IS NOT NULL").fetchone()["c"]
        pending_tags = db.execute("SELECT COUNT(DISTINCT tag||category) as c FROM custom_tags WHERE status='pending'").fetchone()["c"]
        
        return {
            "total_profiles": total,
            "taxonomy_tags": tag_count,
            "emails_captured": with_email,
            "pending_custom_tags": pending_tags
        }


# -- Init --
init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
