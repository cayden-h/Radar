"""Does the roster account for who is in the building.

One function, deliberately. `agents/intruder` owns this decision conceptually
and will import this when it exists; having the hub reimplement it would produce
two versions of the rule that decides whether to treat someone as an intruder,
and they would drift.

Phrase the output as a surplus, never as arithmetic on an exact headcount. A 1x1
radio resolves presence, not a number of people: two people within about a metre
merge into one. What survives that limit is "at least one more presence than the
roster accounts for", which only requires noticing that an additional presence
appeared. See `agents/occupancy` for the counting limits.
"""

from __future__ import annotations


def unaccounted_count(*, people: int, known_devices_present: int) -> int:
    """How many confirmed people the known devices do not account for.

    Floors at zero. Phones routinely outnumber people, and a negative surplus
    would be a credit that silently cancelled a real intruder in a later sum.

    Raises on a negative input rather than flooring it. You cannot observe minus
    one person, so a negative is a bug in whatever counted, and flooring it would
    report "nobody unaccounted for", which is the least safe wrong answer
    available. This is the last point where the mistake is still visible.
    """
    if people < 0 or known_devices_present < 0:
        raise ValueError(
            f"counts cannot be negative: people={people}, "
            f"known_devices_present={known_devices_present}"
        )
    return max(0, people - known_devices_present)
