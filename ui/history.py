"""
Historia wygenerowanych karuzel dla aktywnej marki.
"""
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from core.carousel_generator import (
    export_carousel_as_zip, repair_carousel_backgrounds, get_broken_slide_indices,
)
from core.bulk_reschedule import bulk_reschedule
from config import PUBLER_API_KEY, PUBLER_WORKSPACE_ID
from db import list_carousels, get_carousel, get_automation_config
from ui.theme import page_header, section_title, empty_state
from ui.generate import show_publer_section, _render_slide_regen_editor


_STATUS_COLORS = {
    "draft":     ("#EDE9FE", "#7C3AED"),
    "scheduled": ("#FFFBEB", "#D97706"),
    "posted":    ("#D1FAE5", "#059669"),
    "failed":    ("#FEF2F2", "#DC2626"),
}


# ─────────────────────────────────────────────────────────────
# BULK RESCHEDULE JOB — przesuwa wiele karuzel naraz w tle
# ─────────────────────────────────────────────────────────────

def _get_bulk_jobs() -> dict:
    return st.session_state.setdefault("bulk_reschedule_jobs", {})


def _start_bulk_reschedule_job(brand_id: str, params: dict) -> str:
    jobs = _get_bulk_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "brand_id": brand_id,
        "status": "running",
        "stage": "Inicjalizacja...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
    }

    def _runner(jobs, job_id, params):
        def cb(stage, pct):
            if job_id in jobs:
                jobs[job_id]["stage"] = stage
                jobs[job_id]["progress"] = float(pct)
        try:
            result = bulk_reschedule(
                carousel_ids=params["carousel_ids"],
                start_dt_utc=params["start_dt_utc"],
                gap_minutes_min=params["gap_min"],
                gap_minutes_max=params["gap_max"],
                jitter_minutes=params["jitter"],
                publer_api_key=params.get("publer_api_key", ""),
                publer_workspace_id=params.get("publer_workspace_id", ""),
                ig_account_ids=params.get("ig_account_ids") or [],
                tt_account_ids=params.get("tt_account_ids") or [],
                progress_callback=cb,
            )
            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "done"
            jobs[job_id]["stage"] = "Gotowe"
            jobs[job_id]["progress"] = 1.0
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["traceback"] = traceback.format_exc()
        finally:
            jobs[job_id]["finished_at"] = time.time()

    thread = threading.Thread(target=_runner, args=(jobs, job_id, params), daemon=True)
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def _render_bulk_reschedule_section(brand_id: str, all_carousels: list):
    """Sekcja na gorze widoku Historia — bulk reschedule N karuzel naraz."""
    auto_cfg = get_automation_config(brand_id) or {}

    # Default account IDs z automation config
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

    with st.expander("🔄 Bulk Reschedule — przesuwa wiele karuzel naraz", expanded=False):
        st.caption(
            "Wybierz zakres karuzel po dacie wygenerowania (created_at) i nowy harmonogram. "
            "System skasuje stare scheduled posts w Publerze (jak istnieja) i utworzy nowe "
            "z losowymi odstepami w przyszlosci."
        )

        # ── Filtr: zakres dat ──
        st.markdown("**1. Wybierz karuzele po dacie wygenerowania**")
        if not all_carousels:
            st.info("Brak karuzel w historii.")
            return

        # Domyslne wartosci: created_at najstarszej i najnowszej karuzeli
        try:
            sorted_by_created = sorted(all_carousels, key=lambda c: c.get("created_at") or "")
            oldest = datetime.fromisoformat((sorted_by_created[0].get("created_at") or "").replace("Z", "+00:00"))
            newest = datetime.fromisoformat((sorted_by_created[-1].get("created_at") or "").replace("Z", "+00:00"))
        except Exception:
            now = datetime.now(timezone.utc)
            oldest = now - timedelta(days=1)
            newest = now

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            date_from = st.date_input("Od daty", value=oldest.date(), key=f"bulk_date_from_{brand_id}")
            time_from = st.time_input("Od godziny", value=oldest.time().replace(microsecond=0), key=f"bulk_time_from_{brand_id}")
        with col_f2:
            date_to = st.date_input("Do daty", value=newest.date(), key=f"bulk_date_to_{brand_id}")
            time_to = st.time_input("Do godziny", value=newest.time().replace(microsecond=0), key=f"bulk_time_to_{brand_id}")

        from_dt = datetime.combine(date_from, time_from).replace(tzinfo=timezone.utc)
        to_dt = datetime.combine(date_to, time_to).replace(tzinfo=timezone.utc)

        # Filtruj karuzele
        matching = []
        for c in all_carousels:
            try:
                ca = datetime.fromisoformat((c.get("created_at") or "").replace("Z", "+00:00"))
                if from_dt <= ca <= to_dt:
                    matching.append(c)
            except Exception:
                continue

        # Skip karuzel ktore juz poszly (posted/published)
        matching = [c for c in matching if (c.get("status") or "").lower() not in ("posted", "published", "failed")]

        if not matching:
            st.warning("Zaden zaznaczony zakres nie zawiera reschedulowalnych karuzel "
                        "(wszystkie albo poza zakresem albo juz opublikowane).")
            return

        # Sortuj wedlug created_at rosnaco zeby zachowac kolejnosc oryginalnej generacji
        matching.sort(key=lambda c: c.get("created_at") or "")

        st.success(
            f"✓ Pasuje **{len(matching)}** karuzel "
            f"(od {matching[0].get('created_at','')[:16].replace('T',' ')} "
            f"do {matching[-1].get('created_at','')[:16].replace('T',' ')})"
        )

        # ── Nowy harmonogram ──
        st.markdown("**2. Nowy harmonogram (czas lokalny — Europa/Warszawa)**")
        st.caption(
            "ℹ️ Wprowadzony czas traktujemy jako **czas polski (CET/CEST)**. "
            "Konwertujemy na UTC przed wysylka do Publera."
        )

        # Preset: co godzinę
        fixed_hourly = st.checkbox(
            "⚡ Stały odstęp: 1 karuzelę co godzinę (dokładnie 60 min, bez jittera)",
            value=True,
            key=f"bulk_fixed_hourly_{brand_id}",
        )

        col_n1, col_n2 = st.columns(2)
        # Domyślny start: najbliższa pełna godzina w przyszłości
        _now = datetime.now()
        _next_hour = _now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        with col_n1:
            new_date = st.date_input("Start od daty", value=_next_hour.date(), key=f"bulk_new_date_{brand_id}")
            new_time = st.time_input("Start od godziny", value=_next_hour.time(), key=f"bulk_new_time_{brand_id}")
        with col_n2:
            if fixed_hourly:
                gap_min = 60
                gap_max = 60
                jitter = 0
                st.info("Odstęp: **60 min**, jitter: **0 min**")
            else:
                gap_min = st.slider("Min odstep (minuty)", 30, 240, 60, step=15, key=f"bulk_gap_min_{brand_id}")
                gap_max = st.slider("Max odstep (minuty)", 30, 360, 120, step=15, key=f"bulk_gap_max_{brand_id}")
                jitter = st.slider("Jitter ± (minuty)", 0, 30, 10, step=5, key=f"bulk_jitter_{brand_id}",
                                    help="Losowe przesuniecie ±X min od bazowego odstepu.")
                if gap_min > gap_max:
                    st.error("Min odstep musi byc <= max odstep.")
                    return

        # Konwersja czas polski (CET/CEST) -> UTC.
        # Polska: zima = UTC+1 (CET), lato = UTC+2 (CEST). Uzywamy zoneinfo dla poprawnego DST.
        try:
            from zoneinfo import ZoneInfo
            warsaw_tz = ZoneInfo("Europe/Warsaw")
            start_dt_local = datetime.combine(new_date, new_time).replace(tzinfo=warsaw_tz)
            start_dt_utc = start_dt_local.astimezone(timezone.utc)
        except Exception:
            # Fallback: zaloz CEST (UTC+2)
            start_dt_local_naive = datetime.combine(new_date, new_time)
            start_dt_utc = (start_dt_local_naive - timedelta(hours=2)).replace(tzinfo=timezone.utc)
            start_dt_local = start_dt_local_naive

        # Estymacja: ile bedzie trwac
        avg_gap = (gap_min + gap_max) / 2
        total_minutes = avg_gap * (len(matching) - 1)
        end_estimate_local = start_dt_local + timedelta(minutes=total_minutes)
        st.caption(
            f"Estymowany rozklad (czas PL): **{start_dt_local.strftime('%d.%m.%Y %H:%M')}** → "
            f"**{end_estimate_local.strftime('%d.%m.%Y %H:%M')}** "
            f"({len(matching)} karuzel × ~{int(avg_gap)} min sredni odstep)"
        )

        # ── Konta Publer ──
        st.markdown("**3. Konta do publikacji**")
        if not PUBLER_API_KEY:
            st.warning(
                "⚠️ Brak `PUBLER_API_KEY` — bulk reschedule zaktualizuje TYLKO bazę "
                "(scheduled_at), bez wgrywania do Publera. Nadal warto, ale potem musisz "
                "ręcznie kliknać 'Wyslij do Publer' na każdej karuzeli."
            )
            ig_ids = []
            tt_ids = []
        else:
            from core.publisher_publer import PublerClient
            accounts_key = f"bulk_publer_accounts_{brand_id}"

            col_load, _ = st.columns([1, 3])
            with col_load:
                if st.button("🔄 Załaduj konta Publer", key=f"bulk_load_acc_{brand_id}"):
                    try:
                        c = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
                        if not PUBLER_WORKSPACE_ID:
                            ws = c.get_workspaces()
                            if ws:
                                c.set_workspace(str(ws[0].get("id", "")))
                        accs = c.get_accounts()
                        st.session_state[accounts_key] = accs
                        st.success(f"Załadowano {len(accs)} kont.")
                    except Exception as e:
                        st.error(f"Blad: {e}")

            accounts = st.session_state.get(accounts_key, [])
            if accounts:
                ig_accs = [a for a in accounts if a.get("provider") in ("instagram", "ig")]
                tt_accs = [a for a in accounts if a.get("provider") in ("tiktok", "tt")]

                def _label(a):
                    return a.get("name") or a.get("username") or str(a.get("id", "?"))

                col_ig, col_tt = st.columns(2)
                with col_ig:
                    valid_ig = [x for x in raw_ig if x in [a["id"] for a in ig_accs]]
                    ig_ids = st.multiselect(
                        "📷 Instagram",
                        options=[a["id"] for a in ig_accs],
                        default=valid_ig,
                        format_func=lambda aid: _label(next((a for a in ig_accs if a["id"] == aid), {})),
                        key=f"bulk_sel_ig_{brand_id}",
                    )
                with col_tt:
                    valid_tt = [x for x in raw_tt if x in [a["id"] for a in tt_accs]]
                    tt_ids = st.multiselect(
                        "🎵 TikTok",
                        options=[a["id"] for a in tt_accs],
                        format_func=lambda aid: _label(next((a for a in tt_accs if a["id"] == aid), {})),
                        default=valid_tt,
                        key=f"bulk_sel_tt_{brand_id}",
                    )
            else:
                st.caption("Kliknij 'Załaduj konta Publer' żeby wybrać konta.")
                ig_ids = raw_ig
                tt_ids = raw_tt

        # ── Status running job ──
        bulk_jobs = _get_bulk_jobs()
        active_bulk = next((j for j in bulk_jobs.values()
                            if j["brand_id"] == brand_id and j["status"] == "running"), None)

        if active_bulk:
            st.info(f"🔄 Reschedule trwa... {int(active_bulk['progress']*100)}% — {active_bulk['stage']}")
            st.progress(max(0.05, min(1.0, active_bulk["progress"])))
        else:
            # ── Start button ──
            st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)
            disabled = not matching or (PUBLER_API_KEY and not (ig_ids or tt_ids))
            help_text = None
            if PUBLER_API_KEY and not (ig_ids or tt_ids):
                help_text = "Wybierz przynajmniej jedno konto Publer powyzej."
            if st.button(
                f"🚀 Reschedule {len(matching)} karuzel",
                key=f"bulk_start_{brand_id}",
                type="primary",
                disabled=disabled,
                help=help_text,
                use_container_width=True,
            ):
                params = {
                    "carousel_ids": [c["id"] for c in matching],
                    "start_dt_utc": start_dt_utc,
                    "gap_min": gap_min,
                    "gap_max": gap_max,
                    "jitter": jitter,
                    "publer_api_key": PUBLER_API_KEY or "",
                    "publer_workspace_id": PUBLER_WORKSPACE_ID or "",
                    "ig_account_ids": ig_ids or [],
                    "tt_account_ids": tt_ids or [],
                }
                bjob_id = _start_bulk_reschedule_job(brand_id, params)
                st.success(f"Job ruszyl ({bjob_id}). Postep widoczny tutaj.")
                st.rerun()

        # ── Wyniki ostatniego job-a ──
        my_done = sorted(
            [j for j in bulk_jobs.values() if j["brand_id"] == brand_id and j["status"] == "done"],
            key=lambda j: j["finished_at"] or 0, reverse=True,
        )
        if my_done:
            latest = my_done[0]
            res = latest.get("result") or {}
            st.markdown('<div style="margin-top:0.5rem;"></div>', unsafe_allow_html=True)
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("Zaplanowano", res.get("scheduled", 0))
            with col_b:
                st.metric("Tylko DB", res.get("db_only", 0))
            with col_c:
                st.metric("Pominieto", res.get("skipped", 0))
            with col_d:
                st.metric("Bledow", res.get("errors", 0))

            with st.expander("Szczegoly per karuzela"):
                for r in (res.get("results") or [])[:50]:
                    st.text(f"  {r.get('id', '?')[:12]:12s} → {r.get('status', '?')} "
                            f"{r.get('new_time', '')}  {r.get('error', '')[:60] if r.get('error') else ''}")

        my_err = [j for j in bulk_jobs.values() if j["brand_id"] == brand_id and j["status"] == "error"]
        if my_err:
            latest_err = max(my_err, key=lambda j: j["finished_at"] or 0)
            st.error(f"❌ Bulk reschedule blad: {latest_err.get('error', '?')}")


# ─────────────────────────────────────────────────────────────
# REPAIR JOBS — regeneracja brakujacych tla AI w tle
# ─────────────────────────────────────────────────────────────

def _get_repair_jobs() -> dict:
    return st.session_state.setdefault("repair_jobs", {})


def _start_repair_job(carousel_id: str) -> str:
    jobs = _get_repair_jobs()
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "carousel_id": carousel_id,
        "status": "running",
        "stage": "Inicjalizacja...",
        "progress": 0.0,
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None,
    }

    def _runner(jobs, job_id, carousel_id):
        def cb(stage, pct):
            if job_id in jobs:
                jobs[job_id]["stage"] = stage
                jobs[job_id]["progress"] = float(pct)
        try:
            result = repair_carousel_backgrounds(
                carousel_id,
                prefer_provider="gemini",
                model_override="gemini-3-pro-image-preview",
                progress_callback=cb,
            )
            jobs[job_id]["result"] = result
            jobs[job_id]["status"] = "done"
            jobs[job_id]["stage"] = "Gotowe"
            jobs[job_id]["progress"] = 1.0
        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["traceback"] = traceback.format_exc()
        finally:
            jobs[job_id]["finished_at"] = time.time()

    thread = threading.Thread(target=_runner, args=(jobs, job_id, carousel_id), daemon=True)
    add_script_run_ctx(thread)
    thread.start()
    return job_id


def render_history(brand_id: str):
    page_header(
        "Historia karuzel",
        "Wszystkie wygenerowane karuzele — pobierz ZIP lub skopiuj caption.",
        icon="📜",
    )

    carousels = list_carousels(brand_id, limit=50)

    if not carousels:
        empty_state(
            "📭",
            "Brak karuzel",
            "Wygeneruj pierwszą w zakładce Generator — pojawi się tutaj.",
        )
        return

    total = len(carousels)
    posted = sum(1 for c in carousels if c.get("status") == "posted")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:#7C3AED;">{total}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Łącznie karuzel</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.1rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);text-align:center;">
            <div style="font-size:2rem;font-weight:900;color:#10B981;">{posted}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.2rem;">Opublikowanych</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<div style="margin-top:1.25rem;"></div>', unsafe_allow_html=True)

    # ── Bulk Reschedule (przesuwa wiele naraz na nowe terminy) ──
    _render_bulk_reschedule_section(brand_id, carousels)

    section_title("Lista karuzel", icon="🗂️")

    for outer_idx, c in enumerate(carousels):
        status = c.get("status", "draft")
        bg, fg = _STATUS_COLORS.get(status, ("#F1F5F9", "#64748B"))
        slides = c.get("slides") or []
        created = (c.get("created_at") or "")[:16].replace("T", " ")

        label = (
            f"{created}  ·  {len(slides)} slajdów  ·  "
            f"{'–' if not c.get('caption') else c['caption'][:40] + '...'}"
        )

        with st.expander(label, expanded=False):
            # Status badge + meta
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;">
                <span style="background:{bg};color:{fg};padding:3px 12px;border-radius:999px;
                             font-size:0.73rem;font-weight:700;letter-spacing:0.05em;">{status.upper()}</span>
                <span style="color:#94A3B8;font-size:0.8rem;">{created}</span>
                <span style="color:#94A3B8;font-size:0.8rem;">·  {len(slides)} slajdów</span>
            </div>
            """, unsafe_allow_html=True)

            # Slide thumbnails
            if slides:
                thumb_cols = st.columns(min(len(slides), 5))
                for i, slide in enumerate(slides):
                    with thumb_cols[i % len(thumb_cols)]:
                        img_path = slide.get("image_path", "")
                        if img_path and Path(img_path).exists():
                            st.image(img_path, use_container_width=True)
                        else:
                            st.markdown(f"""
                            <div style="background:#F5F3FF;border:1px dashed #DDD6FE;border-radius:8px;
                                        aspect-ratio:4/5;display:flex;align-items:center;justify-content:center;
                                        color:#A78BFA;font-size:0.75rem;font-weight:600;">{i+1}</div>
                            """, unsafe_allow_html=True)
                        headline = (slide.get("headline") or "")[:35]
                        if headline:
                            st.markdown(f'<div style="font-size:0.7rem;color:#64748B;margin-top:0.2rem;line-height:1.3;">{headline}</div>',
                                        unsafe_allow_html=True)

                        # Editor: zmiana tekstu / regeneracja obrazu pojedynczego slajdu
                        # scope wymusza unikalnosc kluczy widgetow w razie duplikatow id
                        _render_slide_regen_editor(c, i, scope=f"hist{outer_idx}")

            st.markdown('<div style="margin-top:0.75rem;"></div>', unsafe_allow_html=True)

            # Caption
            if c.get("caption"):
                section_title("Caption")
                st.text_area(
                    "caption",
                    value=c["caption"],
                    height=100,
                    key=f"cap_hist_{c['id']}",
                    label_visibility="collapsed",
                )

            # Hashtags
            if c.get("hashtags"):
                section_title("Hashtagi")
                st.text_area(
                    "hashtagi",
                    value="  ".join(c["hashtags"]),
                    height=55,
                    key=f"ht_hist_{c['id']}",
                    label_visibility="collapsed",
                )

            # Actions - direct download_button
            col_a, col_b = st.columns([1, 4])
            with col_a:
                try:
                    zip_path = export_carousel_as_zip(c["id"])
                    with open(zip_path, "rb") as f:
                        zip_bytes = f.read()
                    st.download_button(
                        "⬇️ Pobierz ZIP",
                        data=zip_bytes,
                        file_name=f"karuzela_{c['id']}.zip",
                        mime="application/zip",
                        key=f"dl_hist_{c['id']}",
                        use_container_width=True,
                    )
                except Exception as e:
                    st.error(f"Błąd ZIP: {str(e)[:80]}")

            # ── Repair backgrounds (Gemini fallback recovery) ─────────────────
            full_carousel = get_carousel(c["id"]) or c
            # deep_scan=True: sprawdza tez pliki na dysku (low-variance = solid bg)
            # Lapie stare karuzele ktore mialy wpisany provider 'gemini' ale faktyczny
            # plik to gradient (race condition w starszej wersji kodu).
            broken_idx = get_broken_slide_indices(full_carousel, deep_scan=True)
            n_broken = len(broken_idx)
            n_total = len(full_carousel.get("slides") or [])

            # Debug: pokaz providerow dla kazdego slajdu (collapsed by default)
            with st.expander("🔍 Debug: providery slajdow", expanded=False):
                slides_dbg = full_carousel.get("slides") or []
                if not slides_dbg:
                    st.caption("Brak slajdow w bazie.")
                else:
                    for idx, sl in enumerate(slides_dbg):
                        prov = sl.get("image_provider") or "(empty)"
                        path = sl.get("image_path") or "(empty)"
                        broken_marker = "🔴" if idx in broken_idx else "🟢"
                        st.text(f"{broken_marker} Slajd {idx+1}: provider='{prov}' path='{Path(path).name if path != '(empty)' else path}'")

            if n_broken > 0:
                st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
                st.markdown(
                    f"""<div style="background:#FFF7ED;border:1px solid #FB923C;border-radius:12px;
                        padding:0.85rem 1.1rem;margin-bottom:0.5rem;">
                        <div style="font-weight:700;color:#9A3412;font-size:0.92rem;">
                            ⚠️ Brakujace tla AI: {n_broken}/{n_total} slajdow
                        </div>
                        <div style="color:#7C2D12;font-size:0.8rem;margin-top:0.3rem;line-height:1.45;">
                            Te slajdy maja zastepcze tlo (Gemini quota lub blad podczas generacji).
                            Kliknij ponizej zeby je zregenerowac — tekst zostaje 1:1, tylko obrazy beda nowe.
                            Wymaga aktywnych kluczy Gemini w Secrets.
                        </div>
                    </div>""",
                    unsafe_allow_html=True,
                )

                # Status job-a naprawy dla TEJ karuzeli
                rjobs = _get_repair_jobs()
                my_rjobs = [j for j in rjobs.values() if j["carousel_id"] == c["id"]]
                active_rjob = next((j for j in my_rjobs if j["status"] == "running"), None)

                if active_rjob:
                    st.info(f"🔧 Naprawiam... {int(active_rjob['progress']*100)}% — {active_rjob['stage']}")
                    st.progress(max(0.05, min(1.0, active_rjob["progress"])))
                else:
                    if st.button(
                        f"🔧 Wygeneruj brakujace tla AI ({n_broken} slajdow)",
                        key=f"repair_{c['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        rjob_id = _start_repair_job(c["id"])
                        st.success(f"Job naprawczy ruszyl (`{rjob_id}`). Postep widoczny tutaj.")
                        st.rerun()

                # Pokaz wynik ostatniego repair job-a
                done_jobs = [j for j in my_rjobs if j["status"] == "done"]
                if done_jobs:
                    latest = max(done_jobs, key=lambda j: j["finished_at"] or 0)
                    res = latest.get("result") or {}
                    if res.get("repaired", 0) > 0:
                        st.success(
                            f"✅ Wygenerowano AI tla dla {res['repaired']}/{res['repaired'] + res['failed']} slajdow."
                        )
                    if res.get("failed", 0) > 0:
                        st.warning(
                            f"⚠️ {res['failed']} slajdow dalej ma fallback (Gemini quota wciaz wyczerpane). "
                            f"Sprobuj ponownie pozniej."
                        )
                    with st.expander("Szczegoly naprawy"):
                        for d in (res.get("details") or []):
                            st.text(d)

                err_jobs = [j for j in my_rjobs if j["status"] == "error"]
                if err_jobs:
                    latest_err = max(err_jobs, key=lambda j: j["finished_at"] or 0)
                    st.error(f"❌ Blad naprawy: {latest_err.get('error', '?')}")

            # Publer auto-publish section — same widget as in Generator
            st.markdown('<div style="margin-top:1rem;"></div>', unsafe_allow_html=True)
            show_publer_section(full_carousel, key_suffix="hist")
