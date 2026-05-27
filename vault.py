import os
import re
from datetime import date
from pathlib import Path


def _links_dir() -> Path:
    vault = os.environ["OBSIDIAN_VAULT_PATH"]
    folder = os.environ.get("OBSIDIAN_LINKS_FOLDER", "Links")
    return Path(vault) / folder


def _type_dir(entry_type: str) -> Path:
    known = {"restaurant", "event", "article", "place"}
    subfolder = entry_type.lower() if entry_type and entry_type.lower() in known else "other"
    path = _links_dir() / subfolder
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name) + ".md"


def save(entry: dict) -> tuple[str, bool]:
    dir_ = _type_dir(entry.get("type") or "")
    name = entry.get("name") or "Untitled"
    filepath = dir_ / _safe_filename(name)
    duplicate = filepath.exists()

    tags = entry.get("tags") or []
    tag_str = "[" + ", ".join(tags) + "]" if tags else "[]"

    content = f"""\
---
name: {name}
type: {entry.get("type") or ""}
address: {entry.get("address") or ""}
hours: {entry.get("hours") or ""}
date: {entry.get("date") or ""}
tags: {tag_str}
price_range: {entry.get("price_range") or ""}
visited: false
source: {entry.get("source") or ""}
saved: {date.today().isoformat()}
---

{entry.get("description") or ""}
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath), duplicate


def _parse_note(filepath: Path) -> dict:
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {"name": filepath.stem, "description": text.strip()}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": filepath.stem, "description": text.strip()}
    entry: dict = {"description": parts[2].strip()}
    for line in parts[1].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            entry[key.strip()] = val.strip()
    return entry


def load_all() -> list:
    return [_parse_note(f) for f in _links_dir().rglob("*.md")]


def list_recent(n: int = 10) -> list:
    files = sorted(_links_dir().rglob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [_parse_note(f) for f in files[:n]]


def delete(name: str) -> bool:
    for filepath in _links_dir().rglob(_safe_filename(name)):
        filepath.unlink()
        return True
    return False
