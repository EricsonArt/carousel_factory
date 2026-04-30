"""
Silnik automatyzacji — generuje tematy z brief marki i wysyła karuzele do Publer.
"""
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

from core.llm import call_claude_json
from core.utils import slot_randomizer
from config import MIN_GAP_MINUTES


def generate_topics_batch(brief: dict, niche: str, n: int) -> list[str]:
    """Generuje n różnorodnych tematów wiralowych karuzel z brief marki."""
    product = brief.get("product", "")
    usps = brief.get("usps") or []
    avatars = brief.get("avatars") or []

    pain_points: list[str] = []
    for av in avatars[:2]:
        if isinstance(av, dict):
            pain_points.extend(str(p) for p in (av.get("pain_points") or [])[:3])
            pain_points.extend(str(p) for p in (av.get("daily_struggles") or [])[:2])

    objections = [str(o) for o in (brief.get("objections") or [])[:3]]

    prompt = f"""Wygeneruj DOKLADNIE {n} roznorodnych tematow wiralowych karuzel Instagram/TikTok.

KONTEKST:
- Produkt: {product or "(nieokreslony)"}
- Nisza: {niche or "(nieokreslona)"}
- USPs: {", ".join(str(u) for u in usps[:5]) or "(brak)"}
- Pain points klienta: {", ".join(pain_points[:6]) or "(brak)"}
- Obiekcje: {", ".join(objections) or "(brak)"}

ZASADY:
- Kazdy temat INNY format — uzyj roznorodnych frameworkow: "X bledow...", "Dlaczego...", "Jak...",
  "Prawda o...", "Stop robiac...", "Sekret...", "Nikt ci nie powie...", lista, pytanie, szok
- Tematy KONKRETNE i WIRALOWE — wzbudzaja ciekawosc, FOMO, szok lub ulge
- Tematy zwiazane z produktem/nisza
- Pisz po polsku z poprawnymi znakami diakrytycznymi
- Kazdy temat max 80 znakow

Zwroc TYLKO JSON:
{{"topics": ["temat 1", "temat 2", "...", "temat {n}"]}}"""

    try:
        result = call_claude_json(prompt, max_tokens=2000)
        topics = result.get("topics") or []
        return [str(t).strip() for t in topics if str(t).strip()][:n]
    except Exception:
        base = niche or "sukcesu"
        return [f"Sekret {base} #{i+1}" for i in range(n)]


def run_automation_batch(
    job_dict: dict,
    brand_id: str,
    brand_name: str,
    niche: str,
    posts_per_day: int,
    days_ahead: int,
    style_id: Optional[str],
    ig_account_ids: list,
    tt_account_ids: list,
    language: str,
    model_override: Optional[str],
    image_quality: str,
    prefer_provider: Optional[str],
    publer_api_key: str,
    publer_workspace_id: str,
    slots: list,
    text_settings: Optional[dict] = None,
):
    """
    Pełna automatyzacja w tle:
      1. Generuje N tematów z brief marki
      2. Dla każdego: generuje karuzelę (Claude copy + AI obraz + Pillow overlay)
      3. Wgrywa obrazy do Publer i planuje post na odpowiednią godzinę

    Jeśli publer_api_key pusty lub brak kont → karuzele są generowane (historia), bez planowania.
    """
    from core.carousel_generator import generate_carousel
    from db import get_brief, update_carousel, update_automation_config

    total = posts_per_day * days_ahead
    results: list[dict] = []
    use_publer = bool(publer_api_key and (ig_account_ids or tt_account_ids))

    try:
        # 1. Inicjalizacja Publer (jeśli potrzebne)
        client = None
        if use_publer:
            from core.publisher_publer import PublerClient
            job_dict["stage"] = "Łączę z Publer..."
            job_dict["progress"] = 0.01
            client = PublerClient(publer_api_key, publer_workspace_id)
            if not publer_workspace_id:
                workspaces = client.get_workspaces()
                if not workspaces:
                    raise RuntimeError(
                        "Brak workspaces w koncie Publer — zaloguj się na publer.com "
                        "i sprawdź czy masz aktywny workspace."
                    )
                client.set_workspace(str(workspaces[0].get("id", "")))

        # 2. Generuj tematy
        job_dict["stage"] = "Generuję tematy karuzel..."
        job_dict["progress"] = 0.03
        brief = get_brief(brand_id) or {}
        topics = generate_topics_batch(brief, niche, total)
        if len(topics) < total:
            base = niche or "tematu"
            topics += [f"{base} — wskazówka #{i+1}" for i in range(total - len(topics))]
        topics = topics[:total]

        # 3. Zaplanuj czasy postów
        job_dict["stage"] = "Obliczam harmonogram..."
        job_dict["progress"] = 0.06
        base_date = datetime.now(timezone.utc)
        scheduled_times = slot_randomizer(
            slots=slots,
            num_posts=total,
            min_gap_minutes=MIN_GAP_MINUTES,
            base_date=base_date,
        )

        # 4. Generuj + publikuj każdą karuzelę
        for i, (topic, sched_time) in enumerate(zip(topics, scheduled_times)):
            progress_base = 0.08 + 0.88 * (i / total)

            # Generacja copy + obrazów
            job_dict["stage"] = f"[{i+1}/{total}] Generuję: {topic[:55]}..."
            job_dict["progress"] = progress_base

            try:
                carousel = generate_carousel(
                    brand_id=brand_id,
                    topic=topic,
                    style_id=style_id,
                    slide_count=7,
                    use_ai_images=bool(prefer_provider),
                    prefer_provider=prefer_provider,
                    image_quality=image_quality,
                    model_override=model_override,
                    language=language,
                    text_settings=text_settings,
                )
            except Exception as e:
                results.append({
                    "topic": topic,
                    "status": "error_gen",
                    "error": str(e)[:140],
                    "scheduled_at": sched_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                })
                continue

            # Sprawdz ile slajdow padlo na fallback (czarne/gradientowe tlo zamiast AI)
            slides_meta = carousel.get("slides", []) or []
            fallback_slides = sum(
                1 for s in slides_meta
                if isinstance(s, dict) and str(s.get("image_provider", "")).startswith("fallback")
            )

            scheduled_iso = sched_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            if not use_publer:
                # Tylko generacja — brak planowania
                update_carousel(carousel["id"], status="draft", scheduled_at=scheduled_iso)
                results.append({
                    "topic": topic,
                    "carousel_id": carousel["id"],
                    "scheduled_at": scheduled_iso,
                    "status": "generated_only",
                })
                continue

            # Upload + schedule do Publer
            try:
                slides = carousel.get("slides", [])
                image_paths = [s["image_path"] for s in slides if s.get("image_path")]

                media_ids = []
                n_imgs = len(image_paths)
                for j, path in enumerate(image_paths):
                    job_dict["stage"] = f"[{i+1}/{total}] Upload {j+1}/{n_imgs}..."
                    job_dict["progress"] = progress_base + 0.88 / total * 0.5 * (j / max(n_imgs, 1))
                    mid = client.upload_media(path)
                    media_ids.append(mid)

                job_dict["stage"] = f"[{i+1}/{total}] Planuję + weryfikuję w Publer..."
                publer_result = client.schedule_carousel(
                    ig_account_ids=ig_account_ids,
                    tt_account_ids=tt_account_ids,
                    caption=carousel.get("caption", ""),
                    hashtags=carousel.get("hashtags") or [],
                    media_ids=media_ids,
                    scheduled_at=scheduled_iso,
                    verify=True,  # Czeka az Publer potwierdzi utworzenie posta
                )

                publer_post_id = (
                    publer_result.get("post_id")
                    or publer_result.get("job_id")
                    or "ok"
                )
                update_carousel(
                    carousel["id"],
                    status="scheduled",
                    scheduled_at=scheduled_iso,
                    publer_post_id=str(publer_post_id),
                )
                results.append({
                    "topic": topic,
                    "carousel_id": carousel["id"],
                    "scheduled_at": scheduled_iso,
                    "status": "scheduled",
                    "publer_post_id": str(publer_post_id),
                    "fallback_slides": fallback_slides,
                    "total_slides": len(slides_meta),
                })

            except Exception as e:
                update_carousel(carousel["id"], status="draft", scheduled_at=scheduled_iso)
                results.append({
                    "topic": topic,
                    "carousel_id": carousel.get("id", ""),
                    "scheduled_at": scheduled_iso,
                    "status": "error_publer",
                    "error": str(e)[:200],
                })

        # 5. Zapisz znacznik czasu ostatniego uruchomienia
        update_automation_config(brand_id, auto_last_run=datetime.now(timezone.utc).isoformat())

        ok_count = sum(1 for r in results if r["status"] in ("scheduled", "generated_only"))
        label = "zaplanowanych w Publer" if use_publer else "wygenerowanych (bez Publer)"
        job_dict["stage"] = f"Gotowe! {ok_count}/{total} karuzel {label}."
        job_dict["progress"] = 1.0
        job_dict["results"] = results
        job_dict["status"] = "done"

    except Exception as e:
        job_dict["status"] = "error"
        job_dict["error"] = str(e)
        job_dict["traceback"] = traceback.format_exc()
    finally:
        job_dict["finished_at"] = time.time()
