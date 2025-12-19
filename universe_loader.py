# z.B. oben in DEF_SCANNER_MODE.py oder in universe_loader.py

import json
from pathlib import Path

# Pfad zum Projekt-Root ermitteln (hier: Datei liegt im gleichen Ordner wie MAIN_USER_AGENT.py)
BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_DIR = BASE_DIR / "universes"

def load_universe(name: str) -> list[str]:
    """
    Lädt eine JSON-Liste von Tickern aus universes/<name>.json
    z.B. name="sp500" -> universes/sp500.json
    """
    path = UNIVERSE_DIR / f"{name.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(f"Universe '{name}' nicht gefunden: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def combine_universes(names: list[str]) -> list[str]:
    """
    Kombiniert mehrere Universen zu einer unique Watchlist.
    Beispiel: ["sp500", "semis"]
    """
    symbols = set()
    for n in names:
        symbols.update(load_universe(n))
    return sorted(symbols)


