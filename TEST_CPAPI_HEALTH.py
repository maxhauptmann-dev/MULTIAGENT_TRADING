"""
Kurzer Health-Check für die IBKR Client Portal API (lokal über Gateway/TWS).

1) /sso/validate         – prüft, ob eine aktive Session besteht
2) /iserver/auth/status  – Status der Authentifizierung
3) /iserver/accounts     – listet zugängliche Accounts

Die Base-URL kann über IBKR_BASE_URL gesetzt werden (default: https://localhost:5000/v1/api).
Hinweis: Für self-signed Zertifikate wird verify=False genutzt.
"""
import os
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = os.getenv("IBKR_BASE_URL", "https://localhost:5000/v1/api").rstrip("/")
session = requests.Session()


def _get(path: str):
    url = f"{BASE_URL}{path}"
    resp = session.get(url, verify=False)
    print(f"GET {url} -> {resp.status_code}")
    if not resp.ok:
        print(resp.text)
        return None
    try:
        return resp.json()
    except Exception:
        return resp.text


def run_health_check():
    print(f"Using IBKR_BASE_URL = {BASE_URL}")
    print("1) /sso/validate")
    print(_get("/sso/validate"))

    print("\n2) /iserver/auth/status")
    print(_get("/iserver/auth/status"))

    print("\n3) /iserver/accounts")
    print(_get("/iserver/accounts"))


if __name__ == "__main__":
    run_health_check()
