"""
Warstwa SQLite dla carousel_factory.

Tabele:
  - brands           : wiele marek per uzytkownik
  - brand_briefs     : 1:1 z brand, zawiera awatary/USP/oferta (JSON)
  - style_profiles   : N per brand, biblioteka styli z reference images
  - topics           : kolejka tematow do wygenerowania
  - carousels        : wygenerowane karuzele + status publikacji
  - posts_log        : log publikacji (per platform)
  - usage_log        : daily quota tracking dla image generation
"""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    niche TEXT,
    language TEXT DEFAULT 'pl',
    social_handles TEXT,         -- JSON {"ig": "@x", "tiktok": "@x"}
    brief_completion REAL DEFAULT 0.0,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brand_briefs (
    brand_id TEXT PRIMARY KEY,
    product TEXT,
    product_type TEXT,           -- 'digital_ebook' | 'digital_course' | 'physical' | 'service' | 'saas' | 'coaching' | 'affiliate' | 'other'
    offer TEXT,
    price REAL,
    currency TEXT DEFAULT 'PLN',
    price_anchor REAL,           -- przekreslona "stara" cena (efekt okazji)
    main_promise TEXT,           -- 1-zdaniowa obietnica produktu
    usps TEXT,                   -- JSON list[str]
    avatars TEXT,                -- JSON list[{"name","pains","goals"}]
    objections TEXT,             -- JSON list[str]
    guarantees TEXT,             -- JSON list[str]
    urgency_hooks TEXT,          -- JSON list[str] (pilnosc/scarcity)
    voice_tone TEXT,
    social_proof TEXT,           -- JSON list[str]
    forbidden_claims TEXT,       -- JSON list[str] (np. medyczne, income claims)
    cta_url TEXT,                -- link do strony/oferty (uzyte w CTA slajdzie)
    cta_text TEXT,               -- tekst CTA np. "Klik link w bio"
    copy_framework TEXT DEFAULT 'default',  -- 'default' | 'viral_loop' (struktura promptu copywritera)
    raw_research TEXT,           -- JSON dump z auto-researcha
    updated_at TEXT,
    FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS style_profiles (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    name TEXT NOT NULL,
    palette TEXT,                -- JSON list of hex colors
    typography TEXT,             -- JSON {"headline","body","case"}
    layout_patterns TEXT,        -- JSON list[str]
    hook_formulas TEXT,          -- JSON list[str]
    composition_notes TEXT,
    image_style TEXT,            -- string: prompt-ready opis stylu wizualnego
    mood TEXT,                   -- string: ogolny nastroj
    palette_description TEXT,    -- string: opis palety
    tagline_pattern TEXT,        -- string: patterny tekstu
    cta_style TEXT,              -- string: styl CTA
    reference_image_paths TEXT,  -- JSON list[str]
    extracted_summary TEXT,
    is_preferred INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    source TEXT,                 -- 'ai_invented' | 'comment_mining' | 'viral_replicator' | 'manual'
    prompt TEXT,
    source_url TEXT,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'queued', -- queued | generating | ready | posted | failed | skipped
    scheduled_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS carousels (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL,
    style_id TEXT,
    topic_id TEXT,
    slides TEXT,                 -- JSON list[{"order","headline","body","image_path","image_provider"}]
    caption TEXT,
    hashtags TEXT,               -- JSON list[str]
    status TEXT DEFAULT 'draft', -- draft | scheduled | posted | failed | waiting_quota
    scheduled_at TEXT,
    posted_at TEXT,
    ig_post_id TEXT,
    tt_post_id TEXT,
    insights TEXT,               -- JSON {"ig":{...},"tt":{...}}
    source TEXT,                 -- 'manual' | 'automation' | 'viral_replicator'
    source_url TEXT,             -- URL viralu (gdy source='viral_replicator')
    created_at TEXT NOT NULL,
    FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE,
    FOREIGN KEY (style_id) REFERENCES style_profiles(id) ON DELETE SET NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS posts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carousel_id TEXT,
    platform TEXT,               -- 'instagram' | 'tiktok'
    publisher TEXT,              -- 'instagrapi' | 'graph_api' | 'tiktok_api'
    post_id TEXT,
    posted_at TEXT,
    status TEXT,
    error TEXT,
    FOREIGN KEY (carousel_id) REFERENCES carousels(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- YYYY-MM-DD UTC
    provider TEXT NOT NULL,      -- 'openai' | 'gemini' | 'replicate' | 'anthropic'
    model TEXT,
    images_generated INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    UNIQUE(date, provider, model)
);

CREATE INDEX IF NOT EXISTS idx_topics_brand_status ON topics(brand_id, status);
CREATE INDEX IF NOT EXISTS idx_carousels_brand_status ON carousels(brand_id, status);
CREATE INDEX IF NOT EXISTS idx_styles_brand ON style_profiles(brand_id);
CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_log(date, provider);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_style_profiles(conn)
        _migrate_carousels(conn)
        _migrate_brand_briefs(conn)
        _migrate_brands_automation(conn)


def _migrate_brands_automation(conn):
    """Dodaje kolumny automatyzacji do brands."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(brands)").fetchall()}
    new_cols = {
        "auto_enabled": "INTEGER DEFAULT 0",
        "auto_posts_per_day": "INTEGER DEFAULT 3",
        "auto_days_ahead": "INTEGER DEFAULT 7",
        "auto_style_id": "TEXT",
        "auto_ig_account_ids": "TEXT",   # JSON list[str]
        "auto_tt_account_ids": "TEXT",   # JSON list[str]
        "auto_language": "TEXT DEFAULT 'pl'",
        "auto_model": "TEXT DEFAULT 'nano_banana_pro'",
        "auto_last_run": "TEXT",
    }
    for col, col_type in new_cols.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE brands ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


def _migrate_brand_briefs(conn):
    """Dodaje brakujace kolumny do brand_briefs dla starszych baz."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(brand_briefs)").fetchall()}
    new_cols = {
        "product_type": "TEXT",
        "price_anchor": "REAL",
        "main_promise": "TEXT",
        "urgency_hooks": "TEXT",
        "cta_text": "TEXT",
        "icp_summary": "TEXT",
        "icp_channels": "TEXT",       # JSON list[str]
        "anti_avatar": "TEXT",
        "copy_framework": "TEXT DEFAULT 'default'",
        "text_settings": "TEXT",  # JSON: rozmiary fontu, kolory, stroke, pozycja, font, length, smart_fitting
    }
    for col, col_type in new_cols.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE brand_briefs ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


def _migrate_carousels(conn):
    """Dodaje brakujące kolumny do carousels dla starszych baz."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(carousels)").fetchall()}
    new_cols = {
        "publer_post_id": "TEXT",
        "source": "TEXT",          # 'manual' | 'automation' | 'viral_replicator'
        "source_url": "TEXT",      # URL viralu gdy source='viral_replicator'
    }
    for col, col_type in new_cols.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE carousels ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


def _migrate_style_profiles(conn):
    """Dodaje brakujace kolumny do style_profiles dla starszych baz."""
    existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(style_profiles)").fetchall()}
    new_cols = {
        "image_style": "TEXT",
        "mood": "TEXT",
        "palette_description": "TEXT",
        "tagline_pattern": "TEXT",
        "cta_style": "TEXT",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE style_profiles ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row, json_fields: list[str]) -> dict:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and d[f]:
            try:
                d[f] = json.loads(d[f])
            except Exception:
                pass
    return d


# ─────────────────────────────────────────────────────────────
# BRANDS
# ─────────────────────────────────────────────────────────────

def create_brand(brand_id: str, name: str, niche: str = "", language: str = "pl",
                  social_handles: dict = None) -> dict:
    ts = now_iso()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO brands (id, name, niche, language, social_handles, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (brand_id, name, niche, language,
              json.dumps(social_handles or {}, ensure_ascii=False), ts, ts))
    return get_brand(brand_id)


def get_brand(brand_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM brands WHERE id = ?", (brand_id,)).fetchone()
    return _row_to_dict(row, ["social_handles"])


def list_brands(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM brands"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY updated_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_dict(r, ["social_handles"]) for r in rows]


def update_brand(brand_id: str, **fields):
    if not fields:
        return
    fields["updated_at"] = now_iso()
    if "social_handles" in fields and isinstance(fields["social_handles"], dict):
        fields["social_handles"] = json.dumps(fields["social_handles"], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [brand_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE brands SET {cols} WHERE id = ?", vals)


def delete_brand(brand_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM brands WHERE id = ?", (brand_id,))


# ─────────────────────────────────────────────────────────────
# BRAND BRIEFS
# ─────────────────────────────────────────────────────────────

_BRIEF_JSON_FIELDS = ["usps", "avatars", "objections", "guarantees",
                       "social_proof", "forbidden_claims", "raw_research",
                       "urgency_hooks", "icp_channels", "text_settings"]


def upsert_brief(brand_id: str, brief: dict):
    """Insert lub update brief. brief moze zawierac dowolne pola brand_briefs."""
    payload = dict(brief)
    payload["brand_id"] = brand_id
    payload["updated_at"] = now_iso()

    for f in _BRIEF_JSON_FIELDS:
        if f in payload and not isinstance(payload[f], str):
            payload[f] = json.dumps(payload[f], ensure_ascii=False)

    # Catch-all: serialize any remaining dict/list that SQLite can't store natively
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            payload[k] = json.dumps(v, ensure_ascii=False)

    cols = list(payload.keys())
    placeholders = ", ".join("?" * len(cols))
    update_set = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "brand_id")

    sql = f"""
        INSERT INTO brand_briefs ({", ".join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(brand_id) DO UPDATE SET {update_set}
    """
    with get_conn() as conn:
        conn.execute(sql, list(payload.values()))

    _recompute_brief_completion(brand_id)


def get_brief(brand_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM brand_briefs WHERE brand_id = ?",
                           (brand_id,)).fetchone()
    return _row_to_dict(row, _BRIEF_JSON_FIELDS)


def _recompute_brief_completion(brand_id: str):
    """Liczy kompletnosc briefa jako % wypelnionych pol."""
    brief = get_brief(brand_id) or {}
    required = ["product", "offer", "usps", "avatars", "voice_tone",
                "objections", "guarantees", "cta_url"]
    filled = sum(1 for k in required if brief.get(k))
    completion = round(filled / len(required), 2)
    update_brand(brand_id, brief_completion=completion)


# ─────────────────────────────────────────────────────────────
# STYLE PROFILES
# ─────────────────────────────────────────────────────────────

_STYLE_JSON_FIELDS = ["palette", "typography", "layout_patterns",
                       "hook_formulas", "reference_image_paths"]


def create_style(style_id: str, brand_id: str, name: str, profile: dict) -> dict:
    payload = {
        "id": style_id,
        "brand_id": brand_id,
        "name": name,
        "palette": json.dumps(profile.get("palette", []), ensure_ascii=False),
        "typography": json.dumps(profile.get("typography", {}), ensure_ascii=False),
        "layout_patterns": json.dumps(profile.get("layout_patterns", []), ensure_ascii=False),
        "hook_formulas": json.dumps(profile.get("hook_formulas", []), ensure_ascii=False),
        "composition_notes": profile.get("composition_notes", ""),
        "image_style": profile.get("image_style", ""),
        "mood": profile.get("mood", ""),
        "palette_description": profile.get("palette_description", ""),
        "tagline_pattern": profile.get("tagline_pattern", ""),
        "cta_style": profile.get("cta_style", ""),
        "reference_image_paths": json.dumps(profile.get("reference_image_paths", []),
                                              ensure_ascii=False),
        "extracted_summary": profile.get("extracted_summary", ""),
        "is_preferred": int(profile.get("is_preferred", 0)),
        "created_at": now_iso(),
    }
    cols = list(payload.keys())
    sql = f"INSERT INTO style_profiles ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    with get_conn() as conn:
        conn.execute(sql, list(payload.values()))
    return get_style(style_id)


def get_style(style_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM style_profiles WHERE id = ?",
                           (style_id,)).fetchone()
    return _row_to_dict(row, _STYLE_JSON_FIELDS)


def list_styles(brand_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM style_profiles WHERE brand_id = ?
            ORDER BY is_preferred DESC, created_at DESC
        """, (brand_id,)).fetchall()
    return [_row_to_dict(r, _STYLE_JSON_FIELDS) for r in rows]


def update_style(style_id: str, **fields):
    for f in _STYLE_JSON_FIELDS:
        if f in fields and not isinstance(fields[f], str):
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [style_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE style_profiles SET {cols} WHERE id = ?", vals)


def delete_style(style_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM style_profiles WHERE id = ?", (style_id,))


# ─────────────────────────────────────────────────────────────
# TOPICS
# ─────────────────────────────────────────────────────────────

def create_topic(topic_id: str, brand_id: str, source: str, prompt: str,
                  source_url: str = "", priority: int = 5,
                  scheduled_at: Optional[str] = None) -> dict:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO topics (id, brand_id, source, prompt, source_url, priority,
                                  scheduled_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, brand_id, source, prompt, source_url, priority,
              scheduled_at, now_iso()))
    return get_topic(topic_id)


def get_topic(topic_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return _row_to_dict(row, [])


def list_topics(brand_id: str, status: Optional[str] = None) -> list[dict]:
    if status:
        sql = "SELECT * FROM topics WHERE brand_id = ? AND status = ? ORDER BY priority DESC, created_at"
        params = (brand_id, status)
    else:
        sql = "SELECT * FROM topics WHERE brand_id = ? ORDER BY priority DESC, created_at"
        params = (brand_id,)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r, []) for r in rows]


def update_topic_status(topic_id: str, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))


# ─────────────────────────────────────────────────────────────
# CAROUSELS
# ─────────────────────────────────────────────────────────────

_CAROUSEL_JSON_FIELDS = ["slides", "hashtags", "insights"]


def create_carousel(carousel_id: str, brand_id: str, style_id: Optional[str],
                     topic_id: Optional[str], slides: list[dict],
                     caption: str, hashtags: list[str]) -> dict:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO carousels (id, brand_id, style_id, topic_id, slides, caption,
                                     hashtags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (carousel_id, brand_id, style_id, topic_id,
              json.dumps(slides, ensure_ascii=False),
              caption,
              json.dumps(hashtags, ensure_ascii=False),
              now_iso()))
    return get_carousel(carousel_id)


def get_carousel(carousel_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM carousels WHERE id = ?",
                           (carousel_id,)).fetchone()
    return _row_to_dict(row, _CAROUSEL_JSON_FIELDS)


def list_carousels(brand_id: str, status: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
    if status:
        sql = "SELECT * FROM carousels WHERE brand_id = ? AND status = ? ORDER BY created_at DESC LIMIT ?"
        params = (brand_id, status, limit)
    else:
        sql = "SELECT * FROM carousels WHERE brand_id = ? ORDER BY created_at DESC LIMIT ?"
        params = (brand_id, limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r, _CAROUSEL_JSON_FIELDS) for r in rows]


def update_carousel(carousel_id: str, **fields):
    for f in _CAROUSEL_JSON_FIELDS:
        if f in fields and not isinstance(fields[f], str):
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [carousel_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE carousels SET {cols} WHERE id = ?", vals)


def delete_carousel(carousel_id: str):
    """Permanentnie usuwa karuzelę z bazy danych."""
    with get_conn() as conn:
        conn.execute("DELETE FROM carousels WHERE id = ?", (carousel_id,))


# ─────────────────────────────────────────────────────────────
# USAGE TRACKING (image gen quotas)
# ─────────────────────────────────────────────────────────────

def increment_usage(provider: str, model: str, images: int = 0,
                     tokens: int = 0, cost: float = 0.0):
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO usage_log (date, provider, model, images_generated, tokens_used, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, provider, model) DO UPDATE SET
                images_generated = images_generated + excluded.images_generated,
                tokens_used = tokens_used + excluded.tokens_used,
                cost_usd = cost_usd + excluded.cost_usd
        """, (today, provider, model, images, tokens, cost))


def get_today_usage(provider: str, model: str = None) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        if model:
            row = conn.execute("""
                SELECT images_generated, tokens_used, cost_usd FROM usage_log
                WHERE date = ? AND provider = ? AND model = ?
            """, (today, provider, model)).fetchone()
        else:
            row = conn.execute("""
                SELECT SUM(images_generated) as images_generated,
                       SUM(tokens_used) as tokens_used,
                       SUM(cost_usd) as cost_usd
                FROM usage_log WHERE date = ? AND provider = ?
            """, (today, provider)).fetchone()
    if row is None:
        return {"images_generated": 0, "tokens_used": 0, "cost_usd": 0.0}
    return {
        "images_generated": row["images_generated"] or 0,
        "tokens_used": row["tokens_used"] or 0,
        "cost_usd": row["cost_usd"] or 0.0,
    }


def get_today_total_cost() -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT SUM(cost_usd) as total FROM usage_log WHERE date = ?
        """, (today,)).fetchone()
    return (row["total"] or 0.0) if row else 0.0


# ─────────────────────────────────────────────────────────────
# AUTOMATION CONFIG
# ─────────────────────────────────────────────────────────────

_AUTO_JSON_FIELDS = ["auto_ig_account_ids", "auto_tt_account_ids"]


def get_automation_config(brand_id: str) -> dict:
    """Zwraca pola automatyzacji z tabeli brands."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM brands WHERE id = ?", (brand_id,)).fetchone()
    d = _row_to_dict(row, _AUTO_JSON_FIELDS + ["social_handles"]) or {}
    return {k: d[k] for k in d if k.startswith("auto_")} if d else {}


def update_automation_config(brand_id: str, **fields):
    """Aktualizuje pola automatyzacji w tabeli brands."""
    if not fields:
        return
    for f in _AUTO_JSON_FIELDS:
        if f in fields and isinstance(fields[f], (list, dict)):
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [brand_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE brands SET {cols} WHERE id = ?", vals)
