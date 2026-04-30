"""
Warstwa LLM: Claude (text + vision), Anthropic SDK.

Eksportowane:
  - call_claude(prompt, system, max_tokens) -> str           # text-only
  - call_claude_vision(prompt, images, system) -> str        # vision (URLs lub bytes)
  - call_claude_json(prompt, system, schema_hint) -> dict    # forsuje JSON output, repair loop
  - validate_against_brief(slides, brief) -> dict            # moderation/anti-hallucination
"""
import base64
import json
from pathlib import Path
from typing import Optional

from config import (
    ANTHROPIC_API_KEY, CLAUDE_TEXT_MODEL, CLAUDE_VISION_MODEL, CLAUDE_FAST_MODEL,
)
from core.utils import extract_json_block, safe_json_loads
from db import increment_usage


def _client():
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "Brak ANTHROPIC_API_KEY. Dodaj klucz do .env lub .streamlit/secrets.toml."
        )
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("Brak pakietu anthropic. Uruchom: pip install anthropic")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_claude(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """
    Wolanie Claude Sonnet 4.6 (lub innego modelu).
    Zwraca surowy tekst odpowiedzi.
    """
    client = _client()
    model_id = model or CLAUDE_TEXT_MODEL

    kwargs = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system

    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:
        raise RuntimeError(f"Blad Claude API ({model_id}): {e}")

    # Track token usage
    try:
        usage = resp.usage
        total_tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
        # Claude Sonnet 4.6: ~$3/MTok input, ~$15/MTok output (przyblizenie)
        cost = (usage.input_tokens or 0) * 3.0 / 1_000_000 + \
               (usage.output_tokens or 0) * 15.0 / 1_000_000
        increment_usage("anthropic", model_id, tokens=total_tokens, cost=cost)
    except Exception:
        pass

    return resp.content[0].text


def call_claude_json(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    repair_attempts: int = 1,
) -> dict:
    """
    Jak call_claude, ale:
      - dodaje 'odpowiadasz tylko JSON-em' do system
      - parsuje wynik
      - na blad parsowania wysyla repair-prompt (max repair_attempts razy)
    """
    json_system = (system + "\n\n" if system else "") + \
                  "Odpowiadasz WYLACZNIE poprawnym JSON-em - zero komentarzy, zero markdown, zero text przed/po."
    raw = call_claude(prompt, system=json_system, max_tokens=max_tokens, model=model)

    extracted = extract_json_block(raw)
    parsed = safe_json_loads(extracted)
    if parsed is not None:
        return parsed

    # Repair loop
    for _ in range(repair_attempts):
        repair_prompt = (
            f"Ten JSON jest niepoprawny - popraw skladnie i odpowiedz TYLKO poprawnym JSON-em:\n\n{raw}"
        )
        raw = call_claude(repair_prompt, system=json_system, max_tokens=max_tokens, model=model)
        extracted = extract_json_block(raw)
        parsed = safe_json_loads(extracted)
        if parsed is not None:
            return parsed

    raise ValueError(f"Nie udalo sie sparsowac JSON-a po {repair_attempts + 1} probach. Raw: {raw[:500]}")


def call_claude_vision(
    prompt: str,
    images: list,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    temperature: float = 0.5,
) -> str:
    """
    Vision call. `images` to lista:
      - sciezek do plikow lokalnych (Path/str)
      - URLi (http/https)
      - bytes (raw image bytes)

    Klucz: kazdy obraz konwertujemy na format Anthropic content block
    (image/jpeg lub image/png base64, lub URL).
    """
    client = _client()
    model_id = model or CLAUDE_VISION_MODEL

    content_blocks = []
    for img in images:
        block = _image_to_block(img)
        if block:
            content_blocks.append(block)
    content_blocks.append({"type": "text", "text": prompt})

    kwargs = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content_blocks}],
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system

    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:
        raise RuntimeError(f"Blad Claude Vision ({model_id}): {e}")

    try:
        usage = resp.usage
        total_tokens = (usage.input_tokens or 0) + (usage.output_tokens or 0)
        cost = (usage.input_tokens or 0) * 3.0 / 1_000_000 + \
               (usage.output_tokens or 0) * 15.0 / 1_000_000
        increment_usage("anthropic", model_id, tokens=total_tokens, cost=cost)
    except Exception:
        pass

    return resp.content[0].text


def call_claude_vision_json(
    prompt: str,
    images: list,
    system: str = "",
    max_tokens: int = 4096,
    model: Optional[str] = None,
    repair_attempts: int = 1,
) -> dict:
    json_system = (system + "\n\n" if system else "") + \
                  "Odpowiadasz WYLACZNIE poprawnym JSON-em - zero komentarzy, zero markdown."
    raw = call_claude_vision(prompt, images, system=json_system,
                              max_tokens=max_tokens, model=model)
    extracted = extract_json_block(raw)
    parsed = safe_json_loads(extracted)
    if parsed is not None:
        return parsed

    for _ in range(repair_attempts):
        repair = call_claude(
            f"Popraw JSON na poprawny (zachowaj cala tresc):\n\n{raw}",
            system=json_system,
            max_tokens=max_tokens,
            model=CLAUDE_FAST_MODEL,
        )
        parsed = safe_json_loads(extract_json_block(repair))
        if parsed is not None:
            return parsed

    raise ValueError(f"Vision JSON parse failed. Raw: {raw[:500]}")


def _image_to_block(img) -> Optional[dict]:
    """Konwertuj sciezke/url/bytes na content block dla Anthropic."""
    if isinstance(img, (str, Path)):
        s = str(img)
        if s.startswith(("http://", "https://")):
            return {
                "type": "image",
                "source": {"type": "url", "url": s},
            }
        path = Path(s)
        if not path.exists():
            return None
        data = path.read_bytes()
        # Krzyzuj: detekcja po magic bytes (pewniejsze niz extension)
        # i fallback do extension jak nie rozpoznane
        media_type = _detect_media_type_from_bytes(data) or _guess_media_type(path.suffix)
        b64 = base64.standard_b64encode(data).decode("ascii")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    elif isinstance(img, bytes):
        # KRYTYCZNE: musimy wykryc media_type z magic bytes — Claude API odrzuca
        # mismatch (np. JPEG bytes deklarowane jako image/png → 400 invalid_request_error).
        # TikWM zwraca JPEG, Apify czesto WebP, IG czasem PNG — nie mozemy hardkodowac.
        media_type = _detect_media_type_from_bytes(img) or "image/jpeg"
        b64 = base64.standard_b64encode(img).decode("ascii")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }
    elif isinstance(img, dict):
        return img  # zaufaj ze user juz zbudowal block
    return None


def _detect_media_type_from_bytes(data: bytes) -> Optional[str]:
    """
    Wykrywa format obrazu z pierwszych bajtow pliku (magic bytes).
    Zwraca image/jpeg | image/png | image/webp | image/gif lub None gdy nieznany.
    """
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


def _guess_media_type(suffix: str) -> str:
    s = suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(s, "image/jpeg")


# ─────────────────────────────────────────────────────────────
# WALIDACJA TRESCI VS BRIEF (anti-halucynacja)
# ─────────────────────────────────────────────────────────────

def validate_against_brief(slides: list[dict], brief: dict) -> dict:
    """
    Sprawdza czy zadne stwierdzenie ze slajdow nie:
      - wymyśla USP/cech ktorych nie ma w briefie
      - lamie forbidden_claims (medyczne, income claims, gwarantowane wyniki)
      - klamie o cenie/ofercie
    Zwraca {"ok": bool, "violations": [{"slide": N, "issue": "..."}]}
    """
    if not brief:
        return {"ok": True, "violations": []}

    forbidden = brief.get("forbidden_claims") or [
        "gwarantowane wyniki",
        "100% skutecznosci",
        "leczy",
        "zarabiasz X PLN",
        "pewny zysk",
    ]

    slides_text = "\n".join(
        f"Slajd {s.get('order', i+1)}: HEADLINE: {s.get('headline','')} | BODY: {s.get('body','')}"
        for i, s in enumerate(slides)
    )

    prompt = f"""Sprawdz czy ponizsze slajdy karuzeli sa zgodne z briefem marki.

BRIEF MARKI:
Produkt: {brief.get('product','')}
Oferta: {brief.get('offer','')}
Cena: {brief.get('price','')} {brief.get('currency','PLN')}
USPs (jedyne dozwolone cechy produktu):
{json.dumps(brief.get('usps', []), ensure_ascii=False, indent=2)}
Gwarancje (jedyne dozwolone obietnice): {json.dumps(brief.get('guarantees', []), ensure_ascii=False)}
Zakazane stwierdzenia (ZAWSZE flaguj): {json.dumps(forbidden, ensure_ascii=False)}

SLAJDY DO SPRAWDZENIA:
{slides_text}

Zwroc JSON:
{{"ok": true/false, "violations": [{{"slide": <numer>, "issue": "<krotki opis problemu>"}}]}}

Flaguj TYLKO realne problemy:
- konkretne stwierdzenia o produkcie ktorych nie ma w USPs
- ceny rozne od briefa
- zakazane claims (medyczne, finansowe, gwarantowane wyniki)
NIE flaguj ogolnych hookow, pytan retorycznych, edukacyjnej tresci niezwiazanej z produktem.
"""
    try:
        result = call_claude_json(prompt, system="Jestes recenzentem zgodnosci tresci marketingowych.",
                                    max_tokens=1024, model=CLAUDE_FAST_MODEL)
        return result
    except Exception as e:
        # W razie bledu - nie blokuj generacji, ale zaloguj
        return {"ok": True, "violations": [], "_error": str(e)}
