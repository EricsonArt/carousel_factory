"""
AI auto-fill dla ICP (Ideal Customer Profile).
User opisuje krotko swojego klienta — Claude generuje pelny ICP.
"""
from typing import Optional

from core.llm import call_claude_json


SYSTEM_PROMPT = """Jestes ekspertem od market research i customer development. Pracowales z Lean Startup,
Jobs To Be Done, StoryBrand. Twoja praca to ZAGLEBIENIE SIE w glowe klienta tak, zeby copywriter mogl
napisac slowo w slowo to co klient mowi w glowie.

Zasady:
- Jezyk klienta to ICH wlasne slowa, nie korporacyjny zargon. Cytuj jak by sie wyrazili.
- Konkretne demograficzne dane (wiek, plec, dochod, lokalizacja, status rodzinny).
- Pain points musza byc EMOCJONALNE, nie tylko logiczne. "Nie moge zalozyc spodni" > "Nadwaga".
- Daily struggles = co konkretnie irytuje ich KAŻDEGO dnia.
- Dream outcome = idealny stan po zakupie produktu, opisany sensorycznie.
- Buying triggers = momenty/wyzwalacze ktore sklaniaja do kupna.
- Channels = gdzie sie naprawde przebywaja online (subreddity, IG kont, podcasty, blogi).
"""


SCHEMA_HINT = """{
  "icp_summary": "<2-3 zdania: kto to jest, co ich definiuje, dlaczego potrzebuja produktu>",
  "avatars": [
    {
      "name": "<imie + krotki opis, np. 'Magda 34 - mama dwojki na urlopie macierzynskim'>",
      "demographics": "<wiek, plec, lokalizacja, dochod, status, zawod - jednym zdaniem>",
      "pain_points": [
        "<5 emocjonalnych pain pointow, w wlasnych slowach klienta>",
        "...", "...", "...", "..."
      ],
      "daily_struggles": [
        "<3-4 codzienne irytacje zwiazane z problemem ktory rozwiazuje produkt>",
        "...", "..."
      ],
      "dream_outcome": "<sensoryczny opis idealnego stanu po zakupie - 1-2 zdania>",
      "language_phrases": [
        "<5 dokladnych zwrotow ktorymi mowi klient o swoim problemie>",
        "...", "...", "...", "..."
      ],
      "objections": [
        "<3 obiekcje przed kupnem w slowach klienta>",
        "...", "..."
      ],
      "buying_triggers": [
        "<3 wyzwalacze/momenty ktore sklaniaja do kupna>",
        "...", "..."
      ]
    }
    // Mozna dodac 2-3 awatary jezeli produkt celuje w rozne segmenty
  ],
  "channels": [
    "<5-7 miejsc online gdzie ten klient sie przebywa - konkretne IG/TikTok konta, subreddity, podcasty, blogi, FB grupy>",
    "...", "...", "...", "..."
  ],
  "anti_avatar": "<1-2 zdania: KTO NIE jest klientem - kogo nie chcemy targetowac>"
}"""


def auto_fill_icp(
    brand_name: str,
    niche: str,
    product_description: str,
    customer_description: str,
    extra_context: str = "",
) -> dict:
    """
    Generuje pelny ICP na podstawie krotkiego opisu produktu i klienta.

    Args:
        brand_name: nazwa marki
        niche: nisza
        product_description: krotki opis produktu (z brief.product / main_promise)
        customer_description: 1-3 zdania od usera o tym KTO kupuje
        extra_context: dodatkowy kontekst

    Returns:
        dict z kluczami: icp_summary, avatars, channels, anti_avatar
    """
    prompt = f"""MARKA: {brand_name}
NISZA: {niche or "(nie podano)"}

PRODUKT: {product_description or "(nie podano)"}

OPIS KLIENTA OD UZYTKOWNIKA:
\"\"\"
{customer_description.strip()}
\"\"\"

{f'DODATKOWY KONTEKST: {extra_context}' if extra_context else ''}

Wygeneruj kompletny ICP zgodny ze schematem:

{SCHEMA_HINT}

Pamietaj:
- Cytuj klienta DOSLOWNIE - w `language_phrases` ma byc to co on mowi do siebie w glowie
- Jezeli user opisal jeden segment, zrob 1 awatar (nie wymyslaj na sile drugich)
- Jezeli opisal kilka grup/segmentow, zrob 2-3 awatary
- channels: BARDZO konkretne (np. "subreddit r/keto", "IG konto @ketoportal", "podcast Diet Doctor")

Zwroc TYLKO JSON.
"""
    result = call_claude_json(prompt, system=SYSTEM_PROMPT, max_tokens=3500)

    # Sanitize avatars
    avatars = result.get("avatars") or []
    if not isinstance(avatars, list):
        avatars = []
    cleaned_avatars = []
    for a in avatars:
        if not isinstance(a, dict):
            continue
        cleaned_avatars.append({
            "name": str(a.get("name", "")).strip(),
            "demographics": str(a.get("demographics", "")).strip(),
            "pain_points": _ensure_list(a.get("pain_points")),
            "daily_struggles": _ensure_list(a.get("daily_struggles")),
            "dream_outcome": str(a.get("dream_outcome", "")).strip(),
            "language_phrases": _ensure_list(a.get("language_phrases")),
            "objections": _ensure_list(a.get("objections")),
            "buying_triggers": _ensure_list(a.get("buying_triggers")),
        })

    return {
        "icp_summary": str(result.get("icp_summary", "")).strip(),
        "avatars": cleaned_avatars,
        "channels": _ensure_list(result.get("channels")),
        "anti_avatar": str(result.get("anti_avatar", "")).strip(),
    }


def _ensure_list(v) -> list:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []
