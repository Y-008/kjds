from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    values = {**dotenv_values(root / ".env"), **os.environ}
    users = json.loads(str(values["KJDS_SUPABASE_AUTH_USERS_JSON"]))
    requester = next(
        item for item in users if item.get("actor") == "r0-requester"
    )
    origin = str(
        values.get("KJDS_WEB_PUBLIC_ORIGIN") or "http://127.0.0.1:3000"
    ).rstrip("/")
    with httpx.Client(
        base_url=origin, follow_redirects=False, timeout=20
    ) as client:
        page = client.get("/login")
        response = client.post(
            "/auth/login",
            headers={"Origin": origin, "Referer": f"{origin}/login"},
            data={
                "email": requester["email"],
                "password": requester["password"],
            },
        )
        if page.status_code != 200 or response.status_code != 303:
            raise RuntimeError("BAS-156 browser authentication failed")
        cookies = []
        for cookie in client.cookies.jar:
            rest = {
                str(key).lower(): value
                for key, value in cookie._rest.items()
            }
            same_site = str(
                rest.get("samesite") or "Lax"
            ).capitalize()
            if same_site not in {"Strict", "Lax", "None"}:
                same_site = "Lax"
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain or "127.0.0.1",
                    "path": cookie.path or "/",
                    "expires": float(cookie.expires or -1),
                    "httpOnly": "httponly" in rest,
                    "secure": bool(cookie.secure),
                    "sameSite": same_site,
                }
            )
    if not cookies:
        raise RuntimeError("BAS-156 browser login returned no cookies")
    target = root / ".runtime" / "bas156-browser-auth.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"cookies": cookies, "origins": []}),
        encoding="utf-8",
    )
    print("BAS-156 temporary browser state prepared without credential output")


if __name__ == "__main__":
    main()
