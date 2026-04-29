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
from db import get_brand, get_brief, list_styles, update_carousel
from config import DEFAULT_SLIDES, MIN_SLIDES, MAX_SLIDES, PUBLER_API_KEY, PUBLER_WORKSPACE_ID
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
            progress_callback=cb,
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

    # ── Formularz generacji ────────────────────────────────────────────────────
    section_title("Parametry generacji", icon="⚙️")

    with st.form("generate_carousel"):
        topic = st.text_area(
            "Temat karuzeli",
            placeholder=(
                "np. '3 błędy które niszczą dietę keto'\n"
                "'Dlaczego nie chudniesz mimo diety'\n"
                "'Jak zacząć keto w 7 dni bez efektu jojo'"
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

        # Czytaj klucze na bieżąco (nie z cache modułu) żeby wykryć nowo dodane Secrets
        try:
            _GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "") or ""
            _OAI_KEY    = st.secrets.get("OPENAI_API_KEY", "") or ""
        except Exception:
            from config import GEMINI_API_KEY as _GEMINI_KEY, OPENAI_API_KEY as _OAI_KEY

        # Kolejność: top quality AI na górze (style transfer z reference images), gradient na dole jako fallback
        _img_options: dict[str, str] = {}
        if _GEMINI_KEY:
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
        })
        st.success(
            f"✅ Karuzela ruszyła w tle (job `{job_id}`). "
            f"Możesz wpisać kolejny temat i odpalić następną — będą generować się równolegle. "
            f"Postęp widoczny w panelu na górze strony."
        )
        st.rerun()


def _show_carousel_preview(carousel: dict):
    st.markdown('<hr>', unsafe_allow_html=True)

    section_title("Podgląd slajdów", icon="🖼️")

    slides = carousel.get("slides", [])
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
    _show_publer_section(carousel)


def _show_publer_section(carousel: dict):
    """Sekcja zaplanowanego wysyłania karuzeli do Publer."""
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
        accounts_key = "publer_accounts"

        # ── Załaduj konta ─────────────────────────────────────────────────
        col_load, _ = st.columns([1, 3])
        with col_load:
            if st.button("🔄 Załaduj konta Publer", key=f"load_acc_{car_id}"):
                try:
                    client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
                    if not PUBLER_WORKSPACE_ID:
                        workspaces = client.get_workspaces()
                        if workspaces:
                            client.set_workspace(str(workspaces[0].get("id", "")))
                    accounts = client.get_accounts()
                    st.session_state[accounts_key] = accounts
                    st.success(f"Załadowano {len(accounts)} kont.")
                except PublerError as e:
                    st.error(f"Błąd połączenia z Publer: {e}")

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
                    key=f"pub_ig_sel_{car_id}",
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
                    key=f"pub_tt_sel_{car_id}",
                )
                selected_tt = chosen
            else:
                st.caption("Brak kont TikTok w Publer")

        # ── Data i godzina ────────────────────────────────────────────────
        st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
        col_d, col_t = st.columns(2)
        now_local = datetime.now()
        default_dt = now_local + timedelta(hours=2)
        with col_d:
            sched_date = st.date_input(
                "Data publikacji",
                value=default_dt.date(),
                min_value=now_local.date(),
                key=f"pub_date_{car_id}",
            )
        with col_t:
            sched_time = st.time_input(
                "Godzina",
                value=default_dt.replace(second=0, microsecond=0).time(),
                step=300,
                key=f"pub_time_{car_id}",
            )

        scheduled_dt = datetime.combine(sched_date, sched_time)
        scheduled_iso = scheduled_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        st.caption(f"Zaplanowano na: **{scheduled_dt.strftime('%d.%m.%Y o %H:%M')}** (czas lokalny)")

        # ── Wyślij ────────────────────────────────────────────────────────
        st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
        if st.button(
            "🚀 Wyślij do Publer",
            key=f"send_publer_{car_id}",
            type="primary",
            disabled=not (selected_ig or selected_tt),
        ):
            _send_to_publer(carousel, selected_ig, selected_tt, scheduled_iso)


def _send_to_publer(
    carousel: dict,
    ig_ids: list[str],
    tt_ids: list[str],
    scheduled_iso: str,
):
    """Upload obrazków + stworzenie zaplanowanego posta w Publer."""
    from core.publisher_publer import PublerClient, PublerError

    slides = carousel.get("slides", [])
    image_paths = [s["image_path"] for s in slides if s.get("image_path")]

    if not image_paths:
        st.error("Brak obrazków w karuzeli.")
        return

    client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
    if not PUBLER_WORKSPACE_ID:
        try:
            workspaces = client.get_workspaces()
            if workspaces:
                client.set_workspace(str(workspaces[0].get("id", "")))
        except PublerError as e:
            st.error(f"Nie mogę pobrać workspace: {e}")
            return

    progress = st.progress(0.0, text="Przesyłam obrazki do Publer...")
    media_ids: list[str] = []

    try:
        for i, path in enumerate(image_paths):
            progress.progress(
                (i + 0.5) / len(image_paths),
                text=f"Przesyłam slajd {i + 1}/{len(image_paths)}...",
            )
            mid = client.upload_media(path)
            media_ids.append(mid)

        progress.progress(0.95, text="Tworzę zaplanowany post...")
        result = client.schedule_carousel(
            ig_account_ids=ig_ids,
            tt_account_ids=tt_ids,
            caption=carousel.get("caption", ""),
            hashtags=carousel.get("hashtags") or [],
            media_ids=media_ids,
            scheduled_at=scheduled_iso,
        )
        progress.progress(1.0, text="Gotowe!")

        publer_post_id = str(
            result.get("id")
            or (result.get("data") or {}).get("id")
            or result.get("job_id")
            or "ok"
        )
        update_carousel(carousel["id"], publer_post_id=publer_post_id, status="scheduled")
        st.success(
            f"✅ Karuzela zaplanowana w Publer! "
            f"Publer opublikuje ją automatycznie o wyznaczonej porze."
        )
        st.caption(f"Publer post ID: `{publer_post_id}`")

    except PublerError as e:
        progress.empty()
        st.error(f"Błąd Publer API: {e}")
