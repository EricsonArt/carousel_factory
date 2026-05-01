"""
Generator karuzel — generowanie (równoległe) + wysyłanie do Publer.
"""
import threading
import time
import traceback
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from core.carousel_generator import generate_carousel, export_carousel_as_zip
from core.viral_replicator import replicate_viral_carousel, ViralFetchError
from ui.text_settings import render_text_settings_panel
from db import get_brand, get_brief, list_styles, update_carousel
from config import (
    DEFAULT_SLIDES, MIN_SLIDES, MAX_SLIDES, PUBLER_API_KEY, PUBLER_WORKSPACE_ID,
    OPENAI_API_KEY,
)
from ui.theme import page_header, section_title, empty_state


# ─────────────────────────────────────────────────────────────
# JOB MANAGER — równoległe generowanie kilku karuzel naraz
# ─────────────────────────────────────────────────────────────

def _get_jobs() -> dict:
    """Słownik wszystkich jobów (running + done + error) per sesja."""
    return st.session_state.setdefault("active_jobs", {})


def _start_generation_job(brand_id: str, params: dict) -> str:
    """Odpala nowy wątek generacji. Zwraca job_id."""
    jobs = _get_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "brand_id": brand_id,
        "topic": params["topic"],
        "language": params.get("language", "pl"),
        "status": "running",
        "stage": "Inicjalizacja...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "carousel": None,
        "error": None,
        "traceback": None,
    }

    thread = threading.Thread(
        target=_run_generation_job,
        args=(jobs, job_id, brand_id, params),
        daemon=True,
    )
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def _run_generation_job(jobs: dict, job_id: str, brand_id: str, params: dict):
    """Funkcja wątku — wywołuje generate_carousel i zapisuje wynik do jobs[job_id]."""
    def cb(stage: str, pct: float):
        if job_id in jobs:
            jobs[job_id]["stage"] = stage
            jobs[job_id]["progress"] = float(pct)

    try:
        carousel = generate_carousel(
            brand_id=brand_id,
            topic=params["topic"],
            style_id=params.get("style_id"),
            slide_count=params["slide_count"],
            use_ai_images=params.get("use_ai_images", False),
            prefer_provider=params.get("prefer_provider"),
            image_quality=params.get("image_quality", "low"),
            model_override=params.get("model_override"),
            language=params.get("language", "pl"),
            text_mode=params.get("text_mode", "overlay"),
            text_settings=params.get("text_settings"),
            progress_callback=cb,
            custom_instructions=params.get("custom_instructions", ""),
            image_custom_instructions=params.get("image_custom_instructions", ""),
        )
        jobs[job_id]["carousel"] = carousel
        jobs[job_id]["status"] = "done"
        jobs[job_id]["stage"] = "Gotowe"
        jobs[job_id]["progress"] = 1.0
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["traceback"] = traceback.format_exc()
    finally:
        jobs[job_id]["finished_at"] = time.time()


def _start_viral_job(brand_id: str, params: dict) -> str:
    """Startuje job viralowej replikacji (yt-dlp scrape -> Vision -> Pillow)."""
    jobs = _get_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "brand_id": brand_id,
        "topic": f"🎬 Viral: {params['url'][:50]}",
        "language": params.get("language", "pl"),
        "status": "running",
        "stage": "Pobieram viralu...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "carousel": None,
        "error": None,
        "traceback": None,
        "is_viral": True,
    }
    thread = threading.Thread(
        target=_run_viral_job,
        args=(jobs, job_id, brand_id, params),
        daemon=True,
    )
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def _run_viral_job(jobs: dict, job_id: str, brand_id: str, params: dict):
    """Watek viralowy — wywoluje replicate_viral_carousel."""
    def cb(stage: str, pct: float):
        if job_id in jobs:
            jobs[job_id]["stage"] = stage
            jobs[job_id]["progress"] = float(pct)

    try:
        carousel = replicate_viral_carousel(
            url=params["url"],
            brand_id=brand_id,
            style_id=params.get("style_id"),
            use_ai_images=params.get("use_ai_images", True),
            prefer_provider=params.get("prefer_provider"),
            image_quality=params.get("image_quality", "low"),
            model_override=params.get("model_override"),
            language=params.get("language", "pl"),
            text_settings=params.get("text_settings"),
            progress_callback=cb,
            clone_visual=params.get("clone_visual", False),
            custom_instructions=params.get("custom_instructions", ""),
            image_custom_instructions=params.get("image_custom_instructions", ""),
        )
        jobs[job_id]["carousel"] = carousel
        jobs[job_id]["status"] = "done"
        jobs[job_id]["stage"] = "Gotowe"
        jobs[job_id]["progress"] = 1.0
    except ViralFetchError as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"Pobieranie viralu: {e}"
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["traceback"] = traceback.format_exc()
    finally:
        jobs[job_id]["finished_at"] = time.time()


# ─────────────────────────────────────────────────────────────
# PUBLER JOB — wysyłka też w wątku, bo upload trwa dłużej niż 2s
# (czyli dłużej niż auto-refresh fragmentu — inaczej fragment przerywa upload)
# ─────────────────────────────────────────────────────────────

def _get_publer_jobs() -> dict:
    return st.session_state.setdefault("publer_jobs", {})


def _start_publer_job(carousel: dict, ig_ids: list, tt_ids: list, scheduled_iso: str) -> str:
    jobs = _get_publer_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "carousel_id": carousel["id"],
        "status": "running",
        "stage": "Inicjalizacja...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
        "traceback": None,
    }
    thread = threading.Thread(
        target=_run_publer_job,
        args=(jobs, job_id, carousel, ig_ids, tt_ids, scheduled_iso),
        daemon=True,
    )
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def _run_publer_job(jobs: dict, job_id: str, carousel: dict,
                    ig_ids: list, tt_ids: list, scheduled_iso: str):
    """Funkcja wątku — robi cały upload + schedule. Łapie WSZYSTKIE wyjątki."""
    try:
        from core.publisher_publer import PublerClient, PublerError

        slides = carousel.get("slides", [])
        image_paths = [s["image_path"] for s in slides if s.get("image_path")]
        if not image_paths:
            raise RuntimeError("Karuzela nie ma obrazków do wysłania.")

        jobs[job_id]["stage"] = "Łączenie z Publer..."
        jobs[job_id]["progress"] = 0.05

        client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
        if not PUBLER_WORKSPACE_ID:
            workspaces = client.get_workspaces()
            if not workspaces:
                raise RuntimeError(
                    "Brak workspaces w koncie Publer. Zaloguj się na publer.com "
                    "i sprawdź czy masz aktywny workspace."
                )
            client.set_workspace(str(workspaces[0].get("id", "")))

        media_ids = []
        n = len(image_paths)
        for i, path in enumerate(image_paths):
            jobs[job_id]["stage"] = f"Upload obrazka {i+1}/{n}..."
            jobs[job_id]["progress"] = 0.1 + 0.7 * (i / max(n, 1))
            mid = client.upload_media(path)
            media_ids.append(mid)

        jobs[job_id]["stage"] = "Tworzę zaplanowany post..."
        jobs[job_id]["progress"] = 0.85

        # schedule_carousel ma teraz wbudowana weryfikacje — rzuca PublerError
        # gdy Publer odrzuci post lub ukonczy job z bledami w srodku
        schedule_result = client.schedule_carousel(
            ig_account_ids=ig_ids,
            tt_account_ids=tt_ids,
            caption=carousel.get("caption", ""),
            hashtags=carousel.get("hashtags") or [],
            media_ids=media_ids,
            scheduled_at=scheduled_iso,
            verify=True,
        )

        publer_post_id = (
            schedule_result.get("post_id")
            or schedule_result.get("job_id")
            or "ok"
        )
        update_carousel(
            carousel["id"],
            publer_post_id=str(publer_post_id),
            status="scheduled",
            scheduled_at=scheduled_iso,
        )

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 1.0
        jobs[job_id]["stage"] = "Gotowe — Publer potwierdził utworzenie posta"
        jobs[job_id]["result"] = {
            "post_id": str(publer_post_id),
            "schedule_result": schedule_result,
            "final_job_status": schedule_result.get("job_status_final"),
        }

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["traceback"] = traceback.format_exc()
    finally:
        jobs[job_id]["finished_at"] = time.time()


def _run_publer_diagnostic():
    """Synchroniczny test API Publer — pokazuje krok po kroku co działa, a co nie."""
    from core.publisher_publer import PublerClient, PublerError

    st.markdown("---")
    st.markdown("**🩺 Diagnostyka Publer API**")

    if not PUBLER_API_KEY:
        st.error("❌ PUBLER_API_KEY pusty — dodaj do Streamlit Secrets.")
        return

    masked = PUBLER_API_KEY[:6] + "..." + PUBLER_API_KEY[-4:] if len(PUBLER_API_KEY) > 10 else "(za krótki)"
    st.caption(f"Klucz API: `{masked}` ({len(PUBLER_API_KEY)} znaków)")
    st.caption(f"Workspace ID z Secrets: `{PUBLER_WORKSPACE_ID or '(brak — będzie auto-fetch)'}`")

    try:
        client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)

        st.write("1️⃣ Pobieram listę workspaces...")
        workspaces = client.get_workspaces()
        st.success(f"✅ Workspaces: {len(workspaces)}")
        if workspaces:
            st.json([{"id": w.get("id"), "name": w.get("name")} for w in workspaces[:5]])
            if not PUBLER_WORKSPACE_ID:
                client.set_workspace(str(workspaces[0].get("id", "")))
                st.caption(f"Ustawiam workspace na: `{workspaces[0].get('id')}`")

        st.write("2️⃣ Pobieram konta IG/TikTok...")
        accounts = client.get_accounts()
        st.success(f"✅ Konta: {len(accounts)}")
        if accounts:
            st.json([
                {"id": a.get("id"), "provider": a.get("provider"),
                 "name": a.get("name") or a.get("username")}
                for a in accounts[:10]
            ])
        else:
            st.warning("⚠️ Lista kont jest pusta — w Publer dashboard połącz IG/TikTok.")

        st.success("🎉 Wszystko OK — możesz wysyłać karuzele.")

    except PublerError as e:
        st.error(f"❌ Błąd API: {e}")
        st.caption("Najczęstsze przyczyny: zły klucz, klucz wygasł, plan bez API access, "
                    "zła nazwa nagłówka autoryzacji.")
    except Exception as e:
        st.error(f"❌ Nieoczekiwany błąd: {e}")
        st.exception(e)


@st.fragment(run_every=2)
def _render_jobs_panel(brand_id: str):
    """Panel aktywnych i ukończonych jobów. Auto-refresh co 2s."""
    jobs = _get_jobs()
    # Filtruj tylko joby tej marki
    brand_jobs = {k: v for k, v in jobs.items() if v.get("brand_id") == brand_id}
    if not brand_jobs:
        return

    running = [v for v in brand_jobs.values() if v["status"] == "running"]
    done    = [v for v in brand_jobs.values() if v["status"] == "done"]
    errors  = [v for v in brand_jobs.values() if v["status"] == "error"]

    if running:
        section_title(f"🔄 W trakcie generacji ({len(running)})", icon="")
        for j in running:
            with st.container(border=True):
                col_t, col_lang = st.columns([5, 1])
                with col_t:
                    st.markdown(f"**{j['topic'][:80]}**")
                with col_lang:
                    st.caption(f"🌐 {j['language'].upper()}")
                pct = max(0.02, min(1.0, j["progress"]))
                st.progress(pct, text=f"{int(pct*100)}% — {j['stage']}")
                elapsed = int(time.time() - j["started_at"])
                st.caption(f"⏱️ {elapsed}s")

    if done:
        section_title(f"✅ Gotowe ({len(done)})", icon="")
        for j in sorted(done, key=lambda x: x["finished_at"] or 0, reverse=True):
            with st.expander(f"✅ {j['topic'][:80]}  ·  🌐 {j['language'].upper()}", expanded=False):
                _show_carousel_preview(j["carousel"])
                if st.button("🗑️ Usuń z listy", key=f"rm_done_{j['id']}"):
                    del jobs[j["id"]]
                    st.rerun()

    if errors:
        section_title(f"❌ Błędy ({len(errors)})", icon="")
        for j in errors:
            with st.expander(f"❌ {j['topic'][:80]}", expanded=False):
                st.error(j["error"])
                if j.get("traceback"):
                    with st.expander("Szczegóły"):
                        st.code(j["traceback"])
                if st.button("🗑️ Usuń", key=f"rm_err_{j['id']}"):
                    del jobs[j["id"]]
                    st.rerun()


_ARCHETYPE_LABELS = {
    "list":               ("📋", "Lista", "#7C3AED", "#EDE9FE"),
    "pattern_interrupt":  ("⚡", "Pattern interrupt", "#DC2626", "#FEE2E2"),
    "specific_promise":   ("🎯", "Konkretna obietnica", "#059669", "#D1FAE5"),
    "authority_reveal":   ("👑", "Autorytet zdradza", "#B45309", "#FEF3C7"),
    "counterintuitive":   ("🔄", "Paradoks", "#0891B2", "#CFFAFE"),
    "story":              ("📖", "Historia", "#BE185D", "#FCE7F3"),
}


def _render_topic_ai_section(brand_id: str, brief: dict):
    """Sekcja AI generowania pomysłów na temat karuzeli — eksperckie, konwertujące tematy."""
    section_title("Pomysł na karuzelę", icon="💡")

    # Premium intro
    st.markdown("""
        <div style="background:linear-gradient(135deg,#FAF5FF 0%,#FCE7F3 50%,#FFF7ED 100%);
                    border:1px solid #DDD6FE;border-radius:14px;padding:1rem 1.3rem;
                    margin-bottom:0.9rem;line-height:1.55;">
            <div style="font-weight:700;color:#1F1B3B;font-size:0.92rem;margin-bottom:0.25rem;">
                💎 Brak pomysłu? AI wygeneruje 5 tematów klasy world-class.
            </div>
            <div style="font-size:0.8rem;color:#6B7280;">
                Bazuje na briefie + ICP + 6 archetypach wiralowych hooków.
                Każdy temat z analizą: format, target pain, value w slajdach, konwersja.
            </div>
        </div>
    """, unsafe_allow_html=True)

    has_brief = bool(brief.get("product") or brief.get("avatars") or brief.get("usps"))
    if not has_brief:
        st.warning(
            "⚠️ Brief marki jest pusty — AI wygeneruje generyczne pomysły. "
            "Uzupełnij **Brief**, **Produkt** i **ICP** żeby tematy były precyzyjnie dopasowane."
        )

    btn_col, info_col = st.columns([2, 3])
    with btn_col:
        if st.button(
            "💎 AI: 5 najlepszych pomysłów",
            type="secondary",
            use_container_width=True,
            disabled=st.session_state.get("topic_ai_loading", False),
        ):
            st.session_state["topic_ai_loading"] = True
            st.rerun()

    if st.session_state.get("topic_ai_loading"):
        try:
            with st.spinner("🧠 AI analizuje brief, ICP i pisze tematy klasy world-class (~15s)..."):
                from core.topic_generator import generate_viral_topics, get_recent_topics
                recent = get_recent_topics(brand_id, limit=8)
                suggestions = generate_viral_topics(
                    brief=brief,
                    n=5,
                    exclude_topics=recent,
                )
                st.session_state["topic_suggestions"] = suggestions
                st.session_state["topic_ai_loading"] = False
                st.rerun()
        except Exception as e:
            st.session_state["topic_ai_loading"] = False
            st.error(f"Błąd AI: {e}")

    # Wyświetl wygenerowane pomysły
    suggestions = st.session_state.get("topic_suggestions") or []
    if suggestions:
        st.markdown(
            f"""<div style="margin:1.2rem 0 0.7rem;display:flex;justify-content:space-between;
                            align-items:baseline;">
                <span style="font-size:0.85rem;font-weight:700;color:#1F1B3B;letter-spacing:-0.01em;">
                    🏆 {len(suggestions)} pomysłów posortowanych po sile wirala
                </span>
                <span style="font-size:0.7rem;color:#6B7280;">kliknij 'Użyj →' żeby wybrać</span>
            </div>""",
            unsafe_allow_html=True,
        )

        for i, s in enumerate(suggestions):
            score = s.get("predicted_score", 0)
            score_color = "#10B981" if score >= 8 else "#F59E0B" if score >= 6 else "#94A3B8"

            arch_key = s.get("hook_archetype", "")
            arch_icon, arch_label, arch_fg, arch_bg = _ARCHETYPE_LABELS.get(
                arch_key, ("✨", arch_key.replace("_", " ").title() or "—", "#6B7280", "#F3F4F6")
            )

            with st.container(border=True):
                col_main, col_btn = st.columns([5, 1])
                with col_main:
                    # Topic + badges
                    st.markdown(f"""
                        <div style="font-size:1.1rem;font-weight:800;color:#0B0A18;
                                    line-height:1.3;letter-spacing:-0.015em;margin-bottom:0.5rem;">
                            {s["topic"]}
                        </div>
                        <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.75rem;">
                            <span style="background:{arch_bg};color:{arch_fg};padding:3px 9px;
                                         border-radius:8px;font-size:0.7rem;font-weight:700;
                                         display:inline-flex;align-items:center;gap:0.3rem;">
                                {arch_icon} {arch_label}
                            </span>
                            <span style="background:white;border:1.5px solid {score_color};color:{score_color};
                                         padding:2px 9px;border-radius:8px;font-size:0.7rem;font-weight:800;
                                         display:inline-flex;align-items:center;gap:0.25rem;">
                                ⚡ {score}/10
                            </span>
                        </div>
                    """, unsafe_allow_html=True)

                    # Analytical breakdown
                    if s.get("first_slide_hook_preview"):
                        st.markdown(
                            f"""<div style="background:#F9FAFB;border-left:3px solid #7C3AED;
                                            padding:0.5rem 0.8rem;border-radius:0 8px 8px 0;
                                            margin-bottom:0.5rem;font-size:0.82rem;color:#374151;
                                            line-height:1.4;">
                                <span style="color:#7C3AED;font-weight:700;">PIERWSZY SLAJD:</span>
                                <span style="font-weight:600;">"{s["first_slide_hook_preview"]}"</span>
                            </div>""",
                            unsafe_allow_html=True,
                        )

                    if s.get("target_pain"):
                        st.markdown(
                            f"""<div style="font-size:0.78rem;color:#374151;line-height:1.5;margin-bottom:0.2rem;">
                                <span style="color:#DC2626;font-weight:700;">🎯 TARGET PAIN:</span> {s["target_pain"]}
                            </div>""",
                            unsafe_allow_html=True,
                        )
                    if s.get("value_in_carousel"):
                        st.markdown(
                            f"""<div style="font-size:0.78rem;color:#374151;line-height:1.5;margin-bottom:0.2rem;">
                                <span style="color:#059669;font-weight:700;">💎 VALUE:</span> {s["value_in_carousel"]}
                            </div>""",
                            unsafe_allow_html=True,
                        )
                    if s.get("conversion_angle"):
                        st.markdown(
                            f"""<div style="font-size:0.78rem;color:#374151;line-height:1.5;">
                                <span style="color:#B45309;font-weight:700;">💰 KONWERSJA:</span> {s["conversion_angle"]}
                            </div>""",
                            unsafe_allow_html=True,
                        )

                with col_btn:
                    st.markdown('<div style="padding-top:0.6rem;"></div>', unsafe_allow_html=True)
                    if st.button(
                        "Użyj →",
                        key=f"use_topic_{i}",
                        type="primary",
                        use_container_width=True,
                    ):
                        st.session_state["topic_input"] = s["topic"]
                        st.session_state["topic_suggestions"] = []
                        st.toast(f"✅ Wybrano: {s['topic'][:60]}", icon="🎯")
                        st.rerun()

        # Action row
        action_col1, action_col2 = st.columns([1, 1])
        with action_col1:
            if st.button("🔁 Wygeneruj inne 5", use_container_width=True, key="regen_topics"):
                st.session_state["topic_suggestions"] = []
                st.session_state["topic_ai_loading"] = True
                st.rerun()
        with action_col2:
            if st.button("✖ Schowaj pomysły", use_container_width=True, key="hide_topics"):
                st.session_state["topic_suggestions"] = []
                st.rerun()

    st.markdown('<div style="margin-top:0.8rem;"></div>', unsafe_allow_html=True)


def render_generate(brand_id: str):
    page_header(
        "Generator karuzel",
        "Wpisz temat, wybierz styl — AI tworzy gotowe slajdy w ~60 sekund.",
        icon="🎠",
    )

    brand = get_brand(brand_id)
    brief = get_brief(brand_id) or {}
    completion = brand.get("brief_completion", 0.0)
    pct = int(completion * 100)

    styles = list_styles(brand_id)

    handles = brand.get("social_handles") or {}
    ig_handle = (handles.get("ig") or "").strip()
    tt_handle = (handles.get("tiktok") or "").strip()

    # Status row
    status_items = [
        ("Brief", f"{pct}%", "🧠", "#7C3AED" if pct >= 80 else "#F59E0B"),
        ("Style", str(len(styles)), "🎨", "#7C3AED" if styles else "#94A3B8"),
        ("Gotowość", "OK" if pct >= 50 and styles else "Uzupełnij", "✅" if pct >= 50 and styles else "⚠️",
         "#10B981" if pct >= 50 and styles else "#F59E0B"),
    ]
    cols = st.columns(3)
    for col, (label, val, icon, color) in zip(cols, status_items):
        with col:
            st.markdown(f"""
            <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                        padding:1rem 1.25rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
                <div style="font-size:1.5rem;">{icon}</div>
                <div style="font-size:1.3rem;font-weight:800;color:{color};line-height:1.2;margin-top:0.25rem;">{val}</div>
                <div style="font-size:0.7rem;font-weight:600;color:#64748B;text-transform:uppercase;
                            letter-spacing:0.07em;margin-top:0.2rem;">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)

    if pct < 50:
        st.warning(f"Brief uzupełniony tylko w {pct}% — uzupełnij go w zakładce **Brief marki** dla lepszych wyników.")

    if not styles:
        st.info("Nie masz jeszcze stylu — AI użyje stylu generycznego. Dodaj własne zdjęcia referencyjne w zakładce **Style**.")

    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)

    # ── Panel aktywnych i ukończonych jobów (auto-refresh co 2s) ──────────────
    _render_jobs_panel(brand_id)

    # ── AI: wymyśl najlepszy temat ─────────────────────────────────────────────
    _render_topic_ai_section(brand_id, brief)

    # ── Viral Replicator ──────────────────────────────────────────────────────
    _render_viral_replicator_section(brand_id, brief, styles)

    # ── Formularz generacji ────────────────────────────────────────────────────
    section_title("Parametry generacji", icon="⚙️")

    # Panel stylu tekstu — POZA formularzem (zawiera button "Zapisz jako default")
    # Wartosci trzymane w session_state["generate_text_settings"], submit je odczyta.
    render_text_settings_panel(brand_id, brief, key_prefix="generate", default_expanded=False)

    # Inicjalizacja powiązanego pola tekstowego (sterowane z sekcji AI powyżej)
    if "topic_input" not in st.session_state:
        st.session_state["topic_input"] = ""

    with st.form("generate_carousel"):
        topic = st.text_area(
            "Temat karuzeli",
            key="topic_input",
            placeholder=(
                "np. '3 błędy które niszczą dietę keto'\n"
                "'Dlaczego nie chudniesz mimo diety'\n"
                "'Jak zacząć keto w 7 dni bez efektu jojo'\n\n"
                "👉 Albo kliknij 'AI: 5 najlepszych pomysłów' powyżej"
            ),
            height=110,
            help="Im bardziej konkretny i wiralowy temat, tym lepsza karuzela."
        )

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            slide_count = st.slider(
                "Liczba slajdów",
                MIN_SLIDES, MAX_SLIDES, DEFAULT_SLIDES,
                help="7-9 slajdów to optimum dla IG/TikTok karuzel."
            )
        with col3:
            language = st.selectbox(
                "🌐 Język",
                options=["pl", "en"],
                format_func=lambda x: {"pl": "🇵🇱 Polski", "en": "🇬🇧 English"}[x],
                index=0,
                help="W jakim języku ma być treść slajdów. Tekst nakładamy Pillow — diakrytyki PL gwarantowane.",
            )
        with col2:
            if styles:
                style_options = {None: "— brak stylu (generyczny) —"}
                preferred_id = None
                for s in styles:
                    label = s["name"] + ("  ⭐ preferowany" if s.get("is_preferred") else "")
                    style_options[s["id"]] = label
                    if s.get("is_preferred"):
                        preferred_id = s["id"]

                default_idx = list(style_options.keys()).index(preferred_id) if preferred_id else 0
                style_id = st.selectbox(
                    "Styl wizualny",
                    options=list(style_options.keys()),
                    format_func=lambda k: style_options[k],
                    index=default_idx,
                )
            else:
                style_id = None
                st.markdown('<div style="padding-top:1.7rem;"></div>', unsafe_allow_html=True)
                st.info("Brak stylów")

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.78rem;font-weight:700;color:#475569;'
            'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.4rem;">'
            'Publikuj na</div>',
            unsafe_allow_html=True,
        )
        col_ig, col_tt = st.columns(2)
        with col_ig:
            ig_label = f"📷 Instagram  ({ig_handle})" if ig_handle else "📷 Instagram  (brak handle)"
            publish_ig = st.checkbox(ig_label, value=bool(ig_handle), disabled=not ig_handle, key="pub_ig")
        with col_tt:
            tt_label = f"🎵 TikTok  ({tt_handle})" if tt_handle else "🎵 TikTok  (brak handle)"
            publish_tt = st.checkbox(tt_label, value=bool(tt_handle), disabled=not tt_handle, key="pub_tt")

        if not ig_handle and not tt_handle:
            st.caption("ℹ️ Dodaj handle IG/TikTok w ustawieniach marki, żeby zaznaczyć platformy publikacji.")

        st.markdown('<div style="margin-top:0.25rem;"></div>', unsafe_allow_html=True)

        # Klucze: Gemini ma teraz POOL (auto-rotacja gdy klucz padnie)
        from config import GEMINI_API_KEYS as _GEMINI_KEYS
        _OAI_KEY = OPENAI_API_KEY  # zaimportowany na gorze pliku

        if _GEMINI_KEYS and len(_GEMINI_KEYS) > 1:
            from core.image_router import _alive_gemini_keys
            alive_n = len(_alive_gemini_keys())
            st.caption(
                f"🔑 Gemini pool: **{alive_n}/{len(_GEMINI_KEYS)} kluczy aktywnych** "
                f"(auto-rotacja gdy któryś wyczerpie limit)"
            )

        # Kolejność: top quality AI na górze (style transfer z reference images), gradient na dole jako fallback
        _img_options: dict[str, str] = {}
        if _GEMINI_KEYS:
            _img_options["nano_banana_pro"]  = "🟢 Nano Banana Pro (Gemini 3 Pro Image)  —  TOP JAKOŚĆ, 4K, style transfer, GRATIS"
            _img_options["nano_banana_2"]    = "🟢 Nano Banana 2 (Gemini 3.1 Flash)  —  szybkie + style transfer, GRATIS"
            _img_options["nano_banana_v25"]  = "🟢 Nano Banana (Gemini 2.5 Flash Image)  —  klasyk, GRATIS"
        if _OAI_KEY:
            _img_options["openai_v2"]        = "🔴 GPT Image 2 (OpenAI 21.04.2026)  —  najnowszy, reasoning, czytelny tekst"
            _img_options["openai_v1_high"]   = "🟠 gpt-image-1 high quality  —  starszy, ~$1.20/karuzela"
            _img_options["openai_v1_low"]    = "💛 gpt-image-1 low quality  —  starszy, ~$0.08/karuzela"
        _img_options["none"] = "⚠️ Gradient z palety (BEZ AI — tylko 2 kolory tła)"

        img_mode = st.selectbox(
            "🖼️ Generator tła slajdów",
            options=list(_img_options.keys()),
            format_func=lambda k: _img_options[k],
            index=0,
            help=(
                "Nano Banana Pro to najlepszy darmowy model do replikacji stylu. "
                "GPT Image 2 lepszy gdy potrzebujesz zdjęć produktów ze sklepu. "
                "Gradient to fallback gdy nic innego nie działa."
            ),
        )

        prefer_provider = {
            "nano_banana_pro": "gemini", "nano_banana_2": "gemini", "nano_banana_v25": "gemini",
            "openai_v1_low": "openai", "openai_v1_high": "openai", "openai_v2": "openai",
        }.get(img_mode)
        image_quality = {"openai_v1_low": "low", "openai_v1_high": "high", "openai_v2": "high"}.get(img_mode, "low")
        model_override = {
            "nano_banana_pro": "gemini-3-pro-image-preview",
            "nano_banana_2":   "gemini-3.1-flash-image-preview",
            "nano_banana_v25": "gemini-2.5-flash-image",
            "openai_v2":       "gpt-image-2",
        }.get(img_mode)
        use_ai_images = img_mode != "none"

        # Info gdy user wybrał AI a nie ma stylu z referencjami
        _selected_style = next((s for s in styles if s["id"] == style_id), None) if style_id else None
        _ref_count = len(_selected_style.get("reference_image_paths") or []) if _selected_style else 0
        if use_ai_images:
            if _ref_count > 0:
                st.caption(f"✓ Użyję {_ref_count} zdjęć referencyjnych ze stylu **{_selected_style['name']}** do style transfer.")
            else:
                st.caption("⚠️ Wybrany styl nie ma zdjęć referencyjnych — AI wygeneruje obrazy z samego opisu (gorszy efekt). Dodaj 5-10 zdjęć w Style Library.")

        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)

        # ── Tryb tekstu ────────────────────────────────────────────────────
        text_mode_options = {
            "overlay": "✍️ Pillow overlay  —  Montserrat Black + czarny obrys (TikTok style), 100% poprawne polskie znaki",
            "inline":  "🤖 AI wbudowany  —  tekst generowany razem z obrazem (Nano Banana Pro / GPT Image 2). Eksperymentalne, może masakrować polski",
        }
        text_mode = st.selectbox(
            "📝 Tekst na slajdach",
            options=list(text_mode_options.keys()),
            format_func=lambda k: text_mode_options[k],
            index=0,
            help=(
                "Pillow = pewniak: gwarantowane diakrytyki PL, czcionka jak na TikToku, szybkie. "
                "AI wbudowany = wygląda spójniej z obrazem (jeden styl wizualny), ale modele AI "
                "czasem gubią litery, szczególnie polskie. Spróbuj obu i porównaj."
            ),
        )
        if text_mode == "inline" and not use_ai_images:
            st.caption("⚠️ Tryb 'AI wbudowany' wymaga generatora AI (Nano Banana / GPT Image). Wybierz model wyżej.")
        if text_mode == "inline" and language == "pl":
            st.caption("⚠️ AI inline + język polski = ryzyko zmasakrowanych ą/ę/ś/ć. Dla polskiego bezpieczniej zostać przy Pillow.")

        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)

        # Custom instructions — wieksza kontrola dla usera
        gen_custom_text = st.text_area(
            "📝 Dodatkowe instrukcje dla AI — TEKST (opcjonalne)",
            value="",
            height=85,
            placeholder=(
                "Co AI ma uwzględnić, czego unikać, na co uważać. Przykłady:\n"
                "• 'nie używaj słów darmo / gratis'\n"
                "• 'każdy slajd ma kończyć się pytaniem'\n"
                "• 'unikaj clickbaitu, bądź konkretny'\n"
                "• 'nie wymieniaj nazw konkurencji'"
            ),
            key="gen_custom_text",
            help="Te instrukcje dostają WYŻSZY priorytet niż domyślne reguły. NIE łamią forbidden_claims z briefa.",
        )

        gen_custom_image = st.text_area(
            "🎨 Dodatkowe instrukcje dla AI — OBRAZY (opcjonalne)",
            value="",
            height=85,
            placeholder=(
                "Co zmienić w obrazach AI. Przykłady:\n"
                "• 'tła ciemne, dużo cieni'\n"
                "• 'nie generuj twarzy ludzi, tylko sylwetki/cienie'\n"
                "• 'styl polaroid, instax, organic feel'\n"
                "• 'cinematic, anamorphic lens flare'"
            ),
            key="gen_custom_image",
        )

        submitted = st.form_submit_button("🎠 Generuj karuzelę", type="primary", use_container_width=True)

    if submitted:
        if not topic.strip():
            st.error("Wpisz temat karuzeli przed generowaniem.")
            return

        job_id = _start_generation_job(brand_id, {
            "topic": topic,
            "style_id": style_id,
            "slide_count": slide_count,
            "use_ai_images": use_ai_images,
            "prefer_provider": prefer_provider,
            "image_quality": image_quality,
            "model_override": model_override,
            "language": language,
            "text_mode": text_mode,
            "text_settings": st.session_state.get("generate_text_settings"),
            "custom_instructions": gen_custom_text,
            "image_custom_instructions": gen_custom_image,
        })
        st.success(
            f"✅ Karuzela ruszyła w tle (job `{job_id}`). "
            f"Możesz wpisać kolejny temat i odpalić następną — będą generować się równolegle. "
            f"Postęp widoczny w panelu na górze strony."
        )
        st.rerun()


def _get_regen_jobs() -> dict:
    return st.session_state.setdefault("slide_regen_jobs", {})


def _start_slide_regen_job(carousel_id: str, slide_index: int,
                              image_instructions: str,
                              new_headline: str, new_body: str,
                              regenerate_image: bool) -> str:
    jobs = _get_regen_jobs()
    job_id = uuid.uuid4().hex[:8]
    mode_label = "Regeneruję obraz + tekst..." if regenerate_image else "Aktualizuję tekst (bez nowego obrazu)..."
    jobs[job_id] = {
        "id": job_id,
        "carousel_id": carousel_id,
        "slide_index": slide_index,
        "status": "running",
        "stage": mode_label,
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
        "regenerate_image": regenerate_image,
    }
    thread = threading.Thread(
        target=_run_slide_regen_job,
        args=(jobs, job_id, carousel_id, slide_index, image_instructions,
              new_headline, new_body, regenerate_image),
        daemon=True,
    )
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def _run_slide_regen_job(jobs: dict, job_id: str, carousel_id: str,
                           slide_index: int, image_instructions: str,
                           new_headline: str, new_body: str,
                           regenerate_image: bool):
    try:
        from core.carousel_generator import regenerate_single_slide
        new_h = new_headline if new_headline.strip() else None
        new_b = new_body if new_body.strip() else None
        result = regenerate_single_slide(
            carousel_id=carousel_id,
            slide_index=slide_index,
            image_instructions=image_instructions,
            new_headline=new_h,
            new_body=new_b,
            regenerate_image=regenerate_image,
        )
        jobs[job_id]["status"] = "done"
        jobs[job_id]["result"] = result
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["traceback"] = traceback.format_exc()
    finally:
        jobs[job_id]["finished_at"] = time.time()


@st.fragment(run_every=2)
def _render_slide_regen_editor(carousel: dict, slide_index: int):
    """Inline editor pod kazdym slajdem: zmiana tekstu + regeneracja obrazu."""
    car_id = carousel["id"]
    slide = carousel["slides"][slide_index]
    kp = f"regen_{car_id}_{slide_index}"

    # Sprawdz czy juz jakis regen-job lecial dla tego slajdu
    regen_jobs = _get_regen_jobs()
    my_jobs = [j for j in regen_jobs.values()
                if j["carousel_id"] == car_id and j["slide_index"] == slide_index]
    active = next((j for j in my_jobs if j["status"] == "running"), None)
    last_done = next((j for j in sorted(my_jobs, key=lambda x: x["started_at"], reverse=True)
                       if j["status"] in ("done", "error")), None)

    if active:
        elapsed = int(time.time() - active["started_at"])
        st.info(f"🎨 {active['stage']} ({elapsed}s)")
        return

    # Po zakonczeniu joba: zaktualizuj wyswietlany slajd najnowszymi danymi z DB
    if last_done and last_done["status"] == "done" and last_done.get("result"):
        new_carousel = last_done["result"]
        if new_carousel and new_carousel.get("slides"):
            new_slide = new_carousel["slides"][slide_index]
            # Pokaz odswiezony obraz + tekst
            if new_slide.get("image_path"):
                try:
                    st.image(new_slide["image_path"], use_container_width=True,
                              caption="✅ Po regeneracji")
                except Exception:
                    pass
            slide = new_slide  # uzyj nowych wartosci ponizej w placeholderach

    with st.expander("✏️ Popraw ten slajd", expanded=False):
        new_h = st.text_input(
            "Nowy headline (puste = bez zmian)",
            value="",
            key=f"{kp}_h",
            placeholder=slide.get("headline", "")[:60],
        )
        new_b = st.text_input(
            "Nowy body (puste = bez zmian)",
            value="",
            key=f"{kp}_b",
            placeholder=(slide.get("body", "") or "")[:80],
        )
        img_inst = st.text_area(
            "🎨 Co zmienić w obrazie? (puste = obraz zostaje, zmieni się tylko tekst)",
            value="",
            height=70,
            key=f"{kp}_img",
            placeholder=(
                "np. 'więcej kontrastu, ciemniejsze tło' / "
                "'bez ludzi' / 'inna kompozycja, tekst po prawej'"
            ),
        )

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            btn_text = st.button(
                "📝 Tylko tekst",
                key=f"{kp}_btn_text",
                use_container_width=True,
                disabled=not (new_h.strip() or new_b.strip()),
                help="Zachowuje obecny obraz, zmienia tylko nagłówek/body. Szybkie, nie kosztuje AI."
            )
        with col_btn2:
            btn_full = st.button(
                "🎨 Tekst + nowy obraz",
                key=f"{kp}_btn_full",
                type="primary",
                use_container_width=True,
                disabled=not (img_inst.strip() or new_h.strip() or new_b.strip()),
                help="Generuje nowe tło AI + nakłada nowy tekst. Wolniejsze, używa kwoty AI."
            )

        if btn_text:
            if not (new_h.strip() or new_b.strip()):
                st.warning("Wpisz nowy headline lub body.")
            else:
                _start_slide_regen_job(car_id, slide_index, "", new_h, new_b,
                                          regenerate_image=False)
                st.rerun()
        elif btn_full:
            _start_slide_regen_job(car_id, slide_index, img_inst, new_h, new_b,
                                      regenerate_image=True)
            st.rerun()

        if last_done and last_done["status"] == "error":
            st.error(f"❌ Błąd: {last_done['error']}")


def _show_carousel_preview(carousel: dict):
    st.markdown('<hr>', unsafe_allow_html=True)

    section_title("Podgląd slajdów", icon="🖼️")

    slides = carousel.get("slides", [])

    # Diagnostyka clone_visual (tylko gdy karuzela byla zrobiona viral replicatorem)
    if carousel.get("source") == "viral_replicator":
        applied = sum(1 for s in slides if s.get("_visual_applied"))
        n = len(slides)
        any_visual_attempt = any("_visual_applied" in s for s in slides)
        if any_visual_attempt:
            if applied == 0:
                st.warning(
                    f"⚠️ Tryb 'Skopiuj styl wizualny viralu' był włączony, ale AI nie zwrócił "
                    f"`viral_visual` na żadnym slajdzie ({applied}/{n}). Slajdy dostały styl marki. "
                    f"Spróbuj jeszcze raz lub wklej inny viral z czytelnym tekstem."
                )
            elif applied < n:
                st.info(
                    f"ℹ️ Styl viralu zaaplikowany na {applied}/{n} slajdach. "
                    f"Pozostałe użyły stylu marki (AI nie zwrócił dla nich `viral_visual`)."
                )
            else:
                st.success(f"✅ Styl wizualny viralu zaaplikowany na wszystkich {n}/{n} slajdach.")
            with st.expander("🔍 Debug: per-slajd override stylu z viralu"):
                for idx, s in enumerate(slides):
                    if s.get("_visual_applied"):
                        st.markdown(f"**Slajd {idx+1}** — ✅ override zastosowany:")
                        st.json(s.get("_visual_override", {}))
                    else:
                        st.markdown(f"**Slajd {idx+1}** — ⚪ użyto stylu marki "
                                     f"(AI nie zwrócił viral_visual lub było niekompletne)")

        # Surowa odpowiedz Claude — dla debugowania
        try:
            from pathlib import Path as _P
            from config import CAROUSELS_DIR as _CD
            raw_path = _P(_CD) / carousel.get("brand_id", "") / carousel["id"] / "claude_raw_response.json"
            if raw_path.exists():
                with st.expander("🐛 Debug: surowa odpowiedź Claude Vision (kliknij gdy coś nie działa)"):
                    st.caption(f"Plik: `{raw_path}`")
                    try:
                        import json as _json
                        raw_content = _json.loads(raw_path.read_text(encoding="utf-8"))
                        st.json(raw_content)
                    except Exception as _e:
                        st.code(raw_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if slides:
        cols = st.columns(min(len(slides), 4))
        for i, slide in enumerate(slides):
            with cols[i % len(cols)]:
                if slide.get("image_path"):
                    try:
                        st.image(slide["image_path"], use_container_width=True)
                    except Exception:
                        st.markdown(f"""
                        <div style="background:#F5F3FF;border:1px dashed #DDD6FE;border-radius:10px;
                                    padding:2rem;text-align:center;color:#8B5CF6;font-size:0.8rem;">
                            Slajd {i+1}
                        </div>
                        """, unsafe_allow_html=True)
                st.markdown(f"""
                <div style="padding:0.4rem 0;">
                    <div style="font-size:0.8rem;font-weight:700;color:#0F172A;line-height:1.4;">
                        {slide.get('headline', '')[:60]}
                    </div>
                    {'<div style="font-size:0.72rem;color:#64748B;margin-top:0.2rem;">' + slide.get('body', '')[:80] + '...</div>' if slide.get('body') else ''}
                </div>
                """, unsafe_allow_html=True)

                # Popraw ten slajd — inline editor z custom instructions
                _render_slide_regen_editor(carousel, i)

    # Caption + hashtags
    section_title("Caption i hashtagi", icon="✍️")

    st.text_area(
        "Caption",
        value=carousel.get("caption", ""),
        height=130,
        key=f"cap_{carousel['id']}",
        help="Skopiuj i wklej bezpośrednio na Instagram/TikTok."
    )

    hashtags = carousel.get("hashtags") or []
    if hashtags:
        ht_str = "  ".join(hashtags)
        st.text_area(
            "Hashtagi",
            value=ht_str,
            height=60,
            key=f"ht_{carousel['id']}",
        )

    # Export - direct download_button (jednoklik, bez session_state issues)
    st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
    col_a, col_b = st.columns([1, 3])
    with col_a:
        try:
            zip_path = export_carousel_as_zip(carousel["id"])
            with open(zip_path, "rb") as f:
                zip_bytes = f.read()
            st.download_button(
                "⬇️ Pobierz ZIP",
                data=zip_bytes,
                file_name=f"karuzela_{carousel['id']}.zip",
                mime="application/zip",
                key=f"dl_{carousel['id']}",
                use_container_width=True,
                type="primary",
            )
        except Exception as e:
            st.error(f"Błąd eksportu ZIP: {e}")

    # Publer auto-publish section
    st.markdown('<div style="margin-top:1.5rem;"></div>', unsafe_allow_html=True)
    show_publer_section(carousel)


def show_publer_section(carousel: dict, key_suffix: str = "gen"):
    """Sekcja zaplanowanego wysyłania karuzeli do Publer.

    key_suffix: rozróżnia widgety gdy ta sama karuzela renderuje się w wielu miejscach
                (Generator vs Historia) — Streamlit wymaga unikalnych kluczy.
    """
    with st.expander("📤 Wyślij do Publer (auto-publikacja)", expanded=bool(PUBLER_API_KEY)):

        if not PUBLER_API_KEY:
            st.info(
                "**Brak klucza Publer API.**\n\n"
                "Aby włączyć auto-publikację:\n"
                "1. Zarejestruj się na publer.com (plan Professional ~$12/mies)\n"
                "2. Połącz konta Instagram i TikTok w Publer\n"
                "3. W Publer → Settings → API → wygeneruj klucz\n"
                "4. Dodaj do Streamlit Secrets:\n"
            )
            st.code('PUBLER_API_KEY = "twój_klucz_publer"', language="toml")
            return

        from core.publisher_publer import PublerClient, PublerError

        car_id = carousel["id"]
        kpref = f"{key_suffix}_{car_id}"
        accounts_key = "publer_accounts"

        # Klient jest zawsze tworzony — potrzebny też do delete/reschedule
        client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)

        # ── Załaduj konta + Test ──────────────────────────────────────────
        col_load, col_test, _ = st.columns([1, 1, 2])
        with col_load:
            if st.button("🔄 Załaduj konta", key=f"load_acc_{kpref}"):
                try:
                    if not PUBLER_WORKSPACE_ID:
                        workspaces = client.get_workspaces()
                        if workspaces:
                            client.set_workspace(str(workspaces[0].get("id", "")))
                    accounts = client.get_accounts()
                    st.session_state[accounts_key] = accounts
                    st.success(f"Załadowano {len(accounts)} kont.")
                except PublerError as e:
                    st.error(f"Błąd połączenia: {e}")
                except Exception as e:
                    st.error(f"Nieoczekiwany błąd: {e}")
                    st.exception(e)
        with col_test:
            if st.button("🩺 Test API", key=f"test_pub_{kpref}",
                          help="Sprawdza klucz, workspace i listę kont — diagnostyka."):
                _run_publer_diagnostic()

        accounts: list[dict] = st.session_state.get(accounts_key, [])
        if not accounts:
            st.caption("Kliknij 'Załaduj konta Publer' żeby zobaczyć połączone konta.")
            return

        # ── Picker kont ───────────────────────────────────────────────────
        ig_accounts = [a for a in accounts if a.get("provider") in ("instagram", "ig")]
        tt_accounts = [a for a in accounts if a.get("provider") in ("tiktok", "tt")]

        def _account_label(a: dict) -> str:
            return a.get("name") or a.get("username") or str(a.get("id", "?"))

        selected_ig: list[str] = []
        selected_tt: list[str] = []

        col_ig, col_tt = st.columns(2)
        with col_ig:
            if ig_accounts:
                chosen = st.multiselect(
                    "📷 Instagram",
                    options=[a["id"] for a in ig_accounts],
                    format_func=lambda aid: _account_label(
                        next((a for a in ig_accounts if a["id"] == aid), {})
                    ),
                    key=f"pub_ig_sel_{kpref}",
                )
                selected_ig = chosen
            else:
                st.caption("Brak kont Instagram w Publer")

        with col_tt:
            if tt_accounts:
                chosen = st.multiselect(
                    "🎵 TikTok",
                    options=[a["id"] for a in tt_accounts],
                    format_func=lambda aid: _account_label(
                        next((a for a in tt_accounts if a["id"] == aid), {})
                    ),
                    key=f"pub_tt_sel_{kpref}",
                )
                selected_tt = chosen
            else:
                st.caption("Brak kont TikTok w Publer")

        # ── Data i godzina (czas polski Europe/Warsaw, konwertujemy na UTC do Publera) ──
        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        try:
            from zoneinfo import ZoneInfo
            warsaw_tz = ZoneInfo("Europe/Warsaw")
        except Exception:
            warsaw_tz = timezone(timedelta(hours=2))  # fallback CEST

        now_warsaw = datetime.now(warsaw_tz)
        # Default: TERAZ + 5 min (Publer wymaga min lead time, +5min jest minimum dla "wyslij teraz")
        default_dt = now_warsaw + timedelta(minutes=5)

        col_d, col_t = st.columns(2)
        with col_d:
            sched_date = st.date_input(
                "Data publikacji (czas polski)",
                value=default_dt.date(),
                min_value=now_warsaw.date(),
                key=f"pub_date_{kpref}",
            )
        with col_t:
            sched_time = st.time_input(
                "Godzina (czas polski)",
                value=default_dt.replace(second=0, microsecond=0).time(),
                step=60,  # co 1 min — precyzyjna kontrola
                key=f"pub_time_{kpref}",
            )

        # Wprowadzony czas to zawsze czas polski → konwertuj na UTC dla Publera
        scheduled_local = datetime.combine(sched_date, sched_time).replace(tzinfo=warsaw_tz)
        scheduled_utc = scheduled_local.astimezone(timezone.utc)
        scheduled_iso = scheduled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        st.caption(
            f"Zaplanowano na: **{scheduled_local.strftime('%d.%m.%Y o %H:%M')}** (czas polski) "
            f"= {scheduled_utc.strftime('%H:%M')} UTC"
        )

        # Lead time check — Publer w praktyce potrzebuje ~5 min zeby przetworzyc
        lead_minutes = (scheduled_local - now_warsaw).total_seconds() / 60
        if lead_minutes < 4:
            st.warning(
                f"⚠️ Zaplanowano za **{int(lead_minutes)} min** — Publer może to odrzucić. "
                "Daj minimum **5 minut** zapasu, żeby kolejka API zdążyła przetworzyć post."
            )

        # ── Wyślij ────────────────────────────────────────────────────────
        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)

        # Status aktywnego/zakończonego publer joba dla tej karuzeli
        publer_jobs = _get_publer_jobs()
        my_pjobs = [j for j in publer_jobs.values() if j["carousel_id"] == car_id]
        active_pjob = next((j for j in my_pjobs if j["status"] == "running"), None)

        # Czy karuzela jest JUŻ zaplanowana w Publerze? (ma publer_post_id)
        existing_post_id = (carousel.get("publer_post_id") or "").strip()
        existing_status = (carousel.get("status") or "").strip()
        is_already_scheduled = bool(existing_post_id and existing_status == "scheduled")

        if active_pjob:
            st.info(f"🚀 Wysyłam do Publer... {int(active_pjob['progress']*100)}% — {active_pjob['stage']}")
            st.progress(max(0.05, min(1.0, active_pjob["progress"])))
        elif is_already_scheduled:
            # Już zaplanowane — blok "Wyślij ponownie" + opcje reschedule/anuluj
            existing_sched = carousel.get("scheduled_at", "")
            try:
                # scheduled_at w bazie jest w UTC — konwertuj na czas polski do wyswietlenia
                existing_sched_local = datetime.fromisoformat(existing_sched.replace("Z", "+00:00")) \
                    .astimezone(warsaw_tz).strftime("%d.%m.%Y o %H:%M")
            except Exception:
                existing_sched_local = existing_sched
            st.success(
                f"✅ **Już zaplanowane w Publerze** na **{existing_sched_local}** (czas polski) "
                f"(post id: `{existing_post_id}`).\n\n"
                f"Aby zmienic czas — uzyj guzikow ponizej (skasuje stary post zeby uniknac duplikatu)."
            )

            col_resched, col_cancel = st.columns(2)
            with col_resched:
                if st.button(
                    "🔄 Zmień termin (skasuje stary)",
                    key=f"reschedule_{kpref}",
                    type="primary",
                    disabled=not (selected_ig or selected_tt),
                    help="Kasuje stary scheduled post w Publerze i tworzy nowy w wybranym powyżej terminie.",
                ):
                    try:
                        client.delete_post(existing_post_id)
                        update_carousel(car_id, publer_post_id="", status="draft", scheduled_at="")
                        # Od razu start nowego scheduling job-a
                        pjob_id = _start_publer_job(carousel, selected_ig, selected_tt, scheduled_iso)
                        st.success(f"Stary post skasowany. Tworzę nowy (`{pjob_id}`).")
                        st.rerun()
                    except PublerError as e:
                        st.error(
                            f"❌ Nie udało się skasować starego postu: {e}\n\n"
                            f"Skasuj go ręcznie na publer.com → Calendar (post id `{existing_post_id}`), "
                            f"potem klik tu jeszcze raz."
                        )
            with col_cancel:
                if st.button(
                    "❌ Anuluj publikację",
                    key=f"cancel_{kpref}",
                    help="Kasuje scheduled post w Publerze. Karuzela wraca do statusu draft.",
                ):
                    try:
                        client.delete_post(existing_post_id)
                        update_carousel(car_id, publer_post_id="", status="draft", scheduled_at="")
                        st.success("Anulowano publikację. Możesz zaplanować ponownie.")
                        st.rerun()
                    except PublerError as e:
                        st.error(f"❌ Nie udało się skasować: {e}")
        else:
            # Pierwsze wysłanie — normalny flow
            if st.button(
                "🚀 Wyślij do Publer",
                key=f"send_publer_{kpref}",
                type="primary",
                disabled=not (selected_ig or selected_tt),
            ):
                pjob_id = _start_publer_job(carousel, selected_ig, selected_tt, scheduled_iso)
                st.success(f"Job ruszył w tle (`{pjob_id}`). Postęp pojawi się tutaj.")
                st.rerun()

        # Pokaż wyniki / błędy poprzednich publer-jobów dla tej karuzeli
        for j in sorted(my_pjobs, key=lambda x: x["finished_at"] or 0, reverse=True):
            res = j.get("result") or {}
            if j["status"] == "done":
                pid = res.get("post_id", "ok")
                final_state = (res.get("final_job_status") or {})
                final_state_str = final_state.get("status") or final_state.get("state") or None

                if final_state_str:
                    st.success(f"✅ Publer potwierdził — post id `{pid}`, job state: `{final_state_str}`")
                else:
                    st.warning(
                        f"⚠️ API przyjęło post (job `{pid}`), ale **nie udało się potwierdzić** że "
                        f"Publer go faktycznie utworzył (polling job-status wygasł po 20s). "
                        f"Sprawdź ręcznie publer.com → Calendar / Drafts."
                    )
                st.caption(
                    "ℹ️ Otwórz publer.com → Calendar / Drafts żeby zobaczyć czy post tam jest. "
                    "Jeśli go nie ma mimo 'OK', sprawdź szczegóły poniżej (szczególnie 'Odpowiedź Publer')."
                )

                poll_err = res.get("schedule_result", {}).get("poll_error")
                if poll_err:
                    st.warning(f"⚠️ Błąd podczas sprawdzania statusu job-a: `{poll_err}`")

                with st.expander("📤 Wysłany payload"):
                    st.json(res.get("schedule_result", {}).get("request_payload", {}))
                with st.expander("📥 Odpowiedź Publer (raw)"):
                    st.json(res.get("schedule_result", {}).get("response", {}))
                if res.get("final_job_status"):
                    with st.expander("⚙️ Status job-a w Publer"):
                        st.json(res["final_job_status"])

            elif j["status"] == "error":
                st.error(f"❌ Błąd Publer: {j['error']}")
                if j.get("traceback"):
                    with st.expander("Szczegóły techniczne"):
                        st.code(j["traceback"])


# _send_to_publer został zastąpiony wątkiem _start_publer_job + _run_publer_job (powyżej).
# Synchroniczna wersja przerywała się przy auto-refresh fragmentu co 2s.


# ─────────────────────────────────────────────────────────────
# VIRAL REPLICATOR — sekcja UI
# ─────────────────────────────────────────────────────────────

def _render_viral_replicator_section(brand_id: str, brief: dict, styles: list):
    """Sekcja: wklej URL viralu TT/IG -> AI replikuje strukture na karuzele dla marki."""
    st.markdown(
        """<div style="background:linear-gradient(135deg,#FEF3C7,#FDE68A);border:1px solid #F59E0B;
            border-radius:14px;padding:1rem 1.25rem;margin-bottom:1rem;">
            <div style="font-size:1.05rem;font-weight:800;color:#78350F;margin-bottom:0.3rem;">
                🎬 Viral Replicator
            </div>
            <div style="font-size:0.85rem;color:#92400E;line-height:1.5;">
                Wklej link viralowego posta z TikToka lub Instagrama. AI zanalizuje
                strukture, hook i progresje narracji, a potem zreplikuje je dla Twojej
                marki (z briefa) — nowe tla, nowe copy, ten sam DNA. CTA na ostatnim
                slajdzie pójdzie na <code>brief.cta_url</code>.
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    cta_url = (brief.get("cta_url") or "").strip()
    if not cta_url:
        st.warning(
            "⚠️ Brak `cta_url` w briefie marki — bez linku CTA na ostatnim slajdzie "
            "bedzie generyczne. Wpisz w **Brief marki → Link CTA**, np. `flipzone.pl`."
        )

    with st.form("viral_replicator"):
        viral_url = st.text_input(
            "Link viralu (TikTok lub Instagram)",
            placeholder="np. https://www.tiktok.com/@user/video/1234567890 lub https://www.instagram.com/p/abc123/",
            help="Obsluguje TikTok karuzele zdjeciowe, TikTok wideo (cover frame) "
                 "oraz Instagram posty/karuzele. Scraping przez yt-dlp (darmowy).",
        )

        col_lang, col_style = st.columns([1, 2])
        with col_lang:
            v_language = st.selectbox(
                "🌐 Język repliki",
                options=["pl", "en"],
                format_func=lambda x: {"pl": "🇵🇱 Polski", "en": "🇬🇧 English"}[x],
                index=0,
                key="viral_lang",
            )
        with col_style:
            if styles:
                v_style_opts = {None: "— bez stylu —"}
                preferred_id = None
                for s in styles:
                    label = s["name"] + ("  ⭐" if s.get("is_preferred") else "")
                    v_style_opts[s["id"]] = label
                    if s.get("is_preferred"):
                        preferred_id = s["id"]
                v_default_idx = list(v_style_opts.keys()).index(preferred_id) if preferred_id else 0
                v_style_id = st.selectbox(
                    "Styl wizualny dla nowych slajdów",
                    options=list(v_style_opts.keys()),
                    format_func=lambda k: v_style_opts[k],
                    index=v_default_idx,
                    key="viral_style",
                )
            else:
                v_style_id = None
                st.caption("Brak stylów — replika użyje generycznego.")

        # Generator obrazów — uproszczony wybór (Nano Banana Pro / gradient fallback)
        from config import GEMINI_API_KEYS as _gk
        v_use_ai = bool(_gk)
        if v_use_ai:
            st.caption("🟢 Tła nowych slajdów: **Nano Banana Pro** (Gemini 3 Pro Image, GRATIS)")
            v_prefer = "gemini"
            v_model = "gemini-3-pro-image-preview"
        else:
            st.caption("⚠️ Brak klucza Gemini — slajdy dostaną gradient z palety stylu.")
            v_prefer = None
            v_model = None

        # Tryb wizualny: kopiuj styl tekstu z viralu zamiast uzywac stylu marki
        v_clone_visual = st.checkbox(
            "🎨 Skopiuj też styl wizualny tekstu z viralu (czcionka, pozycja, grubość, kolor — 1:1)",
            value=False,
            key="viral_clone_visual",
            help=(
                "WYŁĄCZONE = tekst jest renderowany w stylu Twojej marki (font, kolory, pozycja z brand settings).\n"
                "WŁĄCZONE = AI analizuje każdy slajd viralu i odtwarza wygląd tekstu 1:1: "
                "tę samą pozycję, kolor, grubość czcionki, CAPS, obrys. Tła nadal generowane AI."
            ),
        )

        # Custom instructions od usera — większa kontrola
        v_custom_text = st.text_area(
            "📝 Dodatkowe instrukcje dla AI — TEKST (opcjonalne)",
            value="",
            height=85,
            placeholder=(
                "Co AI ma uwzględnić, czego unikać, na co uważać. Przykłady:\n"
                "• 'nie używaj słowa darmo'\n"
                "• 'dodaj liczby do każdego nagłówka'\n"
                "• 'CTA ma być bardziej agresywny, w stylu \"OSTATNIE 24H\"'\n"
                "• 'nie zmieniaj słowa z viralu o pieniądzach na walutę USD'"
            ),
            key="viral_custom_text",
            help="Te instrukcje dostają WYŻSZY priorytet niż domyślne reguły system promptu.",
        )

        v_custom_image = st.text_area(
            "🎨 Dodatkowe instrukcje dla AI — OBRAZY (opcjonalne)",
            value="",
            height=85,
            placeholder=(
                "Co zmienić w obrazach AI. Przykłady:\n"
                "• 'tła w odcieniach niebieskiego, mniej saturacji'\n"
                "• 'nie generuj ludzi'\n"
                "• 'dodaj subtle grain effect, vintage look'\n"
                "• 'minimalistyczne, dużo białej przestrzeni'"
            ),
            key="viral_custom_image",
        )

        v_submitted = st.form_submit_button("🎬 Replikuj viralu", type="primary", use_container_width=True)

    if v_submitted:
        if not viral_url.strip():
            st.error("Wklej link viralu zanim klikniesz Replikuj.")
            return
        url_l = viral_url.strip().lower()
        if not ("tiktok.com" in url_l or "instagram.com" in url_l):
            st.error("Link musi byc z tiktok.com lub instagram.com.")
            return

        job_id = _start_viral_job(brand_id, {
            "url": viral_url.strip(),
            "style_id": v_style_id,
            "use_ai_images": v_use_ai,
            "prefer_provider": v_prefer,
            "image_quality": "low",
            "model_override": v_model,
            "language": v_language,
            "text_settings": st.session_state.get("generate_text_settings"),
            "clone_visual": v_clone_visual,
            "custom_instructions": v_custom_text,
            "image_custom_instructions": v_custom_image,
        })
        st.success(
            f"✅ Replikacja ruszyła w tle (job `{job_id}`). yt-dlp pobiera viralu, "
            f"Claude Vision analizuje strukture, potem nowa karuzela. "
            f"Postęp w panelu na górze."
        )
        st.rerun()
