import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extractor

ENTRIES = [{"name": "Rooftop", "type": "place", "setting": "outdoor"}]
CONDITIONS = "2-hour forecast (10 pm to Midnight), by area:\n- Bedok: Light Rain"


def _prompt_for(call, conditions):
    with patch("extractor.weather.get_conditions", return_value=conditions), \
            patch("extractor._generate", return_value="ok") as gen:
        call()
    return gen.call_args.args[0]


def _query():
    return extractor.query(ENTRIES, "dinner tonight")


def _plan():
    return extractor.plan(ENTRIES, "dinner", "today", "east", "$$")


def test_query_prompt_includes_conditions_and_rules():
    prompt = _prompt_for(_query, CONDITIONS)
    assert "- Bedok: Light Rain" in prompt
    assert "missing means unknown" in prompt
    assert "Wet-weather alternative:" in prompt


def test_plan_prompt_includes_conditions_and_reason():
    prompt = _prompt_for(_plan, CONDITIONS)
    assert "- Bedok: Light Rain" in prompt
    assert "(and the weather, if it mattered)" in prompt


def test_no_conditions_leaves_prompts_without_weather():
    for call in (_query, _plan):
        prompt = _prompt_for(call, None)
        assert "Weather:" not in prompt
        assert "Current conditions" not in prompt
        assert "{" not in prompt.split("Saved places:")[0].split("Database:")[0]
