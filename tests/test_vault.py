import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vault


def test_setting_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    vault.save({"name": "Rooftop", "type": "place", "setting": "outdoor"})
    assert vault.load_all()[0]["setting"] == "outdoor"


def test_missing_setting_saved_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    vault.save({"name": "Cafe", "type": "restaurant"})
    assert vault.load_all()[0]["setting"] == ""
