"""
carousel_factory — Streamlit entry point.

Phase 1: Foundation + manual generation
  - Multi-brand sidebar
  - AI Brief Wizard
  - Style Library
  - Carousel Generator → ZIP export
"""
from pathlib import Path

import streamlit as st

from db import init_db, list_brands, create_brand, get_brand, get_brief, list_styles, get_today_total_cost
from core.utils import generate_id
from ui.auth import require_password
from ui.theme import inject_css, page_header, badge
from ui.onboarding import render_onboarding
from ui.style_library import render_style_library


st.set_page_config(
    page_title="KaruzelAI",
    page_icon="🎠",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

if not require_password():
    st.stop()

inject_css()


def _init_session():
    if "active_brand_id" not in st.session_state:
        brands = list_brands()
        st.session_state.active_brand_id = brands[0]["id"] if brands else None


_init_session()


# ─────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    # Logo
    st.markdown("""
    <div style="padding:0.5rem 0 1.6rem;">
        <div style="display:flex;align-items:center;gap:0.55rem;">
            <div style="width:36px;height:36px;border-radius:11px;
                        background:linear-gradient(135deg,#6D28D9 0%,#8B5CF6 50%,#D946EF 100%);
                        display:flex;align-items:center;justify-content:center;
                        box-shadow:0 4px 14px -2px rgba(109,40,217,0.4),
                        inset 0 1px 0 rgba(255,255,255,0.25);font-size:1.1rem;">🎠</div>
            <div>
                <div style="font-size:1.15rem;font-weight:800;color:#0B0A18;letter-spacing:-0.025em;line-height:1;">
                    Karuzel<span class="gradient-text">AI</span>
                </div>
                <div style="font-size:0.6rem;color:#9CA3AF;text-transform:uppercase;letter-spacing:0.18em;
                            margin-top:0.2rem;font-weight:700;">Content Studio</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<hr style="border-top:1px solid #EAE8F2;margin:0 0 1.1rem;">', unsafe_allow_html=True)

    brands = list_brands()

    if brands:
        st.markdown('<div style="font-size:0.62rem;color:#9CA3AF;text-transform:uppercase;'
                    'letter-spacing:0.14em;font-weight:700;margin-bottom:0.5rem;">Aktywna marka</div>',
                    unsafe_allow_html=True)
        brand_options = {b["id"]: b["name"] for b in brands}
        selected = st.selectbox(
            "Aktywna marka",
            options=list(brand_options.keys()),
            format_func=lambda k: brand_options[k],
            index=list(brand_options.keys()).index(st.session_state.active_brand_id)
                  if st.session_state.active_brand_id in brand_options else 0,
            label_visibility="collapsed",
        )
        st.session_state.active_brand_id = selected

        active = get_brand(selected)
        niche = active.get("niche", "")
        completion = active.get("brief_completion", 0.0)
        pct = int(completion * 100)

        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#FAFAFC 0%,#F4F2FA 100%);
                    border:1px solid #EAE8F2;border-radius:12px;padding:0.85rem 1rem;
                    margin:0.7rem 0 0.4rem;">
            <div style="font-size:0.78rem;color:#1F1B3B;font-weight:600;margin-bottom:0.2rem;
                        letter-spacing:-0.005em;">
                {niche or "Brak niszy"}
            </div>
            <div style="font-size:0.68rem;color:#6B7280;font-weight:500;display:flex;
                        align-items:center;gap:0.4rem;">
                <span style="width:5px;height:5px;border-radius:50%;
                             background:{'linear-gradient(135deg,#10B981,#059669)' if pct >= 80 else 'linear-gradient(135deg,#D946EF,#8B5CF6)'};"></span>
                Brief {pct}%
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.progress(completion)
    else:
        st.markdown("""
        <div style="background:linear-gradient(135deg,#FAFAFC 0%,#F4F2FA 100%);
                    border:1px dashed #DDD6FE;border-radius:12px;padding:1rem;text-align:center;">
            <div style="font-size:1.5rem;margin-bottom:0.3rem;">✨</div>
            <div style="color:#6B7280;font-size:0.82rem;line-height:1.5;">
                Brak marek<br><span style="color:#9CA3AF;font-size:0.75rem;">Stwórz pierwszą poniżej</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('<hr style="border-top:1px solid #EAE8F2;margin:1.1rem 0;">', unsafe_allow_html=True)

    with st.expander("➕  Nowa marka"):
        with st.form("new_brand"):
            new_name = st.text_input("Nazwa marki", placeholder="np. KetoPro")
            new_niche = st.text_input("Nisza", placeholder="np. keto / odchudzanie")
            new_ig = st.text_input("Instagram handle", placeholder="@ketopro")
            new_tt = st.text_input("TikTok handle", placeholder="@ketopro_pl")

            if st.form_submit_button("Utwórz markę", use_container_width=True):
                if new_name.strip():
                    bid = generate_id("brd")
                    create_brand(
                        brand_id=bid,
                        name=new_name.strip(),
                        niche=new_niche.strip(),
                        social_handles={"ig": new_ig.strip(), "tiktok": new_tt.strip()},
                    )
                    st.session_state.active_brand_id = bid
                    st.success(f"Utworzono: {new_name}")
                    st.rerun()
                else:
                    st.error("Podaj nazwę marki.")

    # Cost ticker at the bottom
    st.markdown('<hr style="border-top:1px solid #EAE8F2;margin:1.1rem 0 0.85rem;">', unsafe_allow_html=True)

    today_cost = get_today_total_cost()
    from config import DAILY_COST_CAP_USD
    cost_pct = min(today_cost / DAILY_COST_CAP_USD, 1.0) if DAILY_COST_CAP_USD else 0.0
    cost_color = "#DC2626" if cost_pct > 0.8 else "#D97706" if cost_pct > 0.5 else "#059669"

    st.markdown(f"""
    <div style="padding:0.4rem 0 0.3rem;">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.4rem;">
            <span style="font-size:0.62rem;color:#9CA3AF;text-transform:uppercase;
                         letter-spacing:0.14em;font-weight:700;">Koszt dziś</span>
            <span style="font-size:0.66rem;color:#9CA3AF;font-weight:500;">
                limit ${DAILY_COST_CAP_USD:.2f}
            </span>
        </div>
        <div style="font-size:1.4rem;font-weight:800;color:{cost_color};letter-spacing:-0.02em;
                    line-height:1;">${today_cost:.2f}</div>
    </div>
    """, unsafe_allow_html=True)
    st.progress(cost_pct)

    # Cloud storage warning (tylko na Streamlit Cloud)
    from config import IS_STREAMLIT_CLOUD
    if IS_STREAMLIT_CLOUD:
        st.markdown("""
        <div style="background:linear-gradient(135deg,#FFFBEB 0%,#FEF3C7 100%);
                    border:1px solid #FDE68A;border-radius:10px;padding:0.7rem 0.85rem;
                    margin-top:1rem;font-size:0.72rem;line-height:1.5;color:#92400E;">
            <div style="font-weight:700;margin-bottom:0.2rem;">⚠️ Pamiec ulotna</div>
            <div style="color:#78350F;">
                Streamlit Cloud kasuje dane przy restarcie aplikacji.
                <strong>Pobieraj ZIP-y na biezaco</strong> — ponowna generacja kosztuje API.
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid #EAE8F2;">
        <div style="font-size:0.6rem;color:#9CA3AF;text-align:center;letter-spacing:0.06em;">
            Phase 1  ·  v0.3.0
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# MAIN AREA — welcome screen when no brand
# ─────────────────────────────────────────────────────────────

if not st.session_state.active_brand_id:
    st.html("""
    <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: transparent; }
    @keyframes float {
        0%, 100% { transform: translateY(0) rotate(0deg); }
        50% { transform: translateY(-10px) rotate(2deg); }
    }
    @keyframes shimmer {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .wrap {
        max-width: 880px; margin: 5vh auto 4vh;
        text-align: center; padding: 2rem 1.25rem;
    }
    .badge {
        display: inline-flex; align-items: center; gap: 0.45rem;
        padding: 0.4rem 0.95rem;
        background: white; border: 1px solid #EAE8F2; border-radius: 999px;
        box-shadow: 0 1px 2px rgba(11,10,24,0.04);
        font-size: 0.74rem; font-weight: 600; color: #6B7280;
        margin-bottom: 1.6rem; letter-spacing: -0.005em;
    }
    .badge-dot {
        width: 6px; height: 6px; border-radius: 50%;
        background: linear-gradient(135deg,#10B981,#059669);
        box-shadow: 0 0 8px rgba(16,185,129,0.6);
    }
    .hero-icon {
        font-size: 5rem; margin-bottom: 1.2rem;
        filter: drop-shadow(0 12px 28px rgba(109,40,217,0.32));
        animation: float 6s ease-in-out infinite;
    }
    h1 {
        font-size: 3rem; font-weight: 800; color: #0B0A18;
        letter-spacing: -0.04em; margin: 0 0 1.1rem; line-height: 1.05;
    }
    .hl {
        background: linear-gradient(135deg,#6D28D9 0%,#8B5CF6 35%,#D946EF 70%,#F59E0B 100%);
        background-size: 200% 200%;
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shimmer 8s ease-in-out infinite;
    }
    .lead {
        color: #6B7280; font-size: 1.1rem; margin: 0 auto 3rem;
        line-height: 1.65; max-width: 560px; font-weight: 400;
    }
    .lead strong { color: #1F1B3B; }
    .cards {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
        gap: 1rem; text-align: left; margin-bottom: 2.5rem;
    }
    .card {
        background: white; border: 1px solid #EAE8F2; border-radius: 18px;
        padding: 1.5rem; box-shadow: 0 1px 2px rgba(11,10,24,0.04), 0 4px 16px -4px rgba(11,10,24,0.04);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .card:hover { transform: translateY(-3px); box-shadow: 0 1px 2px rgba(11,10,24,0.04), 0 16px 40px -8px rgba(109,40,217,0.18); }
    .card-icon {
        width: 44px; height: 44px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.3rem; margin-bottom: 0.9rem;
    }
    .card-title { font-weight: 700; color: #0B0A18; font-size: 0.98rem; margin-bottom: 0.35rem; }
    .card-body { color: #6B7280; font-size: 0.85rem; line-height: 1.6; }
    .cta {
        display: inline-flex; align-items: center; gap: 0.7rem;
        padding: 0.85rem 1.4rem;
        background: linear-gradient(135deg,#FAFAFC 0%,#F5F3FF 100%);
        border: 1px solid #EAE8F2; border-radius: 14px;
        box-shadow: 0 1px 2px rgba(11,10,24,0.04);
        font-size: 0.92rem; font-weight: 500; color: #1F1B3B;
    }
    .cta-hl {
        background: linear-gradient(135deg,#6D28D9,#D946EF);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text; font-weight: 700;
    }
    </style>
    <div class="wrap">
        <div class="badge"><span class="badge-dot"></span>Phase 1 &middot; v0.3.0 &middot; Manual generation ready</div>
        <div class="hero-icon">🎠</div>
        <h1>Witaj w <span class="hl">KaruzelAI</span></h1>
        <p class="lead">Studio do automatycznego tworzenia <strong>wiralowych karuzel</strong> na Instagram i TikTok. AI uczy się Twojego stylu, pisze copy i generuje slajdy.</p>
        <div class="cards">
            <div class="card">
                <div class="card-icon" style="background:linear-gradient(135deg,#F5F3FF,#EDE9FE);">🧠</div>
                <div class="card-title">AI Onboarding</div>
                <div class="card-body">AI zadaje pytania po polsku i sam dopisuje research z internetu.</div>
            </div>
            <div class="card">
                <div class="card-icon" style="background:linear-gradient(135deg,#FCE7F3,#FBCFE8);">🎨</div>
                <div class="card-title">Style Library</div>
                <div class="card-body">Wgraj zdjęcia z viralowych postów — AI uczy się Twojego stylu.</div>
            </div>
            <div class="card">
                <div class="card-icon" style="background:linear-gradient(135deg,#DBEAFE,#BFDBFE);">⚡</div>
                <div class="card-title">Generator</div>
                <div class="card-body">Wpisz temat, AI w 90 sekund tworzy 8 slajdów + caption + hashtagi.</div>
            </div>
            <div class="card">
                <div class="card-icon" style="background:linear-gradient(135deg,#FEF3C7,#FDE68A);">📦</div>
                <div class="card-title">Export ZIP</div>
                <div class="card-body">Pobierasz gotowe slajdy + opis. Wrzucasz na IG/TikTok lub do Publera.</div>
            </div>
        </div>
        <div class="cta">
            <span style="font-size:1.2rem;">👈</span>
            <span>Kliknij <span class="cta-hl">+ Nowa marka</span> w panelu po lewej, żeby zacząć</span>
        </div>
    </div>
    """)
    st.stop()


# ─────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────

active_brand = get_brand(st.session_state.active_brand_id)
brand_name = active_brand.get("name", "Marka")
brand_niche = active_brand.get("niche", "")

st.markdown(f"""
<div style="margin-bottom:1.1rem;display:flex;align-items:center;gap:0.7rem;">
    <div style="width:38px;height:38px;border-radius:11px;
                background:linear-gradient(135deg,#6D28D9 0%,#8B5CF6 50%,#D946EF 100%);
                display:flex;align-items:center;justify-content:center;font-size:1rem;
                font-weight:800;color:white;letter-spacing:-0.02em;
                box-shadow:0 4px 14px -2px rgba(109,40,217,0.4),
                inset 0 1px 0 rgba(255,255,255,0.25);">
        {brand_name[:1].upper()}
    </div>
    <div>
        <div style="font-size:0.62rem;font-weight:700;color:#9CA3AF;text-transform:uppercase;
                    letter-spacing:0.14em;">Aktywna marka</div>
        <div style="display:flex;align-items:baseline;gap:0.55rem;">
            <span style="font-size:1.15rem;font-weight:800;color:#0B0A18;letter-spacing:-0.025em;">
                {brand_name}
            </span>
            {f'<span style="font-size:0.78rem;color:#6B7280;font-weight:500;">· {brand_niche}</span>' if brand_niche else ''}
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

tab_brief, tab_styles, tab_generate, tab_history = st.tabs([
    "🧠  Brief marki",
    "🎨  Style",
    "🎠  Generator",
    "📜  Historia",
])

with tab_brief:
    render_onboarding(st.session_state.active_brand_id)

with tab_styles:
    render_style_library(st.session_state.active_brand_id)

with tab_generate:
    from ui.generate import render_generate
    render_generate(st.session_state.active_brand_id)

with tab_history:
    from ui.history import render_history
    render_history(st.session_state.active_brand_id)
