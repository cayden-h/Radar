"""The surplus rule: do the devices present account for the people present.

This is the one place that rule exists. `agents/intruder` imports this same
function when it is written, rather than reimplementing it, because two copies
of the rule that decides whether someone is an intruder will drift.
"""

from __future__ import annotations

import pytest

from hawkeye_backend.household.accounting import unaccounted_count


def test_two_people_two_known_devices_is_accounted_for():
    assert unaccounted_count(people=2, known_devices_present=2) == 0


def test_one_more_person_than_devices_is_a_surplus_of_one():
    """The claim a 1x1 radio can actually support: at least one more presence
    than the roster accounts for."""
    assert unaccounted_count(people=3, known_devices_present=2) == 1


def test_more_devices_than_people_is_not_negative():
    """Phones outnumber people constantly: a tablet, a watch, a laptop.

    Surplus is a floor at zero, never a negative that would later cancel out a
    real intruder in some future sum.
    """
    assert unaccounted_count(people=2, known_devices_present=5) == 0


def test_nobody_home_is_accounted_for():
    assert unaccounted_count(people=0, known_devices_present=0) == 0


def test_a_person_with_no_devices_reported_is_a_surplus():
    """Devices absent from a frame means not reported, and the rule is
    conservative: it does not assume everyone is accounted for."""
    assert unaccounted_count(people=1, known_devices_present=0) == 1


def test_a_negative_headcount_is_a_bug_and_says_so():
    """Flooring it would report an all-clear on the strength of a counting bug."""
    with pytest.raises(ValueError):
        unaccounted_count(people=-1, known_devices_present=0)


def test_a_negative_device_count_is_a_bug_and_says_so():
    with pytest.raises(ValueError):
        unaccounted_count(people=1, known_devices_present=-1)
