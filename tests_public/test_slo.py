import pytest
from student_api import slo_status


def test_burn_rate_math():
    result = slo_status(0.995, bad_events=2, total_events=100)
    assert result["allowed_bad_rate"] == pytest.approx(0.005)
    assert result["actual_bad_rate"] == pytest.approx(0.02)
    assert result["burn_rate"] == pytest.approx(4.0)
    assert result["breached"] is True


def test_zero_events_is_safe():
    result = slo_status(0.99, bad_events=0, total_events=0)
    assert result["burn_rate"] == 0
    assert result["breached"] is False


from student_api import multiwindow_burn


def test_sustained_fast_burn_pages():
    result = multiwindow_burn(20.0, 18.0)
    assert result["page"] is True
    assert result["severity"] == "critical"


def test_transient_spike_does_not_page():
    """Short window hot, long window cold: it already recovered."""
    result = multiwindow_burn(20.0, 0.5)
    assert result["page"] is False


def test_finished_incident_is_a_ticket_not_a_page():
    result = multiwindow_burn(0.2, 10.0)
    assert result["page"] is False
    assert result["action"] == "ticket"


def test_within_budget_is_silent():
    result = multiwindow_burn(0.3, 0.2)
    assert result["page"] is False
    assert result["severity"] == "none"
