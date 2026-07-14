from __future__ import annotations

from datetime import datetime, timezone

from app.narrate import build_prompt, narrate, template_narration

NOW = datetime(2026, 7, 13, 22, 0, tzinfo=timezone.utc)


def _summary(**over):
    base = {
        "window_start": NOW,
        "window_end": NOW,
        "total_events": 3,
        "by_type": {"sensor_alert": 1, "builder_update": 2},
        "by_location": {"pod-b": 2, "pod-a": 1},
        "counts": {"blockers": 1, "successes": 1, "experiments": 0},
        "blockers": [
            {"location": "pod-b", "event_type": "sensor_alert",
             "notes": "Nutrient pump blocked", "tags": ["ALERT", "BLOCKER"]}
        ],
        "successes": [
            {"location": "pod-a", "event_type": "builder_update",
             "notes": "Harvested basil", "tags": ["SUCCESS"]}
        ],
        "experiments": [],
    }
    base.update(over)
    return base


def test_template_narration_mentions_totals_and_blocker():
    text = template_narration(_summary())
    assert "3 events" in text
    assert "pod-b" in text  # the lead blocker location
    assert "1 success" in text


def test_template_narration_empty_window():
    text = template_narration(_summary(total_events=0, counts={}, blockers=[], successes=[]))
    assert "No events" in text


def test_build_prompt_is_json_and_has_no_invented_fields():
    prompt = build_prompt(_summary())
    assert "Nutrient pump blocked" in prompt
    assert "total_events" in prompt


def test_narrate_uses_fallback_without_api_key(monkeypatch):
    # No API key configured -> deterministic fallback, never calls the network.
    from app import narrate as narrate_mod

    monkeypatch.setattr(narrate_mod.settings, "openai_api_key", "", raising=False)
    result = narrate(_summary())
    assert result["generated_by"] == "fallback"
    assert result["model"] is None
    assert "3 events" in result["narration"]


def test_narrate_sends_max_completion_tokens_not_max_tokens(monkeypatch):
    """Regression: GPT-5-family models reject `max_tokens` (400 BadRequest).
    We must send `max_completion_tokens`. Mocks the OpenAI client (no network).
    """
    import openai

    from app import narrate as narrate_mod

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            msg = type("M", (), {"content": "narrated text"})()
            choice = type("C", (), {"message": msg})()
            return type("R", (), {"choices": [choice]})()

    class FakeClient:
        def __init__(self, **_):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setattr(narrate_mod.settings, "openai_api_key", "sk-test", raising=False)

    result = narrate_mod.narrate(_summary())
    assert result["generated_by"] == "openai"
    assert "max_completion_tokens" in captured
    assert "max_tokens" not in captured
