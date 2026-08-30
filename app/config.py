from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


@lru_cache
def load_config(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def contains_any(text: str, words: list[str]) -> bool:
    lowered = text.casefold()
    return any(word.casefold() in lowered for word in words)
