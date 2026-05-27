"""Re-saves all existing vault notes with proper YAML formatting."""
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import vault

def _old_parse(filepath: Path) -> dict:
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

files = list(vault._links_dir().rglob("*.md"))
print(f"Found {len(files)} notes")

for filepath in files:
    entry = _old_parse(filepath)
    filepath.unlink()
    path, _ = vault.save(entry)
    print(f"  Migrated: {path}")

print("Done.")
