"""
Auth gate — aktywna gdy APP_PASSWORD jest ustawione.
Pokazuje premium login screen na ciemnym tle.
"""
import hmac
import streamlit as st

from config import APP_PASSWORD

_AUTH_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, sans-serif !important;
}

section[data-testid="stSidebar"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }

.stApp {
    background: radial-gradient(ellipse at 40% 20%, #1E0B4E 0%, #0D0920 50%, #050010 100%) !important;
}
.main .block-container {
    padding-top: 0 !important;
    max-width: 100% !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

/* Override form inside auth */
[data-testid="stForm"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(124,58,237,0.25) !important;
    border-radius: 20px !important;
    padding: 2rem 1.75rem !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4) !important;
    backdrop-filter: blur(12px);
}

.stTextInput > div > div > input {
    background: rgba(255,255,255,0.07) !important;
    border: 1.5px solid rgba(124,58,237,0.35) !important;
    border-radius: 10px !important;
    color: white !important;
    font-size: 0.95rem !important;
}
.stTextInput > div > div > input::placeholder { color: rgba(167,139,250,0.6) !important; }
.stTextInput > div > div > input:focus {
    border-color: #7C3AED !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,0.2) !important;
}
.stTextInput label { color: #C4B5FD !important; font-weight: 500 !important; }

.stButton > button {
    background: linear-gradient(135deg, #7C3AED 0%, #9333EA 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-size: 0.95rem !important;
    padding: 0.65rem 1.5rem !important;
    box-shadow: 0 4px 20px rgba(124,58,237,0.5) !important;
    width: 100%;
}
.stButton > button:hover {
    box-shadow: 0 6px 28px rgba(124,58,237,0.7) !important;
    transform: translateY(-1px);
}

.stError > div {
    background: rgba(239,68,68,0.1) !important;
    border: 1px solid rgba(239,68,68,0.3) !important;
    border-radius: 10px !important;
    color: #FCA5A5 !important;
}
</style>
"""


def require_password() -> bool:
    """Zwraca True gdy autoryzowany lub brak hasla (tryb lokalny)."""
    if not APP_PASSWORD:
        return True
    if st.session_state.get("_auth_ok"):
        return True

    st.markdown(_AUTH_CSS, unsafe_allow_html=True)

    # Vertical spacing
    st.markdown('<div style="height:7vh;"></div>', unsafe_allow_html=True)

    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        # Brand logo
        st.markdown("""
        <div style="text-align:center;margin-bottom:2.5rem;">
            <div style="font-size:3.5rem;margin-bottom:0.75rem;filter:drop-shadow(0 0 20px rgba(124,58,237,0.6));">
                🎠
            </div>
            <div style="font-size:2.2rem;font-weight:900;color:white;letter-spacing:-1.5px;line-height:1;">
                Karuzel<span style="background:linear-gradient(135deg,#A855F7 0%,#F59E0B 100%);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;">AI</span>
            </div>
            <div style="font-size:0.7rem;color:#6D28D9;text-transform:uppercase;letter-spacing:0.22em;
                        font-weight:700;margin-top:0.5rem;">Content Automation Studio</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login", clear_on_submit=True):
            st.markdown('<p style="color:#C4B5FD;font-size:0.88rem;font-weight:500;margin:0 0 0.5rem;">Hasło dostępu</p>',
                        unsafe_allow_html=True)
            password = st.text_input(
                "Hasło",
                type="password",
                placeholder="Wpisz hasło...",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("Wejdź do aplikacji →", use_container_width=True)

        if submitted:
            if hmac.compare_digest(password, APP_PASSWORD):
                st.session_state["_auth_ok"] = True
                st.rerun()
            else:
                st.error("Nieprawidłowe hasło. Spróbuj ponownie.")

        st.markdown("""
        <p style="text-align:center;color:rgba(109,40,217,0.6);font-size:0.72rem;margin-top:1.5rem;">
            Chronione hasłem · Skontaktuj się z administratorem
        </p>
        """, unsafe_allow_html=True)

    return False
