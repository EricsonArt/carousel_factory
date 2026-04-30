"""
Zakładka 🤖 Automat — pełna automatyzacja: generuj + publikuj bez udziału użytkownika.
Kliknij Start raz, system wygeneruje N karuzel i zaplanuje je w Publer na wybrane dni.
"""
import json
import threading
import time
from datetime import datetime, timezone

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from config import PUBLER_API_KEY, PUBLER_WORKSPACE_ID, SLOT_HOURS
from db import get_brand, get_brief, list_styles, get_automation_config, update_automation_config
from ui.theme import page_header, section_title
from ui.text_settings import render_text_settings_panel


# ─────────────────────────────────────────────────────────────
# MODEL OPTIONS
# ─────────────────────────────────────────────────────────────

_MODEL_PARAMS = {
    "nano_banana_pro": ("gemini", "gemini-3-pro-image-preview", "low"),
    "nano_banana_2":   ("gemini", "gemini-3.1-flash-image-preview", "low"),
    "gradient":        (None, None, "low"),
}
_MODEL_LABELS = {
    "nano_banana_pro": "🟢 Nano Banana Pro (Gemini 3) — TOP JAKOŚĆ, GRATIS",
    "nano_banana_2":   "🟢 Nano Banana 2 (Gemini 3.1 Flash) — szybsze, GRATIS",
    "gradient":        "⚠️ Gradient z palety (bez AI — brak klucza Gemini)",
}


# ─────────────────────────────────────────────────────────────
# JOB STATE
# ─────────────────────────────────────────────────────────────

def _get_auto_job(brand_id: str) -> dict:
    jobs = st.session_state.setdefault("auto_jobs", {})
    return jobs.get(brand_id, {})


def _set_auto_job(brand_id: str, job: dict):
    jobs = st.session_state.setdefault("auto_jobs", {})
    jobs[brand_id] = job


def _start_automation(brand_id: str, params: dict):
    job = {
        "brand_id": brand_id,
        "status": "running",
        "stage": "Inicjalizacja...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "results": [],
        "error": None,
        "traceback": None,
    }
    _set_auto_job(brand_id, job)

    thread = threading.Thread(
        target=_run_auto_thread,
        args=(brand_id, job, params),
        daemon=True,
    )
    add_script_run_ctx(thread)
    thread.start()


def _run_auto_thread(brand_id: str, job: dict, params: dict):
    from core.auto_scheduler import run_automation_batch
    run_automation_batch(
        job_dict=job,
        brand_id=brand_id,
        brand_name=params["brand_name"],
        niche=params["niche"],
        posts_per_day=params["posts_per_day"],
        days_ahead=params["days_ahead"],
        style_id=params["style_id"],
        ig_account_ids=params["ig_account_ids"],
        tt_account_ids=params["tt_account_ids"],
        language=params["language"],
        model_override=params["model_override"],
        image_quality=params["image_quality"],
        prefer_provider=params["prefer_provider"],
        publer_api_key=params["publer_api_key"],
        publer_workspace_id=params["publer_workspace_id"],
        slots=params["slots"],
        text_settings=params.get("text_settings"),
    )


# ─────────────────────────────────────────────────────────────
# PROGRESS PANEL (auto-refresh)
# ─────────────────────────────────────────────────────────────

@st.fragment(run_every=3)
def _render_progress(brand_id: str):
    job = _get_auto_job(brand_id)
    if not job:
        return

    status = job.get("status", "")

    if status == "running":
        st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
        pct = max(0.02, min(1.0, job.get("progress", 0.0)))
        elapsed = int(time.time() - (job.get("started_at") or time.time()))
        stage = job.get("stage", "...")

        with st.container(border=True):
            st.markdown(
                f"""<div style="display:flex;justify-content:space-between;align-items:baseline;
                                margin-bottom:0.5rem;">
                    <div style="font-size:1rem;font-weight:700;color:#0F172A;">
                        🔄 Automatyzacja działa
                    </div>
                    <div style="font-size:1.1rem;font-weight:800;color:#7C3AED;">
                        {int(pct*100)}%
                    </div>
                </div>
                <div style="background:#1E293B;color:#F8FAFC;padding:0.7rem 1rem;border-radius:10px;
                            font-size:0.9rem;font-weight:500;line-height:1.4;margin-bottom:0.6rem;
                            font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;">
                    {stage}
                </div>""",
                unsafe_allow_html=True,
            )
            st.progress(pct)
            st.caption(f"⏱️ {elapsed}s   ·   strona odświeża się co 3s")

    elif status == "done":
        results = job.get("results", [])
        scheduled = [r for r in results if r.get("status") == "scheduled"]
        generated = [r for r in results if r.get("status") == "generated_only"]
        errors = [r for r in results if r.get("status") not in ("scheduled", "generated_only")]

        ok_count = len(scheduled) + len(generated)
        if scheduled:
            st.success(f"✅ Automatyzacja gotowa! **{len(scheduled)}** karuzel zaplanowanych w Publer.")
        elif generated:
            st.success(f"✅ Wygenerowano **{len(generated)}** karuzel (bez Publer — dostępne w Historii).")
        else:
            st.warning("Automatyzacja zakończona, ale żadna karuzela nie powiodła się.")

        if scheduled or generated:
            section_title("Harmonogram", icon="📅")

            total_fallback = sum(r.get("fallback_slides", 0) for r in scheduled + generated)
            total_slides = sum(r.get("total_slides", 0) for r in scheduled + generated)
            if total_fallback > 0:
                st.warning(
                    f"⚠️ **{total_fallback} z {total_slides} slajdów** dostało gradient zamiast AI obrazu "
                    f"(rate-limit Gemini lub padł generator). Karuzele z fallbackiem oznaczone 🟡 niżej."
                )

            ok_items = sorted(scheduled + generated, key=lambda r: r.get("scheduled_at", ""))
            for r in ok_items:
                dt_str = r.get("scheduled_at", "")
                try:
                    dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
                    dt_label = dt.strftime("%d.%m.%Y  %H:%M UTC")
                except Exception:
                    dt_label = dt_str
                base_icon = "📅" if r["status"] == "scheduled" else "📁"
                fb = r.get("fallback_slides", 0)
                tot = r.get("total_slides", 0)
                quality_badge = ""
                if fb > 0 and tot > 0:
                    quality_badge = f"  🟡 {fb}/{tot} bez tła"
                elif tot > 0:
                    quality_badge = f"  🟢 {tot}/{tot} z tłem"
                st.markdown(f"{base_icon} **{dt_label}** — {r['topic'][:65]}{quality_badge}")

        if errors:
            with st.expander(f"⚠️ Błędy ({len(errors)})"):
                for r in errors:
                    st.warning(f"{r['topic'][:60]} — {r.get('error', r.get('status', '?'))[:100]}")

        if st.button("🔁 Wyczyść i uruchom ponownie", key=f"clear_auto_{brand_id}"):
            _set_auto_job(brand_id, {})
            st.rerun()

    elif status == "error":
        st.error(f"❌ Błąd automatyzacji: {job.get('error', '?')}")
        if job.get("traceback"):
            with st.expander("Szczegóły techniczne"):
                st.code(job["traceback"])
        if st.button("🗑️ Wyczyść", key=f"clear_auto_err_{brand_id}"):
            _set_auto_job(brand_id, {})
            st.rerun()


# ─────────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────────

def render_automation(brand_id: str):
    page_header(
        "Automat",
        "Skonfiguruj raz — system sam generuje i publikuje karuzele każdego dnia.",
        icon="🤖",
    )

    brand = get_brand(brand_id) or {}
    brief = get_brief(brand_id) or {}
    styles = list_styles(brand_id)
    auto_cfg = get_automation_config(brand_id)

    brand_name = brand.get("name", "")
    niche = brand.get("niche", "")

    # Progress (auto-refreshing fragment)
    _render_progress(brand_id)

    current_job = _get_auto_job(brand_id)
    is_running = current_job.get("status") == "running"

    # ── Info o Publer ─────────────────────────────────────────────────────────
    if not PUBLER_API_KEY:
        st.info(
            "**Brak klucza Publer API** — karuzele będą generowane, ale bez automatycznego planowania.\n\n"
            "Aby włączyć planowanie: dodaj `PUBLER_API_KEY` do Streamlit Secrets, "
            "połącz konta IG/TikTok w publer.com (plan ~$12/mies)."
        )

    # ── Konfiguracja ─────────────────────────────────────────────────────────
    section_title("Konfiguracja harmonogramu", icon="⚙️")

    col1, col2 = st.columns(2)
    with col1:
        posts_per_day = st.slider(
            "Posty dziennie",
            min_value=1, max_value=10,
            value=int(auto_cfg.get("auto_posts_per_day") or 3),
            help="Ile karuzel generować i publikować każdego dnia.",
            disabled=is_running,
        )
    with col2:
        days_ahead = st.slider(
            "Na ile dni do przodu",
            min_value=1, max_value=14,
            value=int(auto_cfg.get("auto_days_ahead") or 7),
            help="Jaki horyzont zaplanować w Publer.",
            disabled=is_running,
        )

    total_posts = posts_per_day * days_ahead
    st.markdown(
        f"""<div style="background:linear-gradient(135deg,#F5F3FF,#EDE9FE);border:1px solid #DDD6FE;
            border-radius:12px;padding:0.9rem 1.1rem;margin:0.5rem 0 1rem;">
            <span style="font-size:1.3rem;font-weight:800;color:#6D28D9;">{total_posts}</span>
            <span style="color:#7C3AED;font-weight:600;font-size:0.9rem;margin-left:0.4rem;">
              karuzel zostanie wygenerowanych i zaplanowanych
            </span>
            <span style="color:#9CA3AF;font-size:0.82rem;margin-left:0.3rem;">
              ({posts_per_day}/dzień × {days_ahead} dni)
            </span>
        </div>""",
        unsafe_allow_html=True,
    )

    col3, col4 = st.columns(2)
    with col3:
        saved_lang = auto_cfg.get("auto_language") or "pl"
        language = st.selectbox(
            "🌐 Język postów",
            options=["pl", "en"],
            format_func=lambda x: {"pl": "🇵🇱 Polski", "en": "🇬🇧 English"}[x],
            index=0 if saved_lang == "pl" else 1,
            disabled=is_running,
        )
    with col4:
        if styles:
            style_opts = {None: "— generyczny (bez stylu) —"}
            preferred_id = None
            for s in styles:
                label = s["name"] + ("  ⭐" if s.get("is_preferred") else "")
                style_opts[s["id"]] = label
                if s.get("is_preferred"):
                    preferred_id = s["id"]
            saved_style = auto_cfg.get("auto_style_id")
            default_style = saved_style if saved_style in style_opts else preferred_id
            default_idx = list(style_opts.keys()).index(default_style) if default_style in style_opts else 0
            style_id = st.selectbox(
                "🎨 Styl wizualny",
                options=list(style_opts.keys()),
                format_func=lambda k: style_opts[k],
                index=default_idx,
                disabled=is_running,
            )
        else:
            style_id = None
            st.caption("Brak stylów — dodaj w zakładce 🎨 Style.")

    # Model
    from config import GEMINI_API_KEYS as _gemini_keys
    has_gemini = bool(_gemini_keys)

    available_models: dict[str, str] = {}
    if has_gemini:
        available_models["nano_banana_pro"] = _MODEL_LABELS["nano_banana_pro"]
        available_models["nano_banana_2"] = _MODEL_LABELS["nano_banana_2"]
    available_models["gradient"] = _MODEL_LABELS["gradient"]

    saved_model = auto_cfg.get("auto_model") or "nano_banana_pro"
    if saved_model not in available_models:
        saved_model = next(iter(available_models))

    selected_model = st.selectbox(
        "🖼️ Generator tła slajdów",
        options=list(available_models.keys()),
        format_func=lambda k: available_models[k],
        index=list(available_models.keys()).index(saved_model),
        disabled=is_running,
    )
    prefer_provider, model_override, image_quality = _MODEL_PARAMS.get(selected_model, (None, None, "low"))

    # Panel stylu tekstu — pre-wypelniony z brief.text_settings, override per-batch
    st.markdown('<div style="margin-top:0.6rem;"></div>', unsafe_allow_html=True)
    render_text_settings_panel(brand_id, brief, key_prefix="auto", default_expanded=False)

    # Sloty czasowe (info)
    st.markdown('<div style="margin-top:0.4rem;"></div>', unsafe_allow_html=True)
    slots_str = ", ".join(f"{s}–{e}" for s, e in SLOT_HOURS)
    st.caption(
        f"⏰ Posty będą losowo rozłożone w slotach UTC: **{slots_str}** "
        f"(min. 90 min przerwy między postami)"
    )

    # ── Konta Publer ─────────────────────────────────────────────────────────
    st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
    section_title("Konta do publikacji", icon="📤")

    selected_ig: list[str] = []
    selected_tt: list[str] = []

    if PUBLER_API_KEY:
        from core.publisher_publer import PublerClient, PublerError

        col_load, _ = st.columns([1, 3])
        with col_load:
            if st.button("🔄 Załaduj konta Publer", key="auto_load_acc", disabled=is_running):
                try:
                    c = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
                    if not PUBLER_WORKSPACE_ID:
                        ws = c.get_workspaces()
                        if ws:
                            c.set_workspace(str(ws[0].get("id", "")))
                    accs = c.get_accounts()
                    st.session_state["auto_publer_accounts"] = accs
                    st.success(f"Załadowano {len(accs)} kont.")
                except Exception as e:
                    st.error(f"Błąd: {e}")

        accounts: list[dict] = st.session_state.get("auto_publer_accounts", [])

        # Odczytaj zapisane ID (mogą być jako JSON string w DB)
        raw_ig = auto_cfg.get("auto_ig_account_ids") or []
        raw_tt = auto_cfg.get("auto_tt_account_ids") or []
        if isinstance(raw_ig, str):
            try:
                raw_ig = json.loads(raw_ig)
            except Exception:
                raw_ig = []
        if isinstance(raw_tt, str):
            try:
                raw_tt = json.loads(raw_tt)
            except Exception:
                raw_tt = []

        if accounts:
            ig_accs = [a for a in accounts if a.get("provider") in ("instagram", "ig")]
            tt_accs = [a for a in accounts if a.get("provider") in ("tiktok", "tt")]

            def _label(a: dict) -> str:
                return a.get("name") or a.get("username") or str(a.get("id", "?"))

            col_ig, col_tt = st.columns(2)
            with col_ig:
                if ig_accs:
                    valid_ig = [x for x in raw_ig if x in [a["id"] for a in ig_accs]]
                    selected_ig = st.multiselect(
                        "📷 Instagram",
                        options=[a["id"] for a in ig_accs],
                        default=valid_ig,
                        format_func=lambda aid: _label(next((a for a in ig_accs if a["id"] == aid), {})),
                        key="auto_sel_ig",
                        disabled=is_running,
                    )
                else:
                    st.caption("Brak kont Instagram w Publer — połącz w publer.com")

            with col_tt:
                if tt_accs:
                    valid_tt = [x for x in raw_tt if x in [a["id"] for a in tt_accs]]
                    selected_tt = st.multiselect(
                        "🎵 TikTok",
                        options=[a["id"] for a in tt_accs],
                        format_func=lambda aid: _label(next((a for a in tt_accs if a["id"] == aid), {})),
                        default=valid_tt,
                        key="auto_sel_tt",
                        disabled=is_running,
                    )
                else:
                    st.caption("Brak kont TikTok w Publer — połącz w publer.com")

            if not selected_ig and not selected_tt:
                st.warning("Wybierz przynajmniej jedno konto IG lub TikTok do publikacji.")
        else:
            st.caption("Kliknij 'Załaduj konta Publer' żeby wybrać konta docelowe.")

    # Ostatnie uruchomienie
    last_run = auto_cfg.get("auto_last_run")
    if last_run:
        try:
            lr = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            st.caption(f"🕐 Ostatnie uruchomienie: {lr.strftime('%d.%m.%Y %H:%M UTC')}")
        except Exception:
            pass

    # ── Start / Stop ──────────────────────────────────────────────────────────
    st.markdown('<div style="margin-top:1.5rem;"></div>', unsafe_allow_html=True)

    publer_ready = bool(not PUBLER_API_KEY or (selected_ig or selected_tt))
    accounts_loaded = bool(not PUBLER_API_KEY or st.session_state.get("auto_publer_accounts"))

    col_start, col_stop = st.columns([3, 1])
    with col_start:
        btn_label = f"▶  Start — wygeneruj i zaplanuj {total_posts} karuzel"
        btn_disabled = is_running or (PUBLER_API_KEY and accounts_loaded and not publer_ready)
        if st.button(btn_label, type="primary", use_container_width=True, disabled=btn_disabled):
            # Zapisz konfigurację przed startem
            update_automation_config(
                brand_id,
                auto_posts_per_day=posts_per_day,
                auto_days_ahead=days_ahead,
                auto_style_id=style_id,
                auto_ig_account_ids=selected_ig,
                auto_tt_account_ids=selected_tt,
                auto_language=language,
                auto_model=selected_model,
            )
            _start_automation(brand_id, {
                "brand_name": brand_name,
                "niche": niche,
                "posts_per_day": posts_per_day,
                "days_ahead": days_ahead,
                "style_id": style_id,
                "ig_account_ids": selected_ig,
                "tt_account_ids": selected_tt,
                "language": language,
                "model_override": model_override,
                "image_quality": image_quality,
                "prefer_provider": prefer_provider,
                "publer_api_key": PUBLER_API_KEY,
                "publer_workspace_id": PUBLER_WORKSPACE_ID,
                "slots": SLOT_HOURS,
                "text_settings": st.session_state.get("auto_text_settings"),
            })
            st.rerun()

    with col_stop:
        if is_running:
            if st.button("⏹  Stop", use_container_width=True):
                current_job["status"] = "error"
                current_job["error"] = "Zatrzymano przez użytkownika."
                current_job["finished_at"] = time.time()
                st.rerun()

    # Instrukcja
    if not is_running and not current_job.get("status"):
        st.markdown(
            """<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;
                padding:1.2rem 1.4rem;margin-top:1.2rem;line-height:1.8;font-size:0.88rem;color:#475569;">
                <strong style="color:#1E293B;">Jak to działa?</strong><br>
                1. Skonfiguruj liczbę postów i styl powyżej<br>
                2. Załaduj konta Publer i zaznacz IG / TikTok<br>
                3. Kliknij <strong>Start</strong> — system w tle:<br>
                &nbsp;&nbsp;&nbsp;• generuje tematy z Twojego briefu (AI)<br>
                &nbsp;&nbsp;&nbsp;• tworzy slajdy z tekstem i grafiką (AI + Pillow)<br>
                &nbsp;&nbsp;&nbsp;• wgrywa do Publer i planuje posty w optymalnych godzinach<br>
                4. Możesz zamknąć przeglądarkę — Publer opublikuje automatycznie<br>
                5. Za 7 dni wróć i kliknij Start znowu, żeby dołożyć kolejne 7 dni
            </div>""",
            unsafe_allow_html=True,
        )

    if is_running:
        st.info(
            "🔄 Automatyzacja działa w tle. Możesz przejść do innych zakładek. "
            "Wróć tu żeby sprawdzić postęp — strona odświeża się co 3 sekundy."
        )
