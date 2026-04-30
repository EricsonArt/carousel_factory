"""
Historia wygenerowanych karuzel dla aktywnej marki.
"""
import threading
import time
import traceback
import uuid
from pathlib import Path

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from core.carousel_generator import (
    export_carousel_as_zip, repair_carousel_backgrounds, get_broken_slide_indices,
)
from db import list_carousels, get_carousel
from ui.theme import page_header, section_title, empty_state
from ui.generate import show_publer_section


_STATUS_COLORS = {
    "draft":     ("#EDE9FE", "#7C3AED"),
    "scheduled": ("#FFFBEB", "#D97706"),
    "posted":    ("#D1FAE5", "#059669"),
    "failed":    ("#FEF2F2", "#DC2626"),
}


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
    section_title("Lista karuzel", icon="🗂️")

    for c in carousels:
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
