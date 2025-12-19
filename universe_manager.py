# universe_manager.py

from __future__ import annotations
from pathlib import Path
import json
from typing import List, Dict, Set, Optional


class UniverseNotFoundError(FileNotFoundError):
    """Fehler, wenn ein Universum nicht existiert."""
    pass


class UniverseManager:
    """
    Verwaltet JSON-Universen unter <projekt_root>/universes/*.json

    - sp500.json        -> Universum "sp500"
    - nasdaq100.json    -> Universum "nasdaq100"
    - dax.json          -> Universum "dax"
    - semis.json        -> Universum "semis"
    - commodities.json  -> Universum "commodities"
    """

    # optionale Aliasse, damit der User nicht exakt den Dateinamen kennen muss
    ALIASES: Dict[str, str] = {
        # SP500
        "sp500": "sp500",
        "s&p500": "sp500",
        "s&p 500": "sp500",
        "sp-500": "sp500",
        "sp 500": "sp500",

        # Nasdaq100
        "nasdaq100": "nasdaq100",
        "nasdaq 100": "nasdaq100",
        "ndx": "nasdaq100",
        "nasdaq": "nasdaq100",

        # DAX
        "dax": "dax",
        "dax40": "dax",
        "dax 40": "dax",

        # Beispiele für Themes
        "semis": "semis",
        "semiconductors": "semis",

        "commodities": "commodities",
        "rohstoffe": "commodities",
    }

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        universe_dirname: str = "universes",
    ) -> None:
        # Standard: Ordner, in dem diese Datei liegt -> Projekt-Root
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent

        self.base_dir: Path = base_dir
        self.universe_dir: Path = self.base_dir / universe_dirname

        if not self.universe_dir.exists():
            raise FileNotFoundError(
                f"Universe-Ordner nicht gefunden: {self.universe_dir}"
            )

        # Cache: name -> Liste von Symbolen
        self._cache: Dict[str, List[str]] = {}

    # ---------- interne Helfer ----------

    def _normalize_name(self, name: str) -> str:
        """Name normalisieren + Aliasse auflösen."""
        key = name.strip().lower()
        return self.ALIASES.get(key, key)

    def _file_for_universe(self, normalized_name: str) -> Path:
        return self.universe_dir / f"{normalized_name}.json"

    # ---------- öffentliche API ----------

    def list_universes(self) -> List[str]:
        """
        Listet alle verfügbaren Universen anhand der *.json-Dateien im Ordner.
        """
        names = []
        for f in self.universe_dir.glob("*.json"):
            names.append(f.stem)
        return sorted(names)

    def exists(self, name: str) -> bool:
        normalized = self._normalize_name(name)
        return self._file_for_universe(normalized).exists()

    def load_universe(self, name: str) -> List[str]:
        """
        Lädt ein einzelnes Universum als Liste von Symbolen.
        Nutzt Caching, um Mehrfach-Zugriffe zu beschleunigen.
        """
        normalized = self._normalize_name(name)

        if normalized in self._cache:
            return self._cache[normalized]

        path = self._file_for_universe(normalized)
        if not path.exists():
            raise UniverseNotFoundError(
                f"Universe '{name}' (normalisiert: '{normalized}') nicht gefunden: {path}"
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Universe-Datei '{path}' ist kein gültiges JSON: {e}")

        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            raise ValueError(
                f"Universe-Datei '{path}' muss eine JSON-Liste von Strings enthalten."
            )

        symbols = sorted(set(x.strip().upper() for x in data if x.strip()))
        self._cache[normalized] = symbols
        return symbols

    def combine_universes(self, names: List[str]) -> List[str]:
        """
        Kombiniert mehrere Universen zu einer unique Watchlist.
        Beispiel: ["sp500", "semis"]
        """
        combined: Set[str] = set()
        for n in names:
            combined.update(self.load_universe(n))
        return sorted(combined)

    def get(self, *names: str) -> List[str]:
        """
        Komfort-Funktion:
        um.get("sp500")          -> SP500
        um.get("sp500", "semis") -> kombiniertes Universum
        """
        if len(names) == 1 and isinstance(names[0], (list, tuple, set)):
            # falls versehentlich eine Liste übergeben wurde: um.get(["sp500","semis"])
            names = tuple(names[0])  # type: ignore[assignment]
        return self.combine_universes(list(names))

    # ---------- Debug / Info ----------

    def info(self) -> str:
        """
        Gibt eine kleine Übersicht als String zurück.
        """
        available = self.list_universes()
        lines = [
            f"Universe-Ordner: {self.universe_dir}",
            f"Verfügbare Universen (*.json): {', '.join(available) if available else 'keine'}",
        ]
        return "\n".join(lines)


# Modulweiter Singleton-Manager für einfachen Import
manager = UniverseManager()


# Kompatible Funktions-API, falls du lieber Funktionen nutzt
def load_universe(name: str) -> List[str]:
    return manager.load_universe(name)


def combine_universes(names: List[str]) -> List[str]:
    return manager.combine_universes(names)


if __name__ == "__main__":
    # Kleiner Self-Test beim direkten Start
    print(manager.info())
    for name in manager.list_universes():
        print(f"{name}: {manager.load_universe(name)}")
