"""
AI generator pomysłów na karuzele klasy WORLD-CLASS.
Wykorzystuje brief marki + ICP + sprawdzone frameworki direct response copywritingu.
"""
from typing import Optional

from core.llm import call_claude_json


SYSTEM_PROMPT = """Jestes WORLD-CLASS direct response copywriterem i strategiem wiralowych tresci.
Twoja praca byla porownywana do legendy: Gary Halbert, Eugene Schwartz, Dan Kennedy, David Ogilvy,
John Carlton. Inzynierowales viralne hooki dla Russell Brunson (ClickFunnels), Alex Hormozi (Acquisition.com),
Codie Sanchez, MrBeast, oraz polskich tworcow: Pawel Tkaczyk, Maciej Aniserowicz, Mateusz Grzesiak,
Artur Jablonski.

Twoja specjalnosc: tematy karuzel Instagram/TikTok ktore robia 3 rzeczy NARAZ:
  1. ZATRZYMUJA scroll w 0.5 sekundy (HOOK ktory budzi mozg)
  2. ZMUSZAJA do swipowania kazdego slajdu (CURIOSITY GAP)
  3. KONCZA tak silnym pragnieniem zakupu, ze widz CHCE kliknac link (CONVERSION)

Mistrzowsko stosujesz:
  - 5 stadiow swiadomosci klienta (Eugene Schwartz): Unaware → Problem-Aware → Solution-Aware → Product-Aware → Most Aware
  - Hormozi Value Equation: (Dream Outcome × Likelihood) / (Effort × Time Delay)
  - Gary Halbert "starving crowd" — temat targetuje ludzi juz gotowych kupic
  - Robert Cialdini influence: scarcity, authority, social proof, reciprocity
  - Pattern interrupts: rozbijasz schematy myslenia widza juz w pierwszych 3 slowach

ZNASZ NA WYLOT 6 archetypow wiralowych hookow:
  • LIST/NUMBERED ("3 bledy ktore niszcza...", "7 powodow dlaczego...")
    → KORZYSC: konkretnosc, swipeability, value w gotowej formie
  • PATTERN INTERRUPT ("Wszystko co wiesz o X jest klamstwem", "Nikt ci nie powie ze...")
    → KORZYSC: rozbija przekonania, budzi obrone i ciekawosc
  • SPECIFIC PROMISE ("Schudnij 5kg w 30 dni bez glodzenia", "Zarob 10k w 90 dni od zera")
    → KORZYSC: jasna obietnica + objection killer ("bez X")
  • AUTHORITY REVEAL ("Trener gwiazd zdradza...", "10 lat w branzy nauczylo mnie...")
    → KORZYSC: spoleczny dowod kompetencji + tajemnica
  • COUNTERINTUITIVE TRUTH ("Jedz wiecej zeby schudnac", "Pracuj mniej zeby zarobic wiecej")
    → KORZYSC: paradoks zatrzymuje, obietnica wyniku napedza dalej
  • STORY/CONFESSION ("Bylem tak grubo ze... oto co zmienilo wszystko", "Stracilam 50k zanim zrozumialam...")
    → KORZYSC: relatability + transformation arc

KRYTYCZNE ZASADY KAZDEGO TEMATU:
  - KONKRETNE LICZBY: "3 bledy" >>> "kilka bledow"; "47 godzin" >>> "pare dni"
  - JEZYK KLIENTA: uzywaj DOSLOWNIE zwrotow z ICP language_phrases (NIE marketingowy zargon)
  - 4-12 SLOW (krocej = silniejszy scroll-stop, max 12 zeby zmiescic na slajdzie)
  - POLSKI z poprawnymi diakrytykami (ą ę ó ł ś ć ż ź ń)
  - KAZDY temat = INNY format (mix wszystkich 6 archetypow)
  - TARGET PAIN: kazdy temat targetuje INNY pain z ICP
  - CONVERSION PATH: kazdy temat naturalnie prowadzi do produktu jako solution
  - NIE clickbait — temat MUSI byc dotrzymany w slajdach (value first, sale second)

ANALIZA KAZDEGO TEMATU (przed wygenerowaniem):
  1. Jaki pain z ICP atakujesz?
  2. Jaki archetyp hooka uzywasz?
  3. Co konkretnie widz dostanie wartosciowego w slajdach (framework, lista, tutorial, story)?
  4. Jak ten temat naturalnie prowadzi do produktu na ostatnim slajdzie?
  5. Czy 8/10 osob z target audience zatrzymalo by scroll w 0.5s?

Jezeli odpowiedz na p.5 to "nie" — przepisujesz temat od nowa. Tylko TOP-TIER tematy przechodza."""


def generate_viral_topics(
    brief: dict,
    n: int = 5,
    exclude_topics: list[str] = None,
    extra_context: str = "",
) -> list[dict]:
    """
    Generuje n najlepszych pomyslow tematow karuzel z ANALIZA dlaczego kazdy zadziala.

    Args:
        brief: dict z brand_briefs (product, main_promise, usps, avatars, objections...)
        n: ile tematow wygenerowac (default 5)
        exclude_topics: ostatnie tematy, ktorych nie powtarzac
        extra_context: dodatkowy kontekst (np. szczegolny moment kampanii)

    Returns:
        list[dict] — kazdy z polami:
            topic, format, hook_archetype, target_pain,
            value_in_carousel, conversion_angle, predicted_score
    """
    exclude_topics = (exclude_topics or [])[:10]

    product = brief.get("product", "")
    main_promise = brief.get("main_promise", "")
    offer = brief.get("offer", "")
    usps = brief.get("usps") or []
    voice_tone = brief.get("voice_tone", "")
    cta_text = brief.get("cta_text", "")
    social_proof = brief.get("social_proof") or []

    avatars = brief.get("avatars") or []
    pains: list[str] = []
    daily_struggles: list[str] = []
    language_phrases: list[str] = []
    dream_outcomes: list[str] = []
    avatar_objections: list[str] = []
    buying_triggers: list[str] = []

    for av in avatars[:2]:
        if not isinstance(av, dict):
            continue
        pains.extend(str(p) for p in (av.get("pain_points") or [])[:5])
        daily_struggles.extend(str(p) for p in (av.get("daily_struggles") or [])[:3])
        language_phrases.extend(str(p) for p in (av.get("language_phrases") or [])[:6])
        avatar_objections.extend(str(p) for p in (av.get("objections") or [])[:3])
        buying_triggers.extend(str(p) for p in (av.get("buying_triggers") or [])[:3])
        if av.get("dream_outcome"):
            dream_outcomes.append(str(av["dream_outcome"]))

    objections = list(brief.get("objections") or [])[:3] + avatar_objections[:3]

    user_prompt = f"""KONTEKST MARKI:
- Produkt: {product or "(brak danych)"}
- Glowna obietnica: {main_promise or "(brak danych)"}
- Pelna oferta: {offer or "(brak danych)"}
- USPs (wyroznienia ktorych ZADEN konkurent nie ma):
  {chr(10).join(f"  • {u}" for u in usps[:6]) or "  (brak)"}
- Voice tone: {voice_tone or "(neutralny ekspercki)"}
- CTA tekst: {cta_text or "Klik link w bio"}
- Social proof (uzyj jezeli pasuje):
  {chr(10).join(f"  • {s}" for s in social_proof[:5]) or "  (brak)"}

ICP — DO KOGO MOWIMY:
- Pain points (jak ich BOLI emocjonalnie):
  {chr(10).join(f"  • {p}" for p in pains[:8]) or "  (brak — uzyj generycznych pain z niszy)"}
- Codzienne irytacje (drobne klucia kazdego dnia):
  {chr(10).join(f"  • {d}" for d in daily_struggles[:5]) or "  (brak)"}
- DOSLOWNE zwroty klienta (uzywaj ich w temacie!):
  {chr(10).join(f'  • "{p}"' for p in language_phrases[:8]) or "  (brak)"}
- Dream outcome (co chca osiagnac):
  {chr(10).join(f"  • {d}" for d in dream_outcomes[:3]) or "  (brak)"}
- Obiekcje (co ich powstrzymuje):
  {chr(10).join(f"  • {o}" for o in objections[:6]) or "  (brak)"}
- Buying triggers (co popycha do kupna):
  {chr(10).join(f"  • {b}" for b in buying_triggers[:5]) or "  (brak)"}

TEMATY KTORE JUZ ZROBILISMY (NIE POWTARZAJ ZADNEGO Z TYCH ANGLES!):
{chr(10).join(f"  • {t}" for t in exclude_topics) or "  (zadnych jeszcze)"}

{f"DODATKOWY KONTEKST: {extra_context}" if extra_context else ""}

ZADANIE:
Wygeneruj DOKLADNIE {n} TEMATOW KARUZEL klasy WORLD-CLASS.

Najpierw POMYSL przez chwile:
  - Ktore z 6 archetypow nie zostaly jeszcze uzyte w "tematy juz zrobione"?
  - Ktorym pain pointom nie poswiecilismy uwagi?
  - Czy dla tej niszy WIRALOWO dziala raczej szok, framework, czy story?
  - Jaka liczba w temacie zaskoczy ("3 bledy", "47 dni", "100 zl")?
  - Czy potrafisz uzyc DOSLOWNIE zwrotu z language_phrases?

Potem wygeneruj {n} tematow gdzie KAZDY:
  1. Jest INNYM archetypem (mix wszystkich 6 — list, pattern_interrupt, specific_promise, authority_reveal, counterintuitive, story)
  2. Targetuje INNY konkretny pain z ICP (jak najwiecej pokrycia)
  3. Ma 4-12 slow (krocej = lepiej, ale nie kosztem konkretnosci)
  4. Naturalnie prowadzi do produktu jako solution (nie wymuszone)
  5. Uzywa konkretu (liczba, nazwa, czas, kwota) zamiast ogolnikow
  6. Brzmi jak temat ktory POLAK by udostepnil znajomemu

Dla kazdego napisz analitycznie DLACZEGO ten temat zadziala (Polish Reader Test).

Zwroc TYLKO JSON:
{{
  "topics": [
    {{
      "topic": "<temat 4-12 slow po polsku z diakrytykami>",
      "format": "list|question|how-to|reveal|warning|comparison|story",
      "hook_archetype": "list|pattern_interrupt|specific_promise|authority_reveal|counterintuitive|story",
      "target_pain": "<konkretny pain z ICP ktory atakujesz>",
      "value_in_carousel": "<dokladnie co widz dostanie w slajdach: framework krok po kroku / lista bledow z fixami / story z lekcjami / case study / checklist>",
      "conversion_angle": "<jak ten temat na ostatnim slajdzie naturalnie prowadzi do zakupu produktu — konkretnie>",
      "first_slide_hook_preview": "<jak moze brzmiec faktyczny tekst na pierwszym slajdzie, max 8 slow>",
      "predicted_score": <int 1-10, gdzie 10 = wiral gwarantowany + wysoki conversion>
    }},
    ...
  ]
}}

ZADNYCH KOMENTARZY POZA JSON. ZADNYCH WYJASNIEN. TYLKO JSON."""

    result = call_claude_json(
        user_prompt,
        system=SYSTEM_PROMPT,
        max_tokens=5000,
    )

    raw = result.get("topics") or []
    cleaned: list[dict] = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        topic_str = str(t.get("topic", "")).strip()
        if not topic_str:
            continue
        try:
            score = int(t.get("predicted_score") or 0)
        except (ValueError, TypeError):
            score = 0
        cleaned.append({
            "topic": topic_str,
            "format": str(t.get("format", "")).strip() or "—",
            "hook_archetype": str(t.get("hook_archetype", "")).strip() or "—",
            "target_pain": str(t.get("target_pain", "")).strip(),
            "value_in_carousel": str(t.get("value_in_carousel", "")).strip(),
            "conversion_angle": str(t.get("conversion_angle", "")).strip(),
            "first_slide_hook_preview": str(t.get("first_slide_hook_preview", "")).strip(),
            "predicted_score": max(0, min(10, score)),
        })

    # Sortuj po predicted_score malejaco
    cleaned.sort(key=lambda x: x["predicted_score"], reverse=True)
    return cleaned[:n]


def get_recent_topics(brand_id: str, limit: int = 8) -> list[str]:
    """Wyciaga tematy ostatnich karuzel (z headline pierwszego slajdu)."""
    from db import list_carousels
    recent = list_carousels(brand_id, limit=limit)
    out = []
    for c in recent:
        slides = c.get("slides") or []
        if not slides:
            continue
        first = slides[0] if isinstance(slides[0], dict) else None
        if first and first.get("headline"):
            out.append(str(first["headline"])[:80])
    return out
