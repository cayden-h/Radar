"""Who each agent is: ANSName, tier, trust profile, and what it will not claim.

One roster, and this is it. `app/backend/hawkeye_backend/master/scenario.py`
carries a copy for the hub's reachability list; that copy predates this file and
is the one to delete once the hub imports from here.

Three things are on the identity rather than buried in each agent:

- **`skills`**, because they are what the A2A card publishes and what
  `agent.webmesh.ai verify_agent` reads back. Deriving the card from the same
  object the agent runs on is how the card stays true.
- **`must_not_claim`**, lifted verbatim from `docs/research/agent-briefs.md`.
  Those lines are the ones that lose the judging conversation, so they are data
  an agent can assert against rather than a comment somebody reads once.
- **`simulated_inputs`**, because root CLAUDE.md requires a simulated input be
  labelled in the data itself. Here it is also labelled on the published card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from hawkeye_backend.models.verification import TrustProfile

# TODO(ans): `.invalid` is reserved by RFC 2606 precisely so it can never
# resolve, which keeps these from being mistaken for real registrations. Swap
# for the domain registered through GoDaddy Registry the moment `ans/` has one.
# The naming convention is the open question: is an agent
# `biometrics.hawkeye.example` or `hawkeye.example/agents/biometrics`? Check
# agent.webmesh.ai's /.well-known/agents-index.json and match it.
DOMAIN = "hawkeye.invalid"

# The version is inside the ANSName: `ans://v0.1.0.biometrics.hawkeye.invalid`,
# and the same string goes in the certificate SAN. That is what "version-bound"
# means concretely (ans/CARD.md). Bump this and re-register on any card or code
# change; changing a card without re-registering is exactly the signature
# `card_drift_watch` looks for, and also what a compromised agent looks like.
VERSION = "0.1.0"


class Role(StrEnum):
    """Which side of the architecture an agent sits on.

    The boundary is the point. SENSING and COORDINATION agents only ever speak
    to other agents, over ANS. HUMAN_BOUNDARY agents are the two translators,
    and they are the only ones allowed to emit plain English at a person.
    """

    SENSING = "sensing"
    COORDINATION = "coordination"
    HUMAN_BOUNDARY = "human-boundary"


@dataclass(frozen=True)
class Skill:
    """One thing an agent will answer. Published on the A2A card."""

    id: str
    name: str
    description: str
    # Interior-state fields this skill asserts, e.g. "biometrics.respiration".
    # These are the `field` values that end up in a claim envelope.
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentIdentity:
    """Everything about an agent that is true before it starts running."""

    slug: str
    """Directory name: `biometrics`. The subpackage is `agents.biometrics`."""

    tier: int
    """Build order when time is short. 1 first."""

    role: Role
    summary: str
    """One line. Goes on the card, so it is read by a verifier, not just by us."""

    question: str
    """The single question this agent answers, from its brief."""

    profile: TrustProfile
    """What `master` lets this agent's claims trigger. See the table in agents/CLAUDE.md."""

    skills: tuple[Skill, ...] = ()
    must_not_claim: tuple[str, ...] = ()
    """Verbatim from docs/research/agent-briefs.md. Published on the card."""

    simulated_inputs: tuple[str, ...] = ()
    """Named on the card. Absent means every input this agent reads is measured."""

    consumes: tuple[str, ...] = field(default_factory=tuple)
    """Slugs of agents this one depends on. Documentation until the wire exists."""

    @property
    def name(self) -> str:
        """The name used throughout the docs: `agents/biometrics`."""
        return f"agents/{self.slug}"

    @property
    def host(self) -> str:
        return f"{self.slug}.{DOMAIN}"

    @property
    def ansname(self) -> str:
        """`ans://v0.1.0.biometrics.hawkeye.invalid`. The version is inside the name."""
        return f"ans://v{VERSION}.{self.host}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


# --------------------------------------------------------------------- the nine


SENSING_MUST_NOT = (
    "Absence of a respiration signature is not absence of a person. Shallow "
    "breathing, breath-holding and range limits all degrade toward invisible.",
)


ROSTER: tuple[AgentIdentity, ...] = (
    AgentIdentity(
        slug="biometrics",
        tier=1,
        role=Role.SENSING,
        summary="Respiration and heart rate from CSI, and the arbiter of what counts as a person.",
        question="Is this a living person, and what is their respiration and heart rate?",
        # FIDUCIARY: its verdict is what turns an occupancy report into a medical
        # emergency, and "unresponsive occupant in the main bedroom" originates
        # here. Nothing else in the stack can tell a human from a curtain.
        profile=TrustProfile.FIDUCIARY,
        skills=(
            Skill(
                id="personhood",
                name="Personhood verdict",
                description=(
                    "Whether a perturbation shows quasi-periodic modulation in the "
                    "0.1-0.5 Hz respiration band. Calibration-free: periodicity does "
                    "not depend on knowing what an empty room looks like."
                ),
                fields=("biometrics.personhood", "biometrics.person_confidence"),
            ),
            Skill(
                id="respiration",
                name="Respiration rate",
                description="Breaths per minute, 6-30. Outside that range, null rather than a number.",
                fields=("biometrics.respiration", "biometrics.breathing_bpm"),
            ),
            Skill(
                id="heart-rate",
                name="Heart rate",
                description=(
                    "40-120 BPM, best effort. A good number to say on the call and never "
                    "a decision input: a heartbeat moves the chest wall a few tenths of a "
                    "millimetre against 5-12mm for breathing, under respiration harmonics."
                ),
                fields=("biometrics.heart_bpm",),
            ),
        ),
        must_not_claim=SENSING_MUST_NOT
        + ("Heart rate is never the personhood test. Respiration carries every decision.",),
    ),
    AgentIdentity(
        slug="occupancy",
        tier=1,
        role=Role.SENSING,
        summary="How many people are in the building, where each one is, and coarsely what each one is.",
        question="How many people, where, and what kind?",
        # TRANSACTIONAL, not FIDUCIARY, and the reason is on the card: a 1x1
        # radio resolves presence, not an exact count. Its zone answers are
        # sound; its count is corroboration for a roster figure.
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="zones",
                name="Room-level occupancy",
                description=(
                    "Which zone each resolved presence is in. Room-level, never coordinates: "
                    "the literature does not support coordinates at this hardware tier."
                ),
                fields=("occupancy.zone", "occupancy.zone_confidence"),
            ),
            Skill(
                id="headcount",
                name="Headcount",
                description=(
                    "Occupants in the building. Sourced from device association against the "
                    "registered roster, because that comes from the network and is certain. "
                    "A sensed count is reported separately, as a floor, with a confidence."
                ),
                fields=("occupancy.headcount", "occupancy.sensed_presences"),
            ),
            Skill(
                id="class",
                name="Coarse class",
                description=(
                    "Adult versus small-and-fast-breathing, decided from the respiration rate "
                    "agents/biometrics supplies, not from signal amplitude."
                ),
                fields=("occupancy.presence_class",),
            ),
        ),
        must_not_claim=(
            "Person re-identification. RuView flags it experimental and data-gated, and "
            "gait-based WiFi identification needs a walking subject, which a person "
            "motionless on a floor is not.",
            "An exact sensed count. The BCM43455c0 is 1x1: frequency diversity across "
            "subcarriers, no spatial diversity. Two people within roughly a metre read as "
            "one. A sensed count is phrased as 'at least', never as a figure.",
            "Coordinates. Zones are room-level by design.",
        ),
        consumes=("biometrics",),
    ),
    AgentIdentity(
        slug="intruder",
        tier=1,
        role=Role.SENSING,
        summary="Detects and tracks a presence that no registered device accounts for.",
        question="Which presence should not be here?",
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="unexpected-presence",
                name="Unexpected presence",
                description=(
                    "A body with no corresponding device. Roster plus device association: "
                    "the household is configuration, not a discovery problem."
                ),
                fields=("intruder.unexpected_presence", "intruder.basis"),
            ),
            Skill(
                id="separation",
                name="Intruder and resident separation",
                description=(
                    "Where the unexpected presence is and where the residents are, tracked "
                    "separately. This is the answer responding officers need."
                ),
                fields=("intruder.intruder_zone", "intruder.resident_zones"),
            ),
        ),
        must_not_claim=(
            "That we recognise individuals. We do not. 'Unexpected' is device arithmetic.",
            "That the rule has no holes. A resident who left their phone in the car, a "
            "guest, and a burglar carrying a phone that never associates all defeat it. "
            "Every real security product has these gaps; name them.",
            "An intruder without a personhood verdict. A perturbation with no respiration "
            "signature is a curtain, and calling police on a curtain is the failure mode.",
        ),
        consumes=("biometrics", "occupancy"),
    ),
    AgentIdentity(
        slug="collapse",
        tier=1,
        role=Role.SENSING,
        summary="Someone was upright, is now down, and has not gotten up.",
        question="Did someone go down, and are they still down?",
        # FIDUCIARY: still_down_s is the clinical variable this whole project
        # moves, and it is the sentence the dispatcher most needs to hear.
        profile=TrustProfile.FIDUCIARY,
        skills=(
            Skill(
                id="collapse-event",
                name="Collapse detection",
                description=(
                    "A downward transition followed by absence of normal movement. The "
                    "'followed by' is the whole engineering problem: sitting down fast, "
                    "lying down to sleep and a child playing all look like a fall for an instant."
                ),
                fields=("collapse.detected", "collapse.zone"),
            ),
            Skill(
                id="still-down",
                name="Time down",
                description=(
                    "Seconds since the collapse, while the person has not gotten up. A long "
                    "lie is clinically over an hour; 53% of older fall patients are still on "
                    "the floor when the ambulance arrives, and half of those down over an "
                    "hour die within six months absent any injury from the fall."
                ),
                fields=("collapse.still_down_s", "collapse.long_lie"),
            ),
        ),
        must_not_claim=SENSING_MUST_NOT
        + (
            "A collapse on a single downward transition. Without the absence-of-movement "
            "confirmation it is a couch, and a system that calls 911 when someone flops "
            "onto a couch is worse than no system.",
        ),
        consumes=("biometrics",),
    ),
    AgentIdentity(
        slug="environment",
        tier=3,
        role=Role.SENSING,
        summary="Carbon monoxide and smoke. A separate modality from CSI, and currently simulated.",
        question="Is the air dangerous?",
        # READ_ONLY, and honestly so: the number is not measured. Corroboration
        # only, never the sole basis for a call. The profile encodes that.
        profile=TrustProfile.READ_ONLY,
        skills=(
            Skill(
                id="co",
                name="Carbon monoxide",
                description=(
                    "Parts per million, banded against UL 2034 alarm thresholds. Not from "
                    "CSI: a 2.4/5 GHz radio cannot sense gas composition at any price, and "
                    "oxygen absorption is a ~60 GHz phenomenon. Two independent modalities "
                    "agreeing is real corroboration; two views of one CSI stream is not."
                ),
                fields=("environment.co_ppm", "environment.co_band"),
            ),
        ),
        must_not_claim=(
            "That CSI can detect gas. It cannot. The claim is about the architecture: a "
            "real MQ-7 on the Pi's GPIO is a driver behind an interface that already "
            "exists, and nothing above it changes.",
            "That this reading was measured. No gas sensor was purchased. Every reading "
            "carries source `demo-trigger`, which computes to simulated, so it cannot be "
            "presented as measured by accident.",
        ),
        simulated_inputs=(
            "Carbon monoxide concentration. No MQ-7 sensor exists on this installation; "
            "the reading is generated by a UL 2034 band ramp and labelled `demo-trigger`.",
        ),
    ),
    AgentIdentity(
        slug="master",
        tier=1,
        role=Role.COORDINATION,
        summary="The incident coordinator, and the strictest verification point in the system.",
        question="What kind of incident is this, and who needs to know?",
        profile=TrustProfile.FIDUCIARY,
        skills=(
            Skill(
                id="classify",
                name="Incident classification",
                description=(
                    "Burglary, Fire or Faint, combined from independent modalities rather "
                    "than switched on one signal. A fall plus elevated CO is a fire with a "
                    "casualty, not a faint."
                ),
                fields=("master.incident_type", "master.classification_basis"),
            ),
            Skill(
                id="verify",
                name="Claim verification",
                description=(
                    "Every accepted claim carries the identity of the agent that made it, "
                    "that agent's Trust Index score at that instant, and a verification "
                    "result. Anything unverifiable is discarded and logged as discarded."
                ),
                fields=("master.accepted", "master.discarded"),
            ),
            Skill(
                id="fanout",
                name="Live query fan-out",
                description=(
                    "An operator question becomes fresh ANS-verified queries to the sensing "
                    "agents, answered from live verification rather than cached state."
                ),
                fields=("master.answer",),
            ),
        ),
        must_not_claim=(
            "That it may dial. master never initiates a 911 call. Sensing agents inform it "
            "continuously; a human tap is what releases agents/caller.",
            "That an UNTRUSTED verdict revokes anything. Suppression is not revocation; "
            "only the RA revokes. master stops accepting a drifting agent's claims and "
            "logs the discard.",
        ),
        consumes=("biometrics", "occupancy", "intruder", "collapse", "environment"),
    ),
    AgentIdentity(
        slug="caller",
        tier=1,
        role=Role.HUMAN_BOUNDARY,
        summary="Speaks to the 911 operator by phone. The only agent that acts on the outside world.",
        question="What does a dispatcher need to hear, and what are they asking?",
        profile=TrustProfile.FIDUCIARY,
        skills=(
            Skill(
                id="report",
                name="Outbound report",
                description=(
                    "The incident in plain English. Every claim spoken has a verified source "
                    "or it does not get spoken. Location and life status first; this is a "
                    "live dispatcher, not a chat window."
                ),
                fields=("caller.utterance",),
            ),
            Skill(
                id="answer",
                name="Inbound operator questions",
                description=(
                    "An operator question, parsed and fanned out through master as verified "
                    "queries. 'I don't know' is always available and gets used."
                ),
                fields=("caller.answer",),
            ),
            Skill(
                id="bridge",
                name="Conference bridge control",
                description=(
                    "Per-leg send and receive on a server-side bridge. Whisper mode is "
                    "send-on, receive-off: the resident is heard and the phone stays silent, "
                    "because silence is enforced on the wire rather than promised by a device."
                ),
                fields=("caller.bridge_state",),
            ),
        ),
        must_not_claim=(
            "That the call is cryptographically verified. The far end is a person on a "
            "phone. A voice asserting verification is worth exactly what a voice asserting "
            "there is a fire is worth, and claiming it would be the project's own threat "
            "model pointed at a dispatcher.",
            "Anything it did not verify live. An operator's authority never widens what "
            "this agent will trust; that is the social-engineering vector the project exists "
            "to close.",
        ),
        consumes=("master",),
    ),
    AgentIdentity(
        slug="guidance",
        tier=2,
        role=Role.HUMAN_BOUNDARY,
        summary="Tells the resident what to do next, in the iOS app, while the incident is happening.",
        question="What does the frightened person in the house do next?",
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="relay",
                name="Operator relay",
                description=(
                    "What the dispatcher and responders said, translated into what it means "
                    "for the resident. The high-value half."
                ),
                fields=("guidance.relay",),
            ),
            Skill(
                id="first-aid",
                name="First aid",
                description=(
                    "Well-established public protocols only: hands-only CPR, recovery "
                    "position, stop-the-bleed, get out and stay out. Nothing improvised."
                ),
                fields=("guidance.instruction",),
            ),
        ),
        must_not_claim=(
            "Medical advice outside established public protocol. Bad first-aid instruction "
            "is real-world harm, not a demo bug.",
            "Anything that competes with the dispatcher. If the operator is giving "
            "instructions, relay theirs. They are trained in emergency medical dispatch "
            "protocols and this agent is not.",
        ),
        consumes=("master", "caller"),
    ),
    AgentIdentity(
        slug="replay",
        tier=3,
        role=Role.COORDINATION,
        summary="The incident recorder. What happened, in order, on whose authority, sealed.",
        question="What happened, in what order, on whose authority?",
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="seal",
                name="Sealed incident record",
                description=(
                    "Every claim, verification result, discard, utterance and operator reply, "
                    "hash-chained and sealed into the SCITT transparency log, where entries "
                    "cannot be altered after the fact."
                ),
                fields=("replay.entry", "replay.seal"),
            ),
        ),
        must_not_claim=(
            "That this prevents a malicious call. It makes one attributable, which beats "
            "tracing a spoofed number. Swatting investigations are entirely post-hoc.",
        ),
        consumes=("master",),
    ),
)

BY_SLUG: dict[str, AgentIdentity] = {a.slug: a for a in ROSTER}


def identity(slug: str) -> AgentIdentity:
    """Look up an agent, or fail with the list rather than a KeyError."""
    try:
        return BY_SLUG[slug]
    except KeyError:
        known = ", ".join(sorted(BY_SLUG))
        raise KeyError(f"no agent {slug!r}; the nine are: {known}") from None
