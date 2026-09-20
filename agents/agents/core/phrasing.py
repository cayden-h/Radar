"""Numbers turned into the words a human hears them in.

One module because both human boundaries are downstream of the same numbers.
`agents/master` writes the elapsed time into a classification a resident reads
on their phone; `agents/caller` speaks the same elapsed time to a dispatcher on
a live call. Two copies of this drift, and the way they drift is that one of
them keeps saying "1 minutes" long after the other stopped.

It lives in `agents/core` rather than in either agent for a reason that is
about deployment, not tidiness: the five agents are independently registered
and independently hosted, and `caller` importing a decision module out of
`master` would couple the agent that speaks to the internals of the agent that
decides. `caller` is a *client* of `master`, over a verified wire, and the only
thing the two may share in code is what neither of them owns - here, English.
"""

from __future__ import annotations


def elapsed_phrase(seconds: str | float) -> str:
    """Seconds as a phrase a dispatcher hears, pluralised correctly.

    This goes straight into a spoken sentence, so "1 minutes" is not a
    cosmetic defect: it is the system sounding like a machine reading a
    template at the moment it most needs to sound like it knows what it is
    saying.
    """
    value = float(seconds)
    if value < 60.0:
        count = round(value)
        unit = "second"
    else:
        count = round(value / 60.0)
        unit = "minute"
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
