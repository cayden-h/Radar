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
    """
    return max(0, people - known_devices_present)
