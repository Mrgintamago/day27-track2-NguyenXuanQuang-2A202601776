from student_api import detect_distribution


def test_extreme_mean_shift_detected():
    baseline = [9, 10, 11, 10, 10]
    current = [190, 200, 210, 205]
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_shape_change_with_identical_mean_is_detected():
    """The case mean-ratio is blind to: same mean, split into two modes."""
    baseline = [70] * 40
    current = [40] * 20 + [100] * 20
    assert sum(current) / len(current) == sum(baseline) / len(baseline)
    assert detect_distribution(current, baseline)["is_anomaly"] is True


def test_same_distribution_is_not_flagged():
    baseline = [68, 70, 72, 69, 71, 70, 73, 67, 70, 71] * 4
    current = [69, 71, 70, 72, 68, 70, 71, 69] * 4
    assert detect_distribution(current, baseline)["is_anomaly"] is False


def test_empty_input_does_not_crash():
    assert detect_distribution([], [1, 2, 3])["is_anomaly"] is False
    assert detect_distribution([1, 2, 3], [])["is_anomaly"] is False
