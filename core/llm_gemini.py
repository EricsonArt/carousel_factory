"""
Gemini 2.5 Flash wrapper z API identycznym jak core.llm (Claude).

Dostarcza funkcje text + vision + JSON + tool use oparte o google.genai SDK.
Używamy puli kluczy z config.GEMINI_API_KEYS z auto-rotacją gdy 429 / quota.

Cena (~10× tańsza niż Claude Sonnet):
  Gemini 2.5 Flash: $0.30/MTok input, $2.50/MTok output
  Claude Sonnet 4.6: $3.00/MTok input, $15.00/MTok output
"""
from __future__ import annotations
import base64
import json
import time
from pathlib import Path
from typing import Optional

from config import GEMINI_API_KEYS
from core.utils import extract_json_block, safe_json_loads
from db import increment_usage


# Modele Gemini — używamy 2.5 Flash do wszystkiego (taniej + szybciej)
GEMINI_TEXT_MODEL = "gemini-2.5-flash"
GEMINI_VISION_MODEL = "gemini-2.5-flash"  # multimodal — obsługuje tekst i obrazy
GEMINI_FAST_MODEL = "gemini-2.5-flash"

# Pricing per MTok (input / output)
_GEMINI_PRICE_IN_PER_MTOK = 0.30
_GEMINI_PRICE_OUT_PER_MTOK = 2.50


# ─────────────────────────────────────────────────────────────
# KLIENT + ROTACJA KLUCZY
# ─────────────────────────────────────────────────────────────

_dead_keys: set[str] = set()  # klucze które padły z billing/quota daily
_key_idx = 0


class GeminiError(Exception):
    pass


class GeminiQuotaError(GeminiError):
    """Wszystkie klucze padły z quota."""
    pass


def _next_alive_key() -> Optional[str]:
    global _key_idx
    if not GEMINI_API_KEYS:
        return None
    n = len(GEMINI_API_KEYS)
    for _ in range(n):
        key = GEMINI_API_KEYS[_key_idx % n]
        _key_idx += 1
        if key not in _dead_keys:
            return key
    return None


def _client(api_key: str):
    try:
        from google import genai
    except ImportError:
        raise GeminiError("Brak pakietu google-genai. pip install google-genai")
    return genai.Client(api_key=api_key)


# ─────────────────────────────────────────────────────────────
# IMAGE → PART (vision)
# ─────────────────────────────────────────────────────────────

def _image_to_part(img):
    """Konwertuj ścieżkę/URL/bytes na Part dla Gemini."""
    from google.genai import types
    if isinstance(img, (str, Path)):
        s = str(img)
        if s.startswith(("http://", "https://")):
            import requests
            r = requests.get(s, timeout=30)
            r.raise_for_status()
            data = r.content
            mime = _detect_mime(data) or "image/jpeg"
            return types.Part.from_bytes(mime_type=mime, data=data)
        path = Path(s)
        if not path.exists():
            return None
        data = path.read_bytes()
        mime = _detect_mime(data) or _guess_mime(path.suffix)
        return types.Part.from_bytes(mime_type=mime, data=data)
    if isinstance(img, bytes):
        mime = _detect_mime(img) or "image/jpeg"
        return types.Part.from_bytes(mime_type=mime, data=img)
    return None


def _detect_mime(data: bytes) -> Optional[str]:
    if not data or len(data) < 12:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def _guess_mime(suffix: str) -> str:
    s = suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }.get(s, "image/jpeg")


# ─────────────────────────────────────────────────────────────
# TRACKING
# ─────────────────────────────────────────────────────────────

def _track_usage(model: str, in_tokens: int, out_tokens: int):
    try:
        cost = (in_tokens * _GEMINI_PRICE_IN_PER_MTOK + out_tokens * _GEMINI_PRICE_OUT_PER_MTOK) / 1_000_000
        increment_usage("gemini", model, tokens=(in_tokens + out_tokens), cost=cost)
    except Exception:
        pass


def _extract_text(resp) -> str:
    """Pobiera tekst z odpowiedzi Gemini (bez parts iteration)."""
    if hasattr(resp, "text") and resp.text:
        return resp.text
    # Fallback: zbierz teksty z parts
    chunks = []
    for cand in (resp.candidates or []):
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in (content.parts or []):
            if hasattr(part, "text") and part.text:
                chunks.append(part.text)
    return "".join(chunks)


def _classify_error(exc: Exception) -> str:
    """Zwraca: 'quota_daily' | 'rate_limit' | 'billing' | 'auth' | 'transient' | 'fatal'."""
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return "rate_limit"
    if "quota" in msg and "exceeded" in msg:
        return "quota_daily"
    if "billing" in msg or "payment" in msg:
        return "billing"
    if "api key" in msg or "unauthorized" in msg or "permission" in msg or "401" in msg or "403" in msg:
        return "auth"
    if "503" in msg or "504" in msg or "timeout" in msg or "unavailable" in msg:
        return "transient"
    return "fatal"


# ─────────────────────────────────────────────────────────────
# CALL — text + vision (jednolite)
# ─────────────────────────────────────────────────────────────

def _call_gemini(
    prompt: str,
    images: Optional[list] = None,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.7,
    response_schema: Optional[dict] = None,
) -> str:
    """Wewnętrzne wywołanie Gemini z rotacją kluczy."""
    if not GEMINI_API_KEYS:
        raise GeminiError("Brak GEMINI_API_KEY w konfiguracji.")

    from google.genai import types

    model_id = model or GEMINI_TEXT_MODEL

    # Buduj parts: obrazy + tekst
    parts = []
    if images:
        for img in images:
            p = _image_to_part(img)
            if p is not None:
                parts.append(p)
    parts.append(types.Part.from_text(text=prompt))

    # Config
    cfg_kwargs = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system:
        cfg_kwargs["system_instruction"] = system
    if response_schema:
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = response_schema
    config = types.GenerateContentConfig(**cfg_kwargs)

    keys_tried: list[str] = []
    last_err: Optional[Exception] = None

    while True:
        key = _next_alive_key()
        if not key or key in keys_tried:
            break
        keys_tried.append(key)

        for attempt in range(3):
            try:
                client = _client(key)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=parts,
                    config=config,
                )
                # Track usage (jeśli dostępne w response)
                try:
                    usage = getattr(resp, "usage_metadata", None)
                    if usage:
                        in_tok = getattr(usage, "prompt_token_count", 0) or 0
                        out_tok = getattr(usage, "candidates_token_count", 0) or 0
                        _track_usage(model_id, in_tok, out_tok)
                except Exception:
                    pass

                text = _extract_text(resp)
                if not text and not response_schema:
                    last_err = GeminiError("Gemini zwrócił pustą odpowiedź")
                    time.sleep(1.5)
                    continue
                return text

            except Exception as e:
                last_err = e
                kind = _classify_error(e)
                if kind in ("quota_daily", "billing", "auth"):
                    _dead_keys.add(key)
                    break  # przejdź do następnego klucza
                if kind in ("rate_limit", "transient"):
                    time.sleep(2 + attempt * 2)
                    continue
                # fatal
                raise GeminiError(f"Gemini ({model_id}): {e}") from e

    if last_err:
        kind = _classify_error(last_err)
        if kind in ("quota_daily", "billing", "auth"):
            raise GeminiQuotaError(f"Wszystkie klucze Gemini padły: {last_err}")
        raise GeminiError(f"Gemini fail po {len(keys_tried)} kluczach: {last_err}")
    raise GeminiQuotaError("Brak żywych kluczy Gemini")


# ─────────────────────────────────────────────────────────────
# PUBLIC API — sygnatury 1:1 jak core.llm
# ─────────────────────────────────────────────────────────────

def gemini_text(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    return _call_gemini(prompt, images=None, system=system,
                          max_tokens=max_tokens, model=model, temperature=temperature)


def gemini_vision(
    prompt: str,
    images: list,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.5,
) -> str:
    return _call_gemini(prompt, images=images, system=system,
                          max_tokens=max_tokens, model=model or GEMINI_VISION_MODEL,
                          temperature=temperature)


def gemini_json(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    repair_attempts: int = 1,
) -> dict:
    json_system = (system + "\n\n" if system else "") + \
                  "Odpowiadasz WYŁĄCZNIE poprawnym JSON-em — zero komentarzy, zero markdown."
    raw = _call_gemini(prompt, images=None, system=json_system,
                        max_tokens=max_tokens, model=model)
    parsed = safe_json_loads(extract_json_block(raw))
    if parsed is not None:
        return parsed
    for _ in range(repair_attempts):
        raw2 = _call_gemini(
            f"Popraw JSON na poprawny (zachowaj treść):\n\n{raw}",
            system=json_system, max_tokens=max_tokens, model=model,
        )
        parsed = safe_json_loads(extract_json_block(raw2))
        if parsed is not None:
            return parsed
    raise ValueError(f"Gemini JSON parse failed. Raw: {raw[:500]}")


def gemini_vision_json(
    prompt: str,
    images: list,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    repair_attempts: int = 1,
) -> dict:
    json_system = (system + "\n\n" if system else "") + \
                  "Odpowiadasz WYŁĄCZNIE poprawnym JSON-em — zero komentarzy, zero markdown."
    raw = _call_gemini(prompt, images=images, system=json_system,
                        max_tokens=max_tokens, model=model or GEMINI_VISION_MODEL)
    parsed = safe_json_loads(extract_json_block(raw))
    if parsed is not None:
        return parsed
    for _ in range(repair_attempts):
        raw2 = _call_gemini(
            f"Popraw JSON na poprawny (zachowaj treść):\n\n{raw}",
            system=json_system, max_tokens=max_tokens, model=model,
        )
        parsed = safe_json_loads(extract_json_block(raw2))
        if parsed is not None:
            return parsed
    raise ValueError(f"Gemini Vision JSON parse failed. Raw: {raw[:500]}")


def gemini_vision_with_tool(
    prompt: str,
    images: list,
    tool_name: str,
    tool_description: str,
    tool_input_schema: dict,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.3,
) -> dict:
    """
    Tool-use w Gemini = response_schema (structured output). Wymuszamy konkretny schema
    i parsujemy JSON. Output 1:1 jak Anthropic tool_use: {"input": {...}, "raw_text": ""}.
    """
    raw = _call_gemini(prompt, images=images, system=system,
                        max_tokens=max_tokens,
                        model=model or GEMINI_VISION_MODEL,
                        temperature=temperature,
                        response_schema=tool_input_schema)
    parsed = safe_json_loads(extract_json_block(raw))
    if parsed is None:
        raise ValueError(f"Gemini tool {tool_name} - zła odpowiedź: {raw[:500]}")
    return {"input": parsed, "raw_text": ""}
