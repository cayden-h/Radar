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

# Registered 2026-09-19. `.club` is a GoDaddy Registry TLD, so this also stacks
# the MLH Best Domain Name prize. The registrar is Porkbun, which is where the
# DNS records below get published.
#
# Subdomain per agent, settled by the shape of the registration rather than by
# preference: ANS publishes `_ans.<host>` and `_ans-badge.<host>` TXT records
# per registration, so five agents sharing one host would collide on them.
# `people.batradar.club`, not `batradar.club/agents/people`.
DOMAIN = "batradar.club"

# The version is inside the ANSName: `ans://v0.1.0.people.hawkeye.invalid`,
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
    # Interior-state fields this skill asserts, e.g. "people.respiration".
    # These are the `field` values that end up in a claim envelope.
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentIdentity:
    """Everything about an agent that is true before it starts running."""

    slug: str
    """Directory name: `people`. The subpackage is `agents.people`."""

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
        """The name used throughout the docs: `agents/people`."""
        return f"agents/{self.slug}"

    @property
    def host(self) -> str:
        return f"{self.slug}.{DOMAIN}"

    @property
    def ansname(self) -> str:
        """`ans://v0.1.0.people.hawkeye.invalid`. The version is inside the name."""
        return f"ans://v{VERSION}.{self.host}"

    @property
    def base_url(self) -> str:
        return f"https://{self.host}"


# --------------------------------------------------------------------- the five
#
# Five agents, settled 2026-09-19, down from nine. The merges were made on the
# principle that an agent is a *context boundary*, not a task: two components
# that read the same input, share the same state, and always run in the same
# order are one agent with two steps, and splitting them buys deployments rather
# than separation.
#
# What the merge did NOT touch is the line the ANS story runs along. The hops
# that carry a claim from something that senses to something that decides to
# something that speaks are all still hops between independently registered
# agents:
#
#     people ---ANS---> master ---ANS---> caller ---plain English---> 911
#     intruder -ANS---^                 \--ANS--> replay
#
# Absorbed, and where each went:
#
#   biometrics  -> people    personhood is what makes a presence a person, and
#                            everything people says is conditioned on it
#   occupancy   -> people    same CSI window, same baseline, same tick
#   environment -> master    a locally-attached sensor has no counterparty to
#                            authenticate; see agents/master/environment.py
#   guidance    -> caller    caller is the agent that talks to humans, and there
#                            are two of them on a live incident


ROSTER: tuple[AgentIdentity, ...] = (
    AgentIdentity(
        slug="people",
        tier=1,
        role=Role.SENSING,
        summary=(
            "Who is in the building, where each one is, whether they are breathing, and "
            "whether anyone has stopped being resolvable."
        ),
        question="How many people, where, in what state, and should a dispatcher expect an answer?",
        # FIDUCIARY: its verdicts are what turn an occupancy report into a
        # medical emergency. "A breathing signature in the main bedroom that we
        # had four minutes ago and do not have now" originates entirely here,
        # and nothing else in the stack can tell a human from a curtain.
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
                fields=("people.personhood", "people.respiration", "people.moving"),
            ),
            Skill(
                id="vitals",
                name="Respiration and heart rate",
                description=(
                    "Breaths per minute, 6-30; outside that range, null rather than a number. "
                    "Heart rate 40-120 is best effort - a good number to say on the call and "
                    "never a decision input, because a heartbeat moves the chest wall a few "
                    "tenths of a millimetre against 5-12mm for breathing."
                ),
                fields=("people.breathing_bpm", "people.heart_bpm"),
            ),
            Skill(
                id="zones",
                name="Room-level location",
                description=(
                    "Which zone each resolved presence is in. Room-level, never coordinates: "
                    "the literature does not support coordinates at this hardware tier."
                ),
                fields=("people.zone", "people.presence_class", "people.perturbation"),
            ),
            Skill(
                id="headcount",
                name="Headcount",
                description=(
                    "Occupants in the building. Sourced from device association against the "
                    "registered roster, because that comes from the network and is certain. "
                    "A sensed count is reported separately, as a floor, with a confidence."
                ),
                fields=("people.headcount", "people.sensed_presences"),
            ),
            Skill(
                id="responsiveness",
                name="Responsiveness",
                description=(
                    "Whether a breathing signature that was present in a zone is still "
                    "resolvable, and the seconds since it was last seen. The transition is "
                    "the signal: a presence that never resolved a signature carries no "
                    "information, because shallow breathing, breath-holding and range limits "
                    "are indistinguishable from an empty room. What this answers for a "
                    "dispatcher is whether to expect a response from whoever is in that room."
                ),
                fields=("people.respiration_lost",),
            ),
        ),
        must_not_claim=(
            "Absence of a respiration signature is not absence of a person. Shallow "
            "breathing, breath-holding and range limits all degrade toward invisible.",
            "Heart rate is never the personhood test. Respiration carries every decision.",
            "Person re-identification. RuView flags it experimental and data-gated, and "
            "gait-based WiFi identification needs a walking subject, which a person "
            "motionless on a floor is not.",
            "An exact sensed count. The BCM43455c0 is 1x1: frequency diversity across "
            "subcarriers, no spatial diversity. Two people within roughly a metre read as "
            "one. A sensed count is phrased as 'at least', never as a figure.",
            "Coordinates. Zones are room-level by design.",
            "That a person has stopped breathing. A signature that is no longer resolvable "
            "is a reason to look, never a finding about a body. Shallow breathing and range "
            "limits produce exactly this reading.",
            "Anything at all about a presence that never established a breathing signature. "
            "A moving body swamps its own chest sinusoid with broadband motion, so someone "
            "who goes from walking to gone leaves no transition to report. Only "
            "breathing-then-silent is a signal; that limit is the price of the claim being "
            "worth anything.",
        ),
    ),
    AgentIdentity(
        slug="intruder",
        tier=1,
        role=Role.SENSING,
        summary="Detects and tracks a presence that no registered device accounts for.",
        question="Which presence should not be here, and where is everybody?",
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
                    "separately. This is the answer responding officers need, and no other "
                    "product gives it to them."
                ),
                fields=(
                    "intruder.intruder_zone",
                    "intruder.occupied_zones",
                    "intruder.resident_zones",
                ),
            ),
        ),
        must_not_claim=(
            "That we recognise individuals. We do not. 'Unexpected' is device arithmetic.",
            "That the rule has no holes. A resident who left their phone in the car, a "
            "guest, and a burglar carrying a phone that never associates all defeat it. "
            "Every real security product has these gaps; name them.",
            "An intruder without a personhood verdict from agents/people. A perturbation "
            "with no respiration signature is a curtain, and calling police on a curtain "
            "is the failure mode.",
            "Which resolved presence is the stranger, when residents are also home. We "
            "know there is an extra body; without re-identification we cannot say which "
            "one, and guessing would send officers to the wrong room.",
        ),
        consumes=("people",),
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
                    "Burglary or Fire, combined from independent modalities rather than "
                    "switched on one signal. Elevated CO alongside a breathing signature "
                    "that has gone missing is a fire with an occupant who may not be able "
                    "to respond - CSI resolved the breathing, a separate gas sensor read "
                    "the air, and neither alone is that verdict."
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
                fields=("master.accepted", "master.discarded", "master.speakable"),
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
            Skill(
                id="air",
                name="Air quality",
                description=(
                    "Carbon monoxide, banded against UL 2034 alarm thresholds, read from a "
                    "locally attached sensor. A second modality from CSI, which is what makes "
                    "agreement between them real corroboration rather than two views of one "
                    "stream. Read directly rather than through the gate, because a sensor on "
                    "this host has no counterparty to authenticate - and labelled as such."
                ),
                fields=("master.co_ppm", "master.co_band", "master.co_elevated"),
            ),
        ),
        must_not_claim=(
            "That it may dial. master never initiates a 911 call. Sensing agents inform it "
            "continuously; a human tap is what releases agents/caller.",
            "That an UNTRUSTED verdict revokes anything. Suppression is not revocation; "
            "only the RA revokes. master stops accepting a drifting agent's claims and "
            "logs the discard.",
            "That the carbon monoxide reading was measured. No gas sensor was purchased. "
            "Every reading carries source `demo-trigger`, which computes to simulated.",
            "That CSI can detect gas. It cannot, at any price, on a 2.4/5 GHz radio. The "
            "extensibility claim is about the architecture, not the radio.",
        ),
        simulated_inputs=(
            "Carbon monoxide concentration. No MQ-7 sensor exists on this installation; "
            "the reading is generated by a UL 2034 band ramp and labelled `demo-trigger`. "
            "A real MQ-7 on the Pi's GPIO is a driver behind an interface that already "
            "exists, and nothing above it changes.",
        ),
        consumes=("people", "intruder"),
    ),
    AgentIdentity(
        slug="caller",
        tier=1,
        role=Role.HUMAN_BOUNDARY,
        summary=(
            "The agent that talks to humans: the 911 operator by phone, and the resident "
            "in the app. The only agent that acts on the outside world."
        ),
        question="What does a dispatcher need to hear, what are they asking, and what does the resident do next?",
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
            Skill(
                id="guidance",
                name="Resident guidance",
                description=(
                    "What the dispatcher said, translated into what it means for the person "
                    "in the house, plus first aid from established public protocol only - "
                    "hands-only CPR, the recovery position, stay low, do not move someone "
                    "who fell. Always defers to the dispatcher."
                ),
                fields=("caller.relay", "caller.instruction"),
            ),
        ),
        must_not_claim=(
            "That the call is cryptographically verified. The far end is a person on a "
            "phone. A voice asserting verification is worth exactly what a voice asserting "
            "there is a fire is worth, and claiming it would be the project's own threat "
            "model pointed at a dispatcher.",
            "Anything it did not verify live. An operator's authority never widens what "
            "this agent will trust, and neither does a frightened resident's typing; that "
            "is the social-engineering vector the project exists to close.",
            "Medical advice outside established public protocol. Bad first-aid instruction "
            "is real-world harm, not a demo bug.",
            "Anything that competes with the dispatcher. If the operator is giving "
            "instructions, relay theirs. They are trained in emergency medical dispatch "
            "protocols and this agent is not.",
        ),
        consumes=("master",),
    ),
    AgentIdentity(
        slug="replay",
        tier=2,
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
            Skill(
                id="movement",
                name="Movement record",
                description=(
                    "Where each tracked presence moved through the house and when. After a "
                    "burglary this is the half a detective actually wants, and it is "
                    "tamper-evident."
                ),
                fields=("replay.movement",),
            ),
        ),
        must_not_claim=(
            "That this prevents a malicious call. It makes one attributable, which beats "
            "tracing a spoofed number. Swatting investigations are entirely post-hoc.",
            "That the local hash chain is a transparency-log seal. The chain is "
            "tamper-evident to whoever holds the record; the log is what makes it "
            "verifiable by someone who does not.",
        ),
        consumes=("master",),
    ),
    AgentIdentity(
        slug="shutter",
        tier=1,
        role=Role.COORDINATION,
        summary=(
            "Holds an opaque shield in front of the camera lens, and moves it only for a "
            "grant from `master` it can verify."
        ),
        question="Is the lens covered, and who proved it should not be?",
        # TRANSACTIONAL, not FIDUCIARY. `shutter` asserts one physical fact
        # about one piece of plastic. It never classifies, never decides an
        # incident exists, and nothing it says should reach a dispatcher as a
        # finding about the house.
        profile=TrustProfile.TRANSACTIONAL,
        skills=(
            Skill(
                id="challenge",
                name="Grant challenge",
                description=(
                    "Issues the single-use nonce a grant must carry, with a ten-second "
                    "TTL. **The verifier issues the challenge**, in both directions: "
                    "everywhere else in the mesh `master` asks and holds the nonce, and "
                    "here `master` is the one asking for something to happen, so the "
                    "nonce is held by the side doing the verifying."
                ),
                fields=("shutter.nonce",),
            ),
            Skill(
                id="open",
                name="Shield position",
                description=(
                    "Verifies a grant against the key `master` publishes in its own trust "
                    "card, moves ninety degrees, and attests the position it commanded. "
                    "Seven refusals, each signed, each leaving the servo where it was."
                ),
                fields=("shutter.position", "shutter.commanded_angle", "shutter.refusal"),
            ),
        ),
        must_not_claim=(
            "That the shield is physically where the servo says it is. The SG92R is "
            "open-loop and has no position feedback, so the attestation reports a "
            "*commanded* angle. A shield that jammed would attest open while covering the "
            "lens, and the only thing that catches that is the frame itself being dark.",
            "That the mount is tamper-resistant. It is demo-grade, and someone standing at "
            "the camera can hold it shut.",
            "That the camera is disabled. Nothing stops it at the driver level: the shield "
            "is an object in front of a lens, which is the point. A software disable is a "
            "claim and an opaque object is not.",
            "Anything about who or what is in the room. It has one input, one output, and "
            "no knowledge of what a camera is for.",
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
        raise KeyError(f"no agent {slug!r}; the roster is: {known}") from None
