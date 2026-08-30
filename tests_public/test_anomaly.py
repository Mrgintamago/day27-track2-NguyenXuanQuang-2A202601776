from student_api import detect_metric


def test_large_volume_drop_is_anomaly():
    history = [1000, 1010, 995, 1008, 1004, 1012, 998]
    result = detect_metric(300, history, method="zscore")
    assert result["is_anomaly"] is True


def test_stable_value_is_not_anomaly():
    history = [1000, 1010, 995, 1008, 1004, 1012, 998]
    result = detect_metric(1002, history, method="zscore")
    assert result["is_anomaly"] is False


def test_auto_uses_same_weekday_baseline_not_overall_mean():
    """Weekend traffic runs ~43% of weekdays; comparing across segments alerts every Saturday."""
    weekday = [600, 610, 595, 605, 598, 602, 607, 590]
    saturday = [250, 258, 244, 262, 249, 255]
    result = detect_metric(
        255, weekday, method="auto",
        context={"metric_name": "row_count", "day_of_week": 5, "same_segment_history": saturday},
    )
    assert result["is_anomaly"] is False


def test_auto_catches_volume_drop_within_segment():
    weekday = [600, 610, 595, 605, 598, 602, 607, 590]
    result = detect_metric(
        150, weekday, method="auto",
        context={"metric_name": "row_count", "day_of_week": 1, "same_segment_history": weekday},
    )
    assert result["is_anomaly"] is True
    assert result["direction"] == "drop"


def test_auto_is_robust_to_a_contaminated_baseline():
    """One outage day inflates std enough for z-score to miss the next failure."""
    poisoned = [600, 610, 595, 605, 598, 20, 602, 607]
    assert detect_metric(400, poisoned, method="zscore")["is_anomaly"] is False
    assert detect_metric(400, poisoned, method="auto")["is_anomaly"] is True


def test_known_event_suppresses_the_alert():
    weekday = [600, 610, 595, 605, 598, 602, 607, 590]
    result = detect_metric(
        150, weekday, method="auto",
        context={"metric_name": "row_count", "known_event": "planned-migration"},
    )
    assert result["is_anomaly"] is False


def test_auto_survives_degenerate_history():
    for history in ([], [500], [500, 500]):
        assert detect_metric(500, history, method="auto")["is_anomaly"] is False
    assert detect_metric(500, [500] * 8, method="auto")["is_anomaly"] is False
