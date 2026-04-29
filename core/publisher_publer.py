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
        Returns dict z polami:
          - request_payload: co poszło do API
          - status_code: HTTP status
          - response: surowy JSON z Publer
          - job_id / post_id (jeśli Publer zwraca)
        """
        if not ig_account_ids and not tt_account_ids:
            raise PublerError("Nie wybrano żadnego konta do publikacji.")

        full_caption = caption.strip()
        if hashtags:
            full_caption += "\n\n" + " ".join(hashtags)

        # TikTok wymaga title (max 90 znaków) — wyciągnij z 1. linii caption
        tt_title = full_caption.split("\n", 1)[0][:88].strip() or "New post"

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
            # TikTok photo carousel: max 35 zdjęć. TITLE WYMAGANY.
            networks["tiktok"] = {
                "type": "photo",
                "title": tt_title,
                "text": full_caption,
                "media": [{"id": mid} for mid in media_ids[:35]],
                "details": {
                    "privacy": "PUBLIC_TO_EVERYONE",
                    "comment": True,
                    "promotional": False,
                    "paid": False,
                    "reminder": False,
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

        try:
            response_json = resp.json()
        except Exception:
            response_json = {"_raw_text": resp.text[:1000]}

        if not resp.ok:
            raise PublerError(
                f"Publer API {resp.status_code}: {response_json}\n"
                f"Wysłany payload: {payload}"
            )

        return {
            "request_payload": payload,
            "status_code": resp.status_code,
            "response": response_json,
            "job_id": (
                response_json.get("job_id")
                or (response_json.get("data") or {}).get("job_id")
            ),
            "post_id": (
                response_json.get("id")
                or (response_json.get("data") or {}).get("id")
            ),
        }

    def get_job_status(self, job_id: str) -> dict:
        """Sprawdza status async job-a (po schedule)."""
        resp = self._session.get(
            f"{PUBLER_BASE}/job_status/{job_id}",
            timeout=15,
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
