"""
Premium Studio theme: refined light aesthetic, sophisticated accents.
Inspired by Linear, Stripe Dashboard, Vercel.
"""
import streamlit as st

COLORS = {
    "brand": "#6D28D9",
    "brand_strong": "#5B21B6",
    "brand_soft": "#EDE9FE",
    "brand_glow": "#8B5CF6",
    "magenta": "#D946EF",
    "amber": "#F59E0B",
    "ink": "#0B0A18",
    "ink_soft": "#1F1B3B",
    "muted": "#6B7280",
    "muted_soft": "#9CA3AF",
    "line": "#EAE8F2",
    "bg": "#FAFAFC",
    "bg_soft": "#F4F2FA",
    "card": "#FFFFFF",
    "success": "#059669",
    "warning": "#D97706",
    "error": "#DC2626",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Instrument+Serif:ital@0;1&display=swap');

html, body, [class*="css"], .stApp, .stApp * {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* === GLOBAL BG with subtle gradient mesh === */
.stApp {
    background:
        radial-gradient(ellipse 80% 60% at 80% 0%, rgba(139, 92, 246, 0.10) 0%, transparent 50%),
        radial-gradient(ellipse 60% 50% at 0% 100%, rgba(217, 70, 239, 0.07) 0%, transparent 50%),
        radial-gradient(ellipse 50% 40% at 100% 100%, rgba(245, 158, 11, 0.05) 0%, transparent 50%),
        #FAFAFC;
    background-attachment: fixed;
}

.main .block-container {
    padding-top: 2.2rem;
    padding-bottom: 4rem;
    max-width: 1180px;
}

/* === SIDEBAR — refined light with glass === */
section[data-testid="stSidebar"] {
    background: rgba(255, 255, 255, 0.72) !important;
    backdrop-filter: blur(24px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(24px) saturate(180%) !important;
    border-right: 1px solid rgba(109, 40, 217, 0.08) !important;
    box-shadow: 1px 0 40px -10px rgba(109, 40, 217, 0.06) !important;
}
section[data-testid="stSidebar"] > div { background: transparent !important; }

section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] div {
    color: #1F1B3B;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #0B0A18 !important;
}
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    color: #0B0A18 !important;
    border-radius: 12px !important;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div:hover {
    border-color: #8B5CF6 !important;
}
section[data-testid="stSidebar"] .stSelectbox svg { fill: #6B7280 !important; }

section[data-testid="stSidebar"] .stProgress > div > div {
    background: rgba(109, 40, 217, 0.08) !important;
    border-radius: 999px !important;
}
section[data-testid="stSidebar"] .stProgress > div > div > div > div {
    background: linear-gradient(90deg, #6D28D9 0%, #D946EF 100%) !important;
    border-radius: 999px !important;
}

section[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    border-radius: 14px !important;
    box-shadow: 0 1px 2px rgba(11, 10, 24, 0.04) !important;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] [data-testid="stExpander"]:hover {
    border-color: rgba(109, 40, 217, 0.25) !important;
    box-shadow: 0 4px 16px -4px rgba(109, 40, 217, 0.12) !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #1F1B3B !important;
    font-weight: 600 !important;
}
section[data-testid="stSidebar"] .stTextInput input {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    color: #0B0A18 !important;
    border-radius: 10px !important;
}
section[data-testid="stSidebar"] hr {
    border-top: 1px solid rgba(109, 40, 217, 0.08) !important;
}

/* === BUTTONS - PRIMARY === */
.stButton > button {
    background: linear-gradient(135deg, #6D28D9 0%, #8B5CF6 50%, #D946EF 100%) !important;
    background-size: 200% 200% !important;
    background-position: 0% 50% !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 0.65rem 1.5rem !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    letter-spacing: -0.01em !important;
    transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1) !important;
    box-shadow:
        0 1px 2px rgba(109, 40, 217, 0.15),
        0 8px 24px -4px rgba(109, 40, 217, 0.35),
        inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}
.stButton > button:hover {
    background-position: 100% 50% !important;
    transform: translateY(-1px) !important;
    box-shadow:
        0 1px 2px rgba(109, 40, 217, 0.18),
        0 14px 32px -6px rgba(109, 40, 217, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.22) !important;
}
.stButton > button:active { transform: translateY(0) !important; }

.stButton > button[kind="secondary"] {
    background: white !important;
    color: #1F1B3B !important;
    border: 1px solid #EAE8F2 !important;
    box-shadow: 0 1px 2px rgba(11, 10, 24, 0.04) !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #FAFAFC !important;
    border-color: rgba(109, 40, 217, 0.3) !important;
    color: #6D28D9 !important;
    box-shadow: 0 4px 12px -2px rgba(109, 40, 217, 0.15) !important;
}

/* === TABS === */
.stTabs [data-baseweb="tab-list"] {
    background: white !important;
    border-radius: 16px !important;
    padding: 6px !important;
    border: 1px solid #EAE8F2 !important;
    gap: 4px !important;
    box-shadow:
        0 1px 2px rgba(11, 10, 24, 0.04),
        0 8px 24px -8px rgba(11, 10, 24, 0.06) !important;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 11px !important;
    color: #6B7280 !important;
    font-weight: 500 !important;
    padding: 0.55rem 1.4rem !important;
    font-size: 0.875rem !important;
    background: transparent !important;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
    letter-spacing: -0.005em !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #6D28D9 !important;
    background: #F4F2FA !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, #6D28D9 0%, #8B5CF6 100%) !important;
    color: white !important;
    box-shadow:
        0 1px 2px rgba(109, 40, 217, 0.15),
        0 6px 16px -3px rgba(109, 40, 217, 0.4),
        inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.75rem !important; }

/* === INPUTS === */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input {
    border: 1px solid #EAE8F2 !important;
    border-radius: 12px !important;
    background: white !important;
    color: #0B0A18 !important;
    font-size: 0.92rem !important;
    padding: 0.7rem 0.95rem !important;
    transition: all 0.2s ease !important;
    box-shadow: inset 0 1px 2px rgba(11, 10, 24, 0.02) !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stNumberInput > div > div > input:focus {
    border-color: #8B5CF6 !important;
    box-shadow:
        0 0 0 3px rgba(139, 92, 246, 0.15),
        inset 0 1px 2px rgba(11, 10, 24, 0.02) !important;
    outline: none !important;
}

/* === SELECTBOX === */
.stSelectbox [data-baseweb="select"] > div {
    border: 1px solid #EAE8F2 !important;
    border-radius: 12px !important;
    background: white !important;
    transition: all 0.2s ease !important;
}
.stSelectbox [data-baseweb="select"] > div:hover {
    border-color: rgba(109, 40, 217, 0.3) !important;
}

/* === PROGRESS BAR === */
.stProgress > div > div {
    background: #EDE9FE !important;
    border-radius: 999px !important;
    height: 6px !important;
    overflow: hidden !important;
}
.stProgress > div > div > div {
    border-radius: 999px !important;
    height: 6px !important;
}
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #6D28D9 0%, #8B5CF6 50%, #D946EF 100%) !important;
    border-radius: 999px !important;
    box-shadow: 0 0 12px rgba(139, 92, 246, 0.5) !important;
}

/* === METRIC === */
[data-testid="metric-container"] {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    border-radius: 16px !important;
    padding: 1.25rem 1.5rem !important;
    box-shadow:
        0 1px 2px rgba(11, 10, 24, 0.04),
        0 4px 16px -4px rgba(11, 10, 24, 0.06) !important;
    transition: all 0.2s ease !important;
}
[data-testid="metric-container"]:hover {
    border-color: rgba(109, 40, 217, 0.2) !important;
    transform: translateY(-1px) !important;
}
[data-testid="stMetricLabel"] > div {
    color: #6B7280 !important;
    font-size: 0.7rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
[data-testid="stMetricValue"] > div {
    color: #0B0A18 !important;
    font-weight: 700 !important;
    font-size: 1.6rem !important;
    letter-spacing: -0.02em !important;
}

/* === EXPANDER === */
[data-testid="stExpander"] {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    box-shadow: 0 1px 2px rgba(11, 10, 24, 0.04) !important;
    margin-bottom: 0.6rem !important;
    transition: all 0.2s ease !important;
}
[data-testid="stExpander"]:hover {
    border-color: rgba(109, 40, 217, 0.2) !important;
    box-shadow: 0 4px 16px -4px rgba(11, 10, 24, 0.08) !important;
}
[data-testid="stExpander"] summary {
    padding: 1rem 1.35rem !important;
    font-weight: 600 !important;
    color: #0B0A18 !important;
    font-size: 0.9rem !important;
    letter-spacing: -0.005em !important;
}

/* === FORM === */
[data-testid="stForm"] {
    background: white !important;
    border: 1px solid #EAE8F2 !important;
    border-radius: 20px !important;
    padding: 1.75rem !important;
    box-shadow:
        0 1px 2px rgba(11, 10, 24, 0.04),
        0 12px 36px -12px rgba(11, 10, 24, 0.08) !important;
}

/* === ALERTS === */
.stSuccess > div {
    background: linear-gradient(135deg, #ECFDF5 0%, #F0FDF4 100%) !important;
    border: 1px solid #BBF7D0 !important;
    border-radius: 12px !important;
    color: #065F46 !important;
    font-weight: 500 !important;
}
.stWarning > div {
    background: linear-gradient(135deg, #FFFBEB 0%, #FEF3C7 100%) !important;
    border: 1px solid #FDE68A !important;
    border-radius: 12px !important;
    color: #92400E !important;
    font-weight: 500 !important;
}
.stError > div {
    background: linear-gradient(135deg, #FEF2F2 0%, #FEE2E2 100%) !important;
    border: 1px solid #FECACA !important;
    border-radius: 12px !important;
    color: #991B1B !important;
    font-weight: 500 !important;
}
.stInfo > div {
    background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%) !important;
    border: 1px solid #DDD6FE !important;
    border-radius: 12px !important;
    color: #5B21B6 !important;
    font-weight: 500 !important;
}

/* === FILE UPLOADER === */
[data-testid="stFileUploadDropzone"] {
    background: white !important;
    border: 2px dashed #DDD6FE !important;
    border-radius: 16px !important;
    transition: all 0.25s ease !important;
    padding: 2rem !important;
}
[data-testid="stFileUploadDropzone"]:hover {
    border-color: #8B5CF6 !important;
    background: linear-gradient(135deg, #FAFAFC 0%, #F5F3FF 100%) !important;
    transform: translateY(-1px) !important;
}

/* === SLIDER === */
[data-testid="stSlider"] [role="slider"] {
    background: white !important;
    border: 2px solid #6D28D9 !important;
    box-shadow:
        0 0 0 4px rgba(109, 40, 217, 0.15),
        0 4px 8px rgba(109, 40, 217, 0.25) !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSlider"] [role="slider"]:hover {
    box-shadow:
        0 0 0 6px rgba(109, 40, 217, 0.2),
        0 6px 12px rgba(109, 40, 217, 0.3) !important;
}

/* === DOWNLOAD BUTTON === */
.stDownloadButton > button {
    background: white !important;
    color: #6D28D9 !important;
    border: 1px solid #DDD6FE !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 2px rgba(11, 10, 24, 0.04) !important;
    transition: all 0.2s ease !important;
}
.stDownloadButton > button:hover {
    background: linear-gradient(135deg, #FAFAFC 0%, #F5F3FF 100%) !important;
    border-color: #8B5CF6 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 16px -2px rgba(109, 40, 217, 0.18) !important;
}

/* === CHECKBOX === */
.stCheckbox [data-baseweb="checkbox"] [data-checked="true"] {
    background: linear-gradient(135deg, #6D28D9 0%, #8B5CF6 100%) !important;
    border-color: #6D28D9 !important;
}

/* === DIVIDER === */
hr {
    border: none !important;
    border-top: 1px solid #EAE8F2 !important;
    margin: 1.75rem 0 !important;
}

/* === SPINNER === */
.stSpinner > div { border-top-color: #6D28D9 !important; }

/* === SCROLLBAR === */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: #DDD6FE;
    border-radius: 999px;
    transition: all 0.15s ease;
}
::-webkit-scrollbar-thumb:hover { background: #8B5CF6; }

/* === HIDE STREAMLIT CHROME === */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }

/* === SUBTLE FADE-IN === */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}
.main .block-container > div {
    animation: fadeInUp 0.5s cubic-bezier(0.16, 1, 0.3, 1);
}

/* === GRADIENT TEXT UTILITY === */
.gradient-text {
    background: linear-gradient(135deg, #6D28D9 0%, #8B5CF6 50%, #D946EF 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    icon_html = f'<span style="font-size:1.6rem;margin-right:0.55rem;vertical-align:middle;">{icon}</span>' if icon else ""
    sub_html = (f'<p style="color:#6B7280;margin:0.5rem 0 0;font-size:0.95rem;'
                f'font-weight:400;line-height:1.65;letter-spacing:-0.005em;">{subtitle}</p>') if subtitle else ""
    st.markdown(f"""
    <div style="margin-bottom:2rem;padding-bottom:1.4rem;border-bottom:1px solid #EAE8F2;">
        <h1 style="font-size:1.85rem;font-weight:800;color:#0B0A18;margin:0;
                   letter-spacing:-0.03em;line-height:1.15;">
            {icon_html}{title}
        </h1>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)


def section_title(text: str, icon: str = "") -> None:
    icon_span = f"{icon} " if icon else ""
    st.markdown(f"""
    <div style="font-size:0.72rem;font-weight:700;color:#6B7280;text-transform:uppercase;
                letter-spacing:0.12em;margin:2rem 0 0.85rem;">{icon_span}{text}</div>
    """, unsafe_allow_html=True)


def badge(text: str, color: str = "#6D28D9") -> str:
    return (f'<span style="background:{color}14;color:{color};padding:4px 11px;'
            f'border-radius:999px;font-size:0.72rem;font-weight:700;display:inline-block;'
            f'letter-spacing:0.02em;border:1px solid {color}20;">{text}</span>')


def stat_cards(items: list) -> None:
    """items: list of (label, value, icon, color) tuples"""
    cards_html = ""
    for label, value, icon, color in items:
        cards_html += f"""
        <div style="flex:1;background:white;border:1px solid #EAE8F2;border-radius:16px;
                    padding:1.4rem 1.6rem;box-shadow:0 1px 2px rgba(11,10,24,0.04),
                    0 4px 16px -4px rgba(11,10,24,0.04);min-width:130px;
                    transition:all 0.2s cubic-bezier(0.16,1,0.3,1);position:relative;overflow:hidden;">
            <div style="position:absolute;inset:0;background:linear-gradient(135deg,{color}08 0%,transparent 60%);
                        pointer-events:none;"></div>
            <div style="position:relative;">
                <div style="font-size:1.4rem;margin-bottom:0.6rem;">{icon}</div>
                <div style="font-size:1.65rem;font-weight:800;color:{color};line-height:1;
                            letter-spacing:-0.02em;">{value}</div>
                <div style="font-size:0.7rem;font-weight:600;color:#6B7280;text-transform:uppercase;
                            letter-spacing:0.08em;margin-top:0.4rem;">{label}</div>
            </div>
        </div>
        """
    st.markdown(f"""
    <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.25rem;">{cards_html}</div>
    """, unsafe_allow_html=True)


def empty_state(icon: str, title: str, subtitle: str = "") -> None:
    sub_html = f'<p style="color:#9CA3AF;font-size:0.92rem;margin:0.55rem 0 0;line-height:1.6;">{subtitle}</p>' if subtitle else ""
    st.markdown(f"""
    <div style="text-align:center;padding:4.5rem 2rem;background:white;border:1px solid #EAE8F2;
                border-radius:24px;box-shadow:0 1px 2px rgba(11,10,24,0.04),
                0 8px 32px -8px rgba(11,10,24,0.06);position:relative;overflow:hidden;">
        <div style="position:absolute;inset:0;background:radial-gradient(ellipse 60% 40% at 50% 0%,
                    rgba(139,92,246,0.07) 0%,transparent 60%);pointer-events:none;"></div>
        <div style="position:relative;">
            <div style="font-size:3.2rem;margin-bottom:1.1rem;
                        filter:drop-shadow(0 6px 16px rgba(109,40,217,0.18));">{icon}</div>
            <h3 style="color:#0B0A18;font-size:1.15rem;font-weight:700;margin:0;
                       letter-spacing:-0.015em;">{title}</h3>
            {sub_html}
        </div>
    </div>
    """, unsafe_allow_html=True)
