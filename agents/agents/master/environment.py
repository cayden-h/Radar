"""Air quality: the simulated carbon monoxide sensor master reads directly.

Carbon monoxide, not oxygen, and **not from CSI**. This is the second modality,
and that is the whole point of it. `people` says someone went down; this says
why. **Two independent sensing modalities agreeing is real corroboration; two
views of one CSI stream agreeing is not.**

Why CO and not oxygen: **CSI cannot sense gas composition at all.** Oxygen
absorption is a ~60 GHz phenomenon, which is why 802.11ad lives there; the
BCM43455c0 is a 2.4/5 GHz radio. The one judge in the room most equipped to
catch that claim is the one grading us.

CO is the better signal on the merits anyway. It is what incapacitates people in
structure fires before flame reaches them - smoke inhalation alone is 35% of
residential fire deaths against 6% for burns alone - and it is the likeliest
reason someone faints in a house that is not visibly burning.

## Why this is master's input and not its own agent

It was its own agent until 2026-09-19. Collapsing it into `master` is a real
tradeoff and it is worth stating rather than glossing:

**What we gave up.** A separately registered agent would present a claim that
`master` verifies like any other. Read locally, this reading skips the gate
entirely, because there is no counterparty to authenticate - master is both the
producer and the consumer.

**Why that is acceptable here, and where it would not be.** A locally-attached
sensor on the same host is inside the trust boundary by construction; putting an
ANS hop between a process and the GPIO pin it is reading would be theatre. What
matters is that the reading is *labelled* as unverified-by-construction rather
than quietly inheriting master's own FIDUCIARY standing, and `MasterAgent` does
exactly that. If the gas sensor ever moves onto separate hardware, it gets its
own identity and goes back through the gate; that is a deployment change, not a
redesign.

**No gas sensor is being purchased.** Root CLAUDE.md's honesty rule applies in
full, and this file is where two of its three clauses live:

1. The interface, and master's handling of what comes through it, are real.
2. The simulated input is labelled **in the data**: every reading carries
   `demo-trigger`, which `Provenance` computes to `simulated`, so it cannot be
   presented as measured by accident.

The third clause - say it out loud on stage before anyone asks - is a human's
job, and master's card carries the same statement for the machines.

Swapping in a real MQ-7 on the Pi's GPIO through an MCP3008 ADC is writing one
more class in this file with `source = "mq7-gpio"`. Nothing above the interface
changes. That is the entire extensibility claim, and it is checkable by reading
the code, which is more than most demos can offer.

**The ramp is not decoration.** CO jumping 0 to 800 ppm in one sample is
obviously synthetic to anyone who has seen a real detector, and a judge who
catches a fabricated-looking measurement stops believing the measured ones too.
So it ramps through the UL 2034 bands on a realistic timescale.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agents.core.ports import GasReading

#: UL 2034 required alarm times. This is what a real device in this role
#: implements, and the bands are what makes a simulated ppm figure plausible.
#:
#: | CO level      | Required alarm time      |
#: |---------------|--------------------------|
#: | below 30 ppm  | no alarm before 30 days  |
#: | 70 ppm        | 60-240 minutes           |
#: | 150 ppm       | 10-50 minutes            |
#: | 400 ppm       | 4-15 minutes             |
#:
#: Above 200 ppm brings headache, dizziness and nausea quickly; 800 ppm and
#: above can be fatal within minutes. Thresholds derive from carboxyhaemoglobin
#: loading via the Coburn-Forster-Kane equation.
UL_BANDS: tuple[tuple[float, str], ...] = (
    (30.0, "below the UL 2034 alarm floor; no alarm before 30 days"),
    (70.0, "UL 2034 alarm within 60-240 minutes"),
    (150.0, "UL 2034 alarm within 10-50 minutes"),
    (400.0, "UL 2034 alarm within 4-15 minutes"),
    (800.0, "headache, dizziness and nausea develop quickly above 200 ppm"),
    (float("inf"), "can be fatal within minutes"),
)


def band_for(co_ppm: float) -> str:
    """The UL 2034 band this reading falls in, in words."""
    for ceiling, description in UL_BANDS:
        if co_ppm < ceiling:
            return description
    return UL_BANDS[-1][1]


class SimulatedCoSensor:
    """Ramps CO through the UL 2034 bands. Never claims to have measured anything.

    Idle at a plausible household background until `trigger()` is called, then
    ramps at `ramp_ppm_per_s` toward `peak_ppm`. A demo operator triggers it; no
    sensing agent can, which keeps the simulated input from being reachable from
    anything that looks like a measurement path.
    """

    #: Ordinary indoor background. Not zero: a real detector in a real house
    #: reads a few ppm from cooking and traffic, and zero would look synthetic.
    BACKGROUND_PPM = 3.0

    def __init__(self, *, ramp_ppm_per_s: float = 4.0, peak_ppm: float = 420.0) -> None:
        self._ramp = ramp_ppm_per_s
        self._peak = peak_ppm
        self._co = self.BACKGROUND_PPM
        self._ramping = False
        self._smoke = False
        self._last: datetime | None = None

    def trigger(self, *, smoke: bool = True) -> None:
        """Start the ramp. The demo trigger, and the only way CO ever rises."""
        self._ramping = True
        self._smoke = smoke

    def clear(self) -> None:
        self._ramping = False
        self._smoke = False
        self._co = self.BACKGROUND_PPM

    def advance(self, seconds: float) -> None:
        """Move the simulated clock forward. Tests drive this instead of sleeping.

        Separated from `read` so a test never has to wait in real time for a
        ramp, and so the ramp is deterministic rather than dependent on how long
        the machine took between two calls.
        """
        if self._ramping:
            self._co = min(self._peak, self._co + self._ramp * seconds)

    def read(self) -> GasReading:
        now = datetime.now(UTC)
        elapsed = (now - self._last).total_seconds() if self._last else 0.0
        self._last = now
        self.advance(elapsed)
        return GasReading(
            co_ppm=round(self._co, 1),
            smoke=self._smoke,
            captured_at=now,
            # The literal string root CLAUDE.md requires. `Provenance` computes
            # `simulated` from it, so this one constant is what keeps a
            # generated number from ever being renderable as a measured one.
            source="demo-trigger",
        )


#: Above this, CO is a finding rather than background. The UL 2034 alarm floor.
ELEVATED_PPM = 30.0

#: Above this, symptoms develop quickly and it belongs in the 911 report.
SYMPTOMATIC_PPM = 200.0
