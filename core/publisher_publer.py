"""
Klient Publer API — wysyła karuzele do zaplanowanego publikowania na IG i TikTok.
Docs: https://publer.com/docs/api-reference/introduction
"""
import requests
from pathlib import Path
from typing import Optional

PUBLER_BASE = "https://app.publer.com/api/v1"


class PublerError(Exception):
    pass


class PublerClient:
    def __init__(self, api_key: str, workspace_id: str = ""):
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer-API {api_key}"})
        if workspace_id:
            self._session.headers["Publer-Workspace-Id"] = workspace_id

    def set_workspace(self, workspace_id: str):
        self._session.headers["Publer-Workspace-Id"] = workspace_id

    # ── Workspaces ──────────────────────────────────────────────────────────

    def get_workspaces(self) -> list[dict]:
        """Lista workspaces (nie wymaga Publer-Workspace-Id)."""
        resp = self._session.get(f"{PUBLER_BASE}/workspaces", timeout=15)
        self._raise(resp)
        return self._list(resp.json())

    # ── Accounts ─────────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        """Lista kont IG / TikTok połączonych z workspace."""
        resp = self._session.get(f"{PUBLER_BASE}/accounts", timeout=15)
        self._raise(resp)
        return self._list(resp.json())

    # ── Media ────────────────────────────────────────────────────────────────

    def upload_media(self, image_path: str) -> str:
        """Wgrywa obrazek PNG/JPG, zwraca media ID do użycia w poście."""
        p = Path(image_path)
        with open(p, "rb") as f:
            resp = self._session.post(
                f"{PUBLER_BASE}/media",
                files={"file": (p.name, f, "image/png")},
                timeout=90,
            )
        self._raise(resp)
        data = resp.json()
        if isinstance(data, dict):
            mid = (
                data.get("id")
                or (data.get("data") or {}).get("id")
                or data.get("media_id")
            )
            if mid:
                return str(mid)
        raise PublerError(f"Brak media ID w odpowiedzi Publer: {data}")

    # ── Posts ────────────────────────────────────────────────────────────────

    def schedule_carousel(
        self,
        ig_account_ids: list[str],
        tt_account_ids: list[str],
        caption: str,
        hashtags: list[str],
        media_ids: list[str],
        scheduled_at: str,
    ) -> dict:
        """
        Planuje karuzelę na Instagramie i/lub TikToku.

        Args:
            ig_account_ids: ID kont Instagram w Publer
            tt_account_ids: ID kont TikTok w Publer
            caption: tekst posta
            hashtags: lista hashtagów (doklejane do caption)
            media_ids: ID mediów zwrócone przez upload_media()
            scheduled_at: czas publikacji ISO 8601, np. "2026-04-30T10:00:00Z"

        Returns:
            Surowa odpowiedź Publer API (dict z job ID itp.)
        """
        if not ig_account_ids and not tt_account_ids:
            raise PublerError("Nie wybrano żadnego konta do publikacji.")

        full_caption = caption.strip()
        if hashtags:
            full_caption += "\n\n" + " ".join(hashtags)

        accounts = [
            {"id": aid, "scheduled_at": scheduled_at}
            for aid in (ig_account_ids + tt_account_ids)
        ]

        networks: dict = {}
        if ig_account_ids:
            # IG carousel: max 10 zdjęć
            networks["instagram"] = {
                "type": "carousel",
                "text": full_caption,
                "media": [{"id": mid, "type": "image"} for mid in media_ids[:10]],
            }
        if tt_account_ids:
            # TikTok photo carousel: max 35 zdjęć
            networks["tiktok"] = {
                "type": "photo",
                "text": full_caption,
                "media": [{"id": mid} for mid in media_ids[:35]],
                "details": {
                    "privacy": "PUBLIC_TO_EVERYONE",
                    "comment": True,
                    "promotional": False,
                    "paid": False,
                },
            }

        payload = {
            "bulk": {
                "state": "scheduled",
                "posts": [{"accounts": accounts, "networks": networks}],
            }
        }

        resp = self._session.post(
            f"{PUBLER_BASE}/posts/schedule",
            json=payload,
            timeout=30,
        )
        self._raise(resp)
        return resp.json()

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _list(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "items", "accounts", "workspaces"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def _raise(self, resp: requests.Response):
        if resp.ok:
            return
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:400]
        raise PublerError(f"Publer API {resp.status_code}: {detail}")
