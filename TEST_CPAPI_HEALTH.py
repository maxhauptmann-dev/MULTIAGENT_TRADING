#!/usr/bin/env python3
"""
TEST_CPAPI_HEALTH.py

Ein einfacher Health-Check / Sanity-Check für das Projekt.

Zweck:
- Prüft Python-Version
- Versucht, zentrale Projekt-Module zu importieren
- Führt einen einfachen DNS/Netzwerk-Check durch

Ausgabe: JSON-Objekt auf stdout mit Ergebnis pro Check. Exit-Code 0 bei Erfolg, 1 bei Fehler.
"""
from __future__ import annotations

import sys
import importlib
import json
import socket
import time
from typing import Dict, Any


def check_python_version(min_major: int = 3, min_minor: int = 8) -> Dict[str, Any]:
    ok = (sys.version_info.major > min_major) or (
        sys.version_info.major == min_major and sys.version_info.minor >= min_minor
    )
    return {
        "name": "python_version",
        "ok": ok,
        "detected": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "required": f">={min_major}.{min_minor}",
    }


def check_imports(modules: list[str]) -> list[Dict[str, Any]]:
    results: list[Dict[str, Any]] = []
    for m in modules:
        try:
            importlib.import_module(m)
            results.append({"name": f"import:{m}", "ok": True, "error": None})
        except Exception as e:
            results.append({"name": f"import:{m}", "ok": False, "error": repr(e)})
    return results


def check_dns(host: str = "example.com", timeout_s: float = 3.0) -> Dict[str, Any]:
    start = time.time()
    try:
        socket.setdefaulttimeout(timeout_s)
        addr = socket.gethostbyname(host)
        took = time.time() - start
        return {"name": "dns_lookup", "ok": True, "host": host, "addr": addr, "rtt_s": round(took, 3)}
    except Exception as e:
        took = time.time() - start
        return {"name": "dns_lookup", "ok": False, "host": host, "error": repr(e), "rtt_s": round(took, 3)}


def run_checks() -> Dict[str, Any]:
    summary: dict[str, Any] = {"ok": True, "checks": []}

    # Python version
    py = check_python_version()
    summary["checks"].append(py)
    if not py.get("ok"):
        summary["ok"] = False

    # Key project modules to validate imports (adjust as needed)
    modules = [
        "DEF_DATA_AGENT",
        "DEF_GPT_AGENTS",
        "DEF_NEWS_CLIENT",
        "DEF_OPTIONS_AGENT",
        "DEF_SCANNER_MODE",
        "MAIN_USER_AGENT",
        "trading_agents_with_gpt",
    ]
    imports = check_imports(modules)
    summary["checks"].extend(imports)
    if any(not i["ok"] for i in imports):
        summary["ok"] = False

    # Simple DNS/network check
    dns = check_dns()
    summary["checks"].append(dns)
    if not dns.get("ok"):
        summary["ok"] = False

    return summary


def main() -> int:
    result = run_checks()
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
