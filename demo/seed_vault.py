"""Seed a throwaway Obsidian vault with sample entries for the demo.

Usage: python demo/seed_vault.py /path/to/demo-vault
Then point OBSIDIAN_VAULT_PATH at the same path when running bot.py.
"""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

if len(sys.argv) != 2:
    sys.exit(__doc__)

os.environ["OBSIDIAN_VAULT_PATH"] = str(Path(sys.argv[1]).expanduser().resolve())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault  # noqa: E402

today = date.today()
saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)

ENTRIES = [
    {
        "name": "Sushi Kuuya", "type": "restaurant", "address": "12 Tras Street, Singapore",
        "hours": "6pm-10:30pm, closed Sun", "tags": ["japanese", "omakase", "date-spot", "tanjong pagar"],
        "price_range": "$$$", "source": "https://example.com/sushi-kuuya",
        "description": "Intimate counter-only omakase with a seasonal menu.",
    },
    {
        "name": "Ramen Hako", "type": "restaurant", "address": "88 Orchard Road, Singapore",
        "hours": "11am-10pm daily", "tags": ["japanese", "ramen", "casual", "orchard"],
        "price_range": "$", "source": "https://example.com/ramen-hako",
        "description": "Rich tonkotsu broth and a short, focused menu.",
    },
    {
        "name": "Birds of a Feather Cafe", "type": "restaurant", "address": "5 Jiak Chuan Road, Singapore",
        "hours": "9am-5pm, closed Mon", "tags": ["brunch", "cafe", "casual", "chinatown"],
        "price_range": "$$", "source": "https://example.com/birds-cafe",
        "description": "Sunny brunch spot known for its eggs benedict and cold brew.",
    },
    {
        "name": "Hawker Supper Crawl", "type": "event", "address": "Maxwell Food Centre, Singapore",
        "hours": "8pm-12am", "date": saturday.isoformat(), "tags": ["supper", "hawker", "free", "cbd"],
        "price_range": "$", "source": "https://example.com/supper-crawl",
        "description": "Guided late-night tasting walk across Maxwell and Chinatown Complex. Free to join.",
    },
    {
        "name": "Sunset Jazz at the Gardens", "type": "event", "address": "Singapore Botanic Gardens",
        "hours": "5pm-9pm", "date": (saturday + timedelta(days=1)).isoformat(), "tags": ["music", "outdoor", "free", "date-spot"],
        "price_range": "", "source": "https://example.com/gardens-jazz",
        "description": "Open-air jazz on the Symphony Lake stage. Bring a picnic mat.",
    },
    {
        "name": "Haw Par Villa", "type": "place", "address": "262 Pasir Panjang Road, Singapore",
        "hours": "9am-7pm daily", "tags": ["quirky", "sightseeing", "free", "west"],
        "price_range": "", "source": "https://example.com/haw-par-villa",
        "description": "Surreal mythology theme park with dioramas of Chinese folklore.",
    },
    {
        "name": "Why Singapore's Hawker Culture Is Special", "type": "article",
        "tags": ["food", "culture", "hawker"], "source": "https://example.com/hawker-culture",
        "description": "Long read on the history and future of Singapore's hawker centres.",
    },
]

for entry in ENTRIES:
    path, _ = vault.save(entry)
    print("wrote", path)
