"""
Reschedule wszystkich draftów → Publer, 1 karuzelę co godzinę.

Użycie:
    python scripts/reschedule_drafts.py

Opcjonalnie:
    python scripts/reschedule_drafts.py --start "2026-05-01 23:00" --gap 60
    python scripts/reschedule_drafts.py --brand brd_xxxxx --dry-run
"""
import argparse
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Dodaj root projektu do ścieżki
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config import PUBLER_API_KEY, PUBLER_WORKSPACE_ID
from db import list_brands, list_carousels, get_automation_config, update_carousel
from core.publisher_publer import PublerClient, PublerError
from core.bulk_reschedule import bulk_reschedule


def _next_full_hour_pl() -> datetime:
    """Zwraca najbliższą pełną godzinę czasu polskiego jako aware datetime."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Warsaw")
    except ImportError:
        tz = timezone(timedelta(hours=2))  # CEST fallback
    now = datetime.now(tz)
    next_h = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_h


def main():
    parser = argparse.ArgumentParser(description="Reschedule draftów co godzinę do Publer")
    parser.add_argument("--brand", default=None, help="ID marki (domyślnie: pierwsza aktywna)")
    parser.add_argument("--start", default=None,
                        help="Start czas PL, np. '2026-05-02 08:00' (domyślnie: najbliższa pełna godzina)")
    parser.add_argument("--gap", type=int, default=60, help="Odstęp w minutach (domyślnie: 60)")
    parser.add_argument("--status", default="draft",
                        help="Filtr statusu: draft | scheduled | all (domyślnie: draft)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Tylko pokaż plan, nie wysyłaj do Publer")
    args = parser.parse_args()

    # ── 1. Marka ──────────────────────────────────────────────
    brands = list_brands()
    if not brands:
        print("❌ Brak marek w bazie danych.")
        sys.exit(1)

    if args.brand:
        brand = next((b for b in brands if b["id"] == args.brand), None)
        if not brand:
            print(f"❌ Nie znaleziono marki: {args.brand}")
            sys.exit(1)
    else:
        brand = brands[0]

    print(f"✅ Marka: {brand['name']} ({brand['id']})")

    # ── 2. Karuzele do reschedulowania ────────────────────────
    all_carousels = list_carousels(brand["id"], limit=500)

    if args.status == "all":
        target_statuses = {"draft", "scheduled"}
    elif args.status == "scheduled":
        target_statuses = {"scheduled"}
    else:
        target_statuses = {"draft"}

    to_reschedule = [
        c for c in all_carousels
        if (c.get("status") or "draft").lower() in target_statuses
        and (c.get("status") or "").lower() not in ("posted", "published", "failed")
    ]
    to_reschedule.sort(key=lambda c: c.get("created_at") or "")

    if not to_reschedule:
        print(f"⚠️  Brak karuzel ze statusem '{args.status}' dla marki {brand['name']}.")
        print(f"    Dostępne statusy: {set(c.get('status','draft') for c in all_carousels)}")
        sys.exit(0)

    print(f"📋 Karuzele do zaplanowania: {len(to_reschedule)}")

    # ── 3. Czas startu ────────────────────────────────────────
    try:
        from zoneinfo import ZoneInfo
        warsaw_tz = ZoneInfo("Europe/Warsaw")
    except ImportError:
        warsaw_tz = timezone(timedelta(hours=2))

    if args.start:
        try:
            start_local = datetime.strptime(args.start, "%Y-%m-%d %H:%M").replace(tzinfo=warsaw_tz)
        except ValueError:
            print(f"❌ Zły format daty: '{args.start}'. Użyj 'YYYY-MM-DD HH:MM'")
            sys.exit(1)
    else:
        start_local = _next_full_hour_pl()

    start_utc = start_local.astimezone(timezone.utc)

    end_estimate = start_local + timedelta(minutes=args.gap * (len(to_reschedule) - 1))
    print(f"⏰ Start (PL): {start_local.strftime('%d.%m.%Y %H:%M')}")
    print(f"⏰ Koniec (PL): {end_estimate.strftime('%d.%m.%Y %H:%M')}")
    print(f"📏 Odstęp: co {args.gap} minut")
    print()

    # ── 4. Konta Publer ───────────────────────────────────────
    auto_cfg = get_automation_config(brand["id"]) or {}
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

    if not PUBLER_API_KEY:
        print("⚠️  Brak PUBLER_API_KEY — zaktualizuję tylko bazę danych (scheduled_at).")
        print("    Dodaj PUBLER_API_KEY do .env żeby wysłać do Publer.")
        ig_ids, tt_ids = [], []
    else:
        if not (raw_ig or raw_tt):
            print("🔍 Pobieranie kont Publer...")
            try:
                client = PublerClient(PUBLER_API_KEY, PUBLER_WORKSPACE_ID)
                if not PUBLER_WORKSPACE_ID:
                    ws = client.get_workspaces()
                    if ws:
                        client.set_workspace(str(ws[0].get("id", "")))
                accounts = client.get_accounts()
                ig_accounts = [a for a in accounts if a.get("provider") in ("instagram", "ig")]
                tt_accounts = [a for a in accounts if a.get("provider") in ("tiktok", "tt")]
                print(f"   Znaleziono: {len(ig_accounts)} Instagram, {len(tt_accounts)} TikTok")
                for a in ig_accounts:
                    print(f"   📷 IG: {a.get('name') or a.get('username')} ({a.get('id')})")
                for a in tt_accounts:
                    print(f"   🎵 TT: {a.get('name') or a.get('username')} ({a.get('id')})")
                ig_ids = [a["id"] for a in ig_accounts]
                tt_ids = [a["id"] for a in tt_accounts]
            except Exception as e:
                print(f"❌ Błąd pobierania kont Publer: {e}")
                ig_ids, tt_ids = [], []
        else:
            ig_ids = raw_ig
            tt_ids = raw_tt
            print(f"✅ Konta z automation config: {len(ig_ids)} IG, {len(tt_ids)} TT")

    # ── 5. Dry run ────────────────────────────────────────────
    if args.dry_run:
        print("\n🔍 DRY RUN — plan (bez wysyłania do Publer):")
        t = start_local
        for i, c in enumerate(to_reschedule):
            slides = c.get("slides") or []
            topic = (c.get("topic") or c.get("caption") or "?")[:60]
            print(f"  {i+1:3d}. {t.strftime('%d.%m %H:%M')} PL | {len(slides)} slajdów | {topic}")
            t += timedelta(minutes=args.gap)
        print(f"\nŁącznie: {len(to_reschedule)} karuzel, ostatnia o {t.strftime('%d.%m.%Y %H:%M')} PL")
        return

    # ── 6. Właściwy reschedule ────────────────────────────────
    print("🚀 Startujemy reschedule...\n")

    def progress(stage, pct):
        bar = "█" * int(pct * 20) + "░" * (20 - int(pct * 20))
        print(f"\r  [{bar}] {int(pct*100):3d}% {stage}", end="", flush=True)

    result = bulk_reschedule(
        carousel_ids=[c["id"] for c in to_reschedule],
        start_dt_utc=start_utc,
        gap_minutes_min=args.gap,
        gap_minutes_max=args.gap,
        jitter_minutes=0,
        publer_api_key=PUBLER_API_KEY or "",
        publer_workspace_id=PUBLER_WORKSPACE_ID or "",
        ig_account_ids=ig_ids,
        tt_account_ids=tt_ids,
        progress_callback=progress,
    )

    print("\n")
    print("─" * 50)
    print(f"✅ Zaplanowano w Publer : {result.get('scheduled', 0)}")
    print(f"📝 Tylko w DB (brak Publer): {result.get('db_only', 0)}")
    print(f"⏭  Pominięto          : {result.get('skipped', 0)}")
    print(f"❌ Błędów             : {result.get('errors', 0)}")
    print("─" * 50)

    errors = [r for r in (result.get("results") or []) if r.get("status") == "publer_error"]
    if errors:
        print("\n⚠️  Błędy Publer:")
        for e in errors:
            print(f"   {e.get('id','?')[:12]} → {e.get('error','?')[:100]}")


if __name__ == "__main__":
    main()
