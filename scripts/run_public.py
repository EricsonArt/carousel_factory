"""
Uruchamia carousel_factory na publicznym URL przez Cloudflare Tunnel.

Co robi:
  1. Sprawdza ze masz APP_PASSWORD w .env (chroni przed nieautoryzowanym dostepem)
  2. Sprawdza ANTHROPIC_API_KEY i OPENAI_API_KEY (minimum dla Phase 1)
  3. Startuje Streamlit (lokalny port 8501)
  4. Startuje cloudflared tunnel ktory daje publiczny URL trycloudflare.com
  5. Wyswietla URL ktory mozesz otworzyc na telefonie/innym kompie
  6. Ctrl+C ubija oba procesy

Uzycie:
  python scripts/run_public.py
  - lub -
  start_public.bat (Windows)
"""
import os
import re
import sys
import time
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Importujemy config zeby wymusic load .env i sprawdzic klucze
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


CLOUDFLARED = ROOT / "bin" / "cloudflared.exe"
STREAMLIT_PORT = 8501


def check_prerequisites() -> bool:
    """Sprawdza klucze API + APP_PASSWORD."""
    print("=" * 60)
    print("carousel_factory - publiczny deploy")
    print("=" * 60)
    print()

    issues = []

    if not CLOUDFLARED.exists():
        issues.append(f"Brak {CLOUDFLARED}. Uruchom:\n  curl -L --ssl-no-revoke -o "
                       f"{CLOUDFLARED} https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe")

    if not (ROOT / ".env").exists():
        issues.append(f"Brak {ROOT}\\.env - skopiuj z .env.example i uzupelnij klucze")
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            issues.append("Brak ANTHROPIC_API_KEY w .env")
        if not os.getenv("OPENAI_API_KEY"):
            issues.append("Brak OPENAI_API_KEY w .env")

        if not os.getenv("APP_PASSWORD"):
            print("⚠️  OSTRZEZENIE: brak APP_PASSWORD w .env!")
            print("   Bez hasla KAZDY z URLem moze generowac karuzele i kosztowac Cie pieniadze")
            print("   za API Claude/OpenAI. To powaznie - dodaj APP_PASSWORD do .env.")
            print()
            ans = input("Kontynuowac mimo to? [y/N]: ").strip().lower()
            if ans != "y":
                print("Anulowano. Dodaj APP_PASSWORD=jakies_dlugie_haslo do .env i sprobuj ponownie.")
                return False

    if issues:
        print("BLAD: nie mozna uruchomic publicznego URLa:")
        for i in issues:
            print(f"  - {i}")
        return False

    return True


def start_streamlit() -> subprocess.Popen:
    """Uruchamia Streamlit w tle."""
    print(f"[1/2] Startuje Streamlit na porcie {STREAMLIT_PORT}...")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", str(STREAMLIT_PORT),
            "--server.headless", "true",
            "--server.address", "127.0.0.1",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    # Poczekaj az Streamlit nasluchuje
    print("    Czekam az Streamlit wstanie...")
    for _ in range(30):
        time.sleep(1)
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{STREAMLIT_PORT}/", timeout=1)
            print(f"    OK - Streamlit dziala na http://127.0.0.1:{STREAMLIT_PORT}")
            return proc
        except Exception:
            continue
    print("    Streamlit nie odpowiada po 30s.")
    return proc


def start_cloudflared() -> tuple[subprocess.Popen, str]:
    """Uruchamia cloudflared tunnel i wyciaga publiczny URL ze stdout."""
    print(f"[2/2] Startuje Cloudflare Tunnel...")
    proc = subprocess.Popen(
        [
            str(CLOUDFLARED), "tunnel",
            "--url", f"http://127.0.0.1:{STREAMLIT_PORT}",
            "--no-autoupdate",
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    # Wyciagamy URL ze stdout
    public_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    print("    Czekam na URL z Cloudflare...")
    start = time.time()
    while time.time() - start < 60:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        # Niektorzy chca widziec dziennik - skomentowane
        # print(f"    [cf] {line.rstrip()}")
        m = url_pattern.search(line)
        if m:
            public_url = m.group()
            break

    return proc, public_url


def main():
    if not check_prerequisites():
        sys.exit(1)

    streamlit_proc = start_streamlit()
    cf_proc, public_url = start_cloudflared()

    print()
    print("=" * 60)
    if public_url:
        print(f"PUBLICZNY URL:")
        print(f"   {public_url}")
        print()
        print("Mozesz otworzyc ten link na telefonie, innym kompie, wyslac komus.")
        if os.getenv("APP_PASSWORD"):
            print(f"Aplikacja chroniona haslem - APP_PASSWORD z .env.")
        print()
        print("URL bedzie aktywny dopoki to okno jest otwarte.")
        print("Ctrl+C ubija oba procesy i URL znika.")
    else:
        print("Nie udalo sie uzyskac publicznego URL z Cloudflared.")
        print("Sprawdz logi: cloudflared moze nie miec dostepu do internetu.")
    print("=" * 60)
    print()

    def shutdown(signum=None, frame=None):
        print("\nUbijam procesy...")
        for p in (cf_proc, streamlit_proc):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Mainloop - czekamy az ktorys proces padnie albo Ctrl+C
    while True:
        if streamlit_proc.poll() is not None:
            print("Streamlit padl - zamykam.")
            break
        if cf_proc.poll() is not None:
            print("Cloudflared padl - zamykam.")
            break
        time.sleep(2)

    shutdown()


if __name__ == "__main__":
    main()
