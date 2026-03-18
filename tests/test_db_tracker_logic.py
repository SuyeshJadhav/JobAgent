from backend.services.db_tracker import _can_transition


def test_can_transition_forward_statuses():
    assert _can_transition("found", "shortlisted") is True
    assert _can_transition("shortlisted", "applied") is True


def test_can_transition_backward_is_blocked():
    assert _can_transition("applied", "found") is False


def test_can_transition_to_side_branches_is_allowed():
    assert _can_transition("found", "failed") is True
    assert _can_transition("applied", "skipped") is True
