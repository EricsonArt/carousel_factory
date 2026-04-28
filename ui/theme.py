"""
Global theme: CSS injection + HTML helper components.
"""
import streamlit as st

COLORS = {
    "brand": "#7C3AED",
    "brand_purple": "#9333EA",
    "brand_dark": "#5B21B6",
    "brand_light": "#EDE9FE",
    "brand_bg": "#F5F3FF",
    "accent": "#F59E0B",
    "bg_card": "#FFFFFF",
    "text": "#0F172A",
    "muted": "#64748B",
    "border": "#E2E8F0",
    "success": "#10B981",
    "warning": "#F59E0B",
    "error": "#EF4444",
}

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

/* === MAIN BG === */
.stApp { background: #F5F3FF; }

.main .block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
    max-width: 1100px;
}

/* === SIDEBAR === */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0D0920 0%, #130B30 55%, #1A1040 100%) !important;
    border-right: 1px solid rgba(124, 58, 237, 0.15) !important;
}
section[data-testid="stSidebar"] > div {
    background: transparent !important;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label {
    color: #A78BFA !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: white !important;
}
section[data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div {
    background: rgba(167,139,250,0.1) !important;
    border: 1px solid rgba(167,139,250,0.3) !important;
    color: white !important;
}
section[data-testid="stSidebar"] .stSelectbox svg { fill: #A78BFA !important; }

section[data-testid="stSidebar"] .stProgress > div > div {
    background: rgba(167,139,250,0.15) !important;
    border-radius: 999px !important;
}
section[data-testid="stSidebar"] .stProgress > div > div > div > div {
    background: linear-gradient(90deg, #7C3AED, #A855F7) !important;
    border-radius: 999px !important;
}

section[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: rgba(167,139,250,0.07) !important;
    border: 1px solid rgba(167,139,250,0.2) !important;
    border-radius: 12px !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: #C4B5FD !important;
}
section[data-testid="stSidebar"] .stTextInput input {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(167,139,250,0.3) !important;
    color: white !important;
}
section[data-testid="stSidebar"] [data-testid="metric-container"] {
    background: rgba(124,58,237,0.15) !important;
    border: 1px solid rgba(124,58,237,0.3) !important;
}
section[data-testid="stSidebar"] [data-testid="metric-container"] * {
    color: white !important;
}
section[data-testid="stSidebar"] hr {
    border-top-color: rgba(124,58,237,0.2) !important;
}

/* === BUTTONS === */
.stButton > button {
    background: linear-gradient(135deg, #7C3AED 0%, #9333EA 100%);
    color: white !important;
    border: none !important;
    border-radius: 10px;
    padding: 0.55rem 1.4rem;
    font-weight: 600;
    font-size: 0.875rem;
    letter-spacing: 0.01em;
    transition: all 0.2s ease;
    box-shadow: 0 4px 14px rgba(124,58,237,0.3);
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(124,58,237,0.45);
}
.stButton > button:active { transform: translateY(0); }

.stButton > button[kind="secondary"] {
    background: white !important;
    color: #7C3AED !important;
    border: 1.5px solid #DDD6FE !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #F5F3FF !important;
    border-color: #7C3AED !important;
    box-shadow: 0 3px 10px rgba(124,58,237,0.15) !important;
    transform: translateY(-1px);
}

/* === TABS === */
.stTabs [data-baseweb="tab-list"] {
    background: white;
    border-radius: 14px;
    padding: 5px;
    border: 1px solid #E2E8F0;
    gap: 3px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.04);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    color: #64748B;
    font-weight: 500;
    padding: 0.5rem 1.3rem;
    font-size: 0.875rem;
    background: transparent;
    transition: all 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #7C3AED;
    background: #F5F3FF;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, #7C3AED 0%, #9333EA 100%) !important;
    color: white !important;
    box-shadow: 0 3px 12px rgba(124,58,237,0.3);
}
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }
.stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.5rem; }

/* === INPUTS === */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input {
    border: 1.5px solid #E2E8F0 !important;
    border-radius: 10px !important;
    background: white !important;
    color: #0F172A !important;
    font-size: 0.9rem !important;
    transition: all 0.2s ease;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #7C3AED !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.1) !important;
    outline: none !important;
}

/* === SELECTBOX === */
.stSelectbox [data-baseweb="select"] > div {
    border: 1.5px solid #E2E8F0 !important;
    border-radius: 10px !important;
    background: white !important;
}

/* === PROGRESS BAR === */
.stProgress > div > div {
    background: #EDE9FE !important;
    border-radius: 999px !important;
    height: 8px !important;
    overflow: hidden;
}
.stProgress > div > div > div {
    border-radius: 999px !important;
    height: 8px !important;
}
.stProgress > div > div > div > div {
    background: linear-gradient(90deg, #7C3AED 0%, #A855F7 100%) !important;
    border-radius: 999px !important;
}

/* === METRIC === */
[data-testid="metric-container"] {
    background: white;
    border: 1px solid #E2E8F0;
    border-radius: 14px;
    padding: 1.2rem 1.5rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
[data-testid="stMetricLabel"] > div {
    color: #64748B;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
[data-testid="stMetricValue"] > div {
    color: #0F172A;
    font-weight: 700;
    font-size: 1.5rem;
}

/* === EXPANDER === */
[data-testid="stExpander"] {
    background: white;
    border: 1px solid #E2E8F0 !important;
    border-radius: 14px !important;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
    margin-bottom: 0.5rem;
}
[data-testid="stExpander"] summary {
    padding: 0.9rem 1.25rem;
    font-weight: 500;
    color: #0F172A;
    font-size: 0.9rem;
}

/* === FORM === */
[data-testid="stForm"] {
    background: white;
    border: 1px solid #E2E8F0 !important;
    border-radius: 16px !important;
    padding: 1.5rem !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

/* === ALERTS === */
.stSuccess > div {
    background: #F0FDF4 !important;
    border: 1px solid #BBF7D0 !important;
    border-radius: 10px !important;
    color: #166534 !important;
}
.stWarning > div {
    background: #FFFBEB !important;
    border: 1px solid #FDE68A !important;
    border-radius: 10px !important;
    color: #92400E !important;
}
.stError > div {
    background: #FEF2F2 !important;
    border: 1px solid #FECACA !important;
    border-radius: 10px !important;
    color: #991B1B !important;
}
.stInfo > div {
    background: #F0F9FF !important;
    border: 1px solid #BAE6FD !important;
    border-radius: 10px !important;
    color: #0C4A6E !important;
}

/* === FILE UPLOADER === */
[data-testid="stFileUploadDropzone"] {
    background: white !important;
    border: 2px dashed #DDD6FE !important;
    border-radius: 14px !important;
    transition: all 0.2s ease;
}
[data-testid="stFileUploadDropzone"]:hover {
    border-color: #7C3AED !important;
    background: #F5F3FF !important;
}

/* === SLIDER === */
[data-testid="stSlider"] [role="slider"] {
    background: #7C3AED !important;
    border: 2px solid white !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.3) !important;
}

/* === DOWNLOAD BUTTON === */
.stDownloadButton > button {
    background: white !important;
    color: #7C3AED !important;
    border: 1.5px solid #DDD6FE !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06) !important;
}
.stDownloadButton > button:hover {
    background: #F5F3FF !important;
    border-color: #7C3AED !important;
    transform: translateY(-1px);
}

/* === DIVIDER === */
hr {
    border: none !important;
    border-top: 1px solid #E2E8F0 !important;
    margin: 1.5rem 0 !important;
}

/* === SPINNER === */
.stSpinner > div { border-top-color: #7C3AED !important; }

/* === SCROLLBAR === */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #F5F3FF; }
::-webkit-scrollbar-thumb { background: #DDD6FE; border-radius: 999px; }
::-webkit-scrollbar-thumb:hover { background: #7C3AED; }

/* === HIDE STREAMLIT CHROME === */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
[data-testid="stToolbar"] { visibility: hidden; }
[data-testid="stDecoration"] { display: none; }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    icon_html = f'<span style="font-size:1.8rem;margin-right:0.5rem;vertical-align:middle;">{icon}</span>' if icon else ""
    sub_html = (f'<p style="color:#64748B;margin:0.4rem 0 0;font-size:0.92rem;'
                f'font-weight:400;line-height:1.6;">{subtitle}</p>') if subtitle else ""
    st.markdown(f"""
    <div style="margin-bottom:1.8rem;padding-bottom:1.2rem;border-bottom:1px solid #E2E8F0;">
        <h1 style="font-size:1.65rem;font-weight:800;color:#0F172A;margin:0;letter-spacing:-0.5px;line-height:1.2;">
            {icon_html}{title}
        </h1>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)


def section_title(text: str, icon: str = "") -> None:
    icon_span = f"{icon} " if icon else ""
    st.markdown(f"""
    <div style="font-size:0.78rem;font-weight:700;color:#64748B;text-transform:uppercase;
                letter-spacing:0.1em;margin:1.8rem 0 0.8rem;">{icon_span}{text}</div>
    """, unsafe_allow_html=True)


def badge(text: str, color: str = "#7C3AED") -> str:
    return (f'<span style="background:{color}1A;color:{color};padding:3px 10px;'
            f'border-radius:999px;font-size:0.73rem;font-weight:700;display:inline-block;'
            f'letter-spacing:0.03em;">{text}</span>')


def stat_cards(items: list) -> None:
    """items: list of (label, value, icon, color) tuples"""
    cards_html = ""
    for label, value, icon, color in items:
        cards_html += f"""
        <div style="flex:1;background:white;border:1px solid #E2E8F0;border-radius:14px;
                    padding:1.25rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,0.04);min-width:120px;">
            <div style="font-size:1.4rem;margin-bottom:0.5rem;">{icon}</div>
            <div style="font-size:1.5rem;font-weight:800;color:{color};line-height:1;">{value}</div>
            <div style="font-size:0.72rem;font-weight:600;color:#64748B;text-transform:uppercase;
                        letter-spacing:0.07em;margin-top:0.3rem;">{label}</div>
        </div>
        """
    st.markdown(f"""
    <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem;">{cards_html}</div>
    """, unsafe_allow_html=True)


def empty_state(icon: str, title: str, subtitle: str = "") -> None:
    sub_html = f'<p style="color:#94A3B8;font-size:0.9rem;margin:0.5rem 0 0;">{subtitle}</p>' if subtitle else ""
    st.markdown(f"""
    <div style="text-align:center;padding:4rem 2rem;background:white;border:1px solid #E2E8F0;
                border-radius:20px;box-shadow:0 1px 4px rgba(0,0,0,0.04);">
        <div style="font-size:3rem;margin-bottom:1rem;">{icon}</div>
        <h3 style="color:#0F172A;font-size:1.1rem;font-weight:700;margin:0;">{title}</h3>
        {sub_html}
    </div>
    """, unsafe_allow_html=True)
