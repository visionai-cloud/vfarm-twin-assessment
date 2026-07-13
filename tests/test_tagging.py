from __future__ import annotations

from app.tagging import derive_tags


def test_blocker_from_notes():
    assert "BLOCKER" in derive_tags("builder_update", "Nutrient pump blocked, waiting on part")


def test_success_from_notes():
    assert "SUCCESS" in derive_tags("builder_update", "Harvested basil, batch completed")


def test_experiment_from_type_even_without_keyword():
    assert derive_tags("experiment", "light cycle") == ["EXPERIMENT"]


def test_sensor_alert_type_promotes_alert():
    assert "ALERT" in derive_tags("sensor_alert", "temperature spike")


def test_multiple_tags_sorted_and_unique():
    tags = derive_tags("experiment", "trial failed, blocked on hardware")
    assert tags == sorted(tags)
    assert len(tags) == len(set(tags))
    assert "BLOCKER" in tags and "EXPERIMENT" in tags


def test_no_tags_when_nothing_matches():
    assert derive_tags("environment", "humidity nominal") == []
