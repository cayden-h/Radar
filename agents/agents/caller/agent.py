"""Talks to the 911 operator. The only agent that acts on the outside world.

This is the fiduciary agent. It speaks to emergency services on a human's
behalf, and it is the last thing between a compromised sensor and an armed
response to someone's address.

**Outbound.** Reports the incident in plain English. Every claim it speaks has a
verified source or it does not get spoken - and today nothing does, because the
transport is not wired, so this agent will say so rather than speak anyway.
That is not a degraded mode to apologise for; it is the rule working.

**Inbound.** The operator talks back, mid-call. "Is the child still breathing?"
"Anyone in the garage?" "How long since you had breathing?" Each question is parsed
and fanned out through `master` as fresh verified queries, and the answer comes
back in one short sentence.

Four rules for the inbound path, all enforced below rather than documented:

- **Answer from a live verified query, not cached state.** The operator asks now
  because the answer may have changed, and an agent trusted ninety seconds ago
  may not be trusted now. `master.answer` re-reads and re-admits every time.
- **"I don't know" must be available and must be used.** An agent that invents
  an answer for a dispatcher is worse than one that admits a gap.
- **An operator question must never widen what the agent will trust.** Pressure
  from an authority figure is a social-engineering vector. There is no branch
  here that relaxes verification, and adding one would be the failure this
  project exists to prevent.
- **Keep answers short.** A dispatcher on a live call, not a chat window.

**The resident.** Since 2026-09-19 this agent owns both human boundaries, not
just the phone. `guidance.py` is the resident-facing half: what the dispatcher
said, translated into what it means for the person in the house, plus first aid
from established public protocol. One agent holds one picture of the incident
and says it twice, which is what stops the operator and the resident being told
different things.

What this agent must never say is that the call is cryptographically verified.
The far end is a person on a phone, at both ends. A voice asserting verification
is worth exactly what a voice asserting there is a fire is worth.
"""

from __future__ import annotations

from dataclasses import dataclass

from hawkeye_backend.models.common import Provenance, Source
from hawkeye_backend.models.incident import IncidentType
from hawkeye_backend.verification.envelope import Severity

from agents.caller.bridge import Bridge, ParticipationMode
from agents.caller.guidance import Instruction, ResidentChannel
from agents.core.base import Agent
from agents.core.identity import identity
from agents.core.observations import AgentObservation, Assertion
from agents.core.phrasing import elapsed_phrase
from agents.core.ports import ObservationSource

#: Questions we used to answer and must now refuse.
#:
#: Respiration sensing was cut on 2026-09-19 and the code deleted on
#: 2026-09-20. The routes stay, pointed here, rather than being removed: a
#: deleted route lets "is she breathing?" fall through to whatever matches next,
#: and an operator getting a confident answer to a question about a different
#: thing is worse than getting none. Routing to an explicit refusal is what
#: makes "I don't know" available and used, which this agent's contract
#: requires.
UNSENSED_VITALS = "caller.unsensed_vitals"

#: Question intent to the interior-state field that answers it.
#:
#: **Match on meaning, not exact strings.** A dispatcher will not say the phrase
#: anyone hardcoded, so each intent carries several ways of asking and the match
#: is on any of them appearing. This is a keyword router, which is honest about
#: what it is: a language model would generalise better and would also be a
#: component that can be talked into something, on the one path where an
#: authority figure is applying pressure. A router that cannot be persuaded is
#: the right trade here, and anything it does not recognise becomes "I don't
#: know" rather than a guess.
#:
#: **Order is behaviour, and so is keyword breadth.** The first entry whose
#: keywords appear wins, so a broad keyword high in the table silently eats
#: every question below it. That is not a wasted "I don't know": the operator
#: asked about carbon monoxide and gets a sentence about a breathing signature,
#: delivered confidently, as the answer to their question.
#:
#: The subject-bearing routes therefore come first. "Carbon monoxide",
#: "intruder" and "how many" say what the question is *about*, and a question
#: that names its subject should reach that subject's field whatever shape the
#: rest of the sentence takes. The responsiveness route, which is about a person
#: rather than a thing, sits below them and is matched on phrases that can only
#: be about a person: "is she responsive", "will she answer you", "how long
#: since you had breathing". It used to carry bare "since", "answer", "how long"
#: and "when did", which are the words every other question is built out of.
#:
#: There is deliberately no route for how long a fire has been burning. Nothing
#: in this system measures it, and "I don't know" is the honest answer.
QUESTION_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # "air" on its own matched chair, stairs and repair. It is first in the
    # table now, so a substring that broad would have reached further than any
    # other mistake here.
    (
        "master.co_ppm",
        ("carbon monoxide", "co level", "co reading", "gas", "the air", "air quality", "smoke"),
    ),
    # The camera routes sit above `intruder` and below the gas route, and the
    # placement is the whole of their correctness.
    #
    # Above `intruder`, because after the pivot the camera is what answers "what
    # is the intruder doing". That question names its subject, so a route table
    # that matched on "intruder" first would hear a question about behaviour and
    # answer it with device arithmetic - confidently, to a dispatcher, in a
    # synthetic voice. The camera routes match only on phrases about *seeing*
    # and *doing*, which "is there an intruder" does not contain, so the
    # intruder route keeps every question that is actually about it.
    #
    # Below the gas route, because "can you see smoke" is a question about the
    # air and this camera cannot answer it.
    #
    # `vision.people_visible` comes first inside the block: it is the narrow
    # case of "how many", and the broad "how many" belongs to
    # `people.headcount` further down. A count from the camera and a count from
    # the device roster are different facts about different things - one room
    # versus the building - and handing a dispatcher either one under the
    # other's question is the mistake this ordering exists to prevent.
    (
        "vision.people_visible",
        (
            "how many can you see",
            "how many do you see",
            "how many people can you see",
            "how many people do you see",
            "how many on camera",
            "how many are on camera",
            "how many people on camera",
        ),
    ),
    # Responder safety. A dispatcher asking this is deciding what to send, so it
    # sits above the general description rather than inside it.
    (
        "vision.carrying",
        (
            "carrying",
            "holding",
            "weapon",
            "armed",
            "a gun",
            "a knife",
            "in his hand",
            "in her hand",
            "in their hand",
        ),
    ),
    (
        "vision.matches_resident",
        (
            "recognise",
            "recognize",
            "someone who lives",
            "lives there",
            "lives at",
            "one of the residents",
        ),
    ),
    (
        "vision.description",
        (
            "what do you see",
            "what can you see",
            "what are you seeing",
            "describe",
            "what is he doing",
            "what is she doing",
            "what are they doing",
            "what's he doing",
            "what's she doing",
            "what is the person doing",
            "what is the intruder doing",
            "on camera",
            "on the camera",
        ),
    ),
    (
        "vision.lighting",
        ("is it dark", "are the lights", "can you see anything", "is the camera working"),
    ),
    ("intruder.unexpected_presence", ("intruder", "someone else", "stranger", "break in")),
    ("presence.devices_home", ("how many", "anyone else", "who else", "occupants", "people")),
    (
        UNSENSED_VITALS,
        (
            "responsive",
            "respond",
            # "answer the door" and not "answer", so that "has anyone answered
            # the door?" - which is about the door - does not land here.
            "answer the door",
            "answer you",
            "answer me",
            "answer us",
            # "since" on its own belonged to every other question on the call.
            "since breathing",
            "since the breathing",
            "since you had breathing",
            "since you had a breathing",
            "been down",
            "went down",
            "on the floor",
            "unconscious",
            "passed out",
        ),
    ),
    (UNSENSED_VITALS, ("breathing", "breath", "respiration", "still alive", "conscious")),
    (UNSENSED_VITALS, ("how fast", "breathing rate", "breaths")),
    ("presence.zone", ("where", "which room", "what room", "located")),
    ("intruder.resident_zones", ("where is the resident", "where are they", "homeowner")),
)

#: What a dispatcher saying this means for the resident. `guidance` renders it.
#:
#: Meaning again, not strings. "Units are rolling" and "I've got help on the
#: way" are the same fact, and a system that only recognises one of them tells
#: the resident nothing during the call that matters most.
OPERATOR_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dispatched", ("dispatched", "on the way", "units are rolling", "sending", "help is coming")),
    ("eta", ("minutes out", "two minutes", "be there in", "almost there")),
    ("unlock", ("unlock", "open the door", "let them in")),
    ("stay_put", ("stay where you are", "don't move", "stay put", "remain")),
    ("get_out", ("get out", "leave the house", "evacuate", "outside")),
)


@dataclass(frozen=True)
class Utterance:
    """Something this agent is prepared to say, and what it is made of."""

    text: str
    claim_fields: tuple[str, ...]
    attributed_to: str
    """`agents/people`, or `resident`, or `agents/caller` for its own framing.

    Never blank. A dispatcher hearing a fact deserves to know whether it came
    from a sensor, from the person in the house, or from the agent's own
    summary, and the three are not interchangeable.
    """


class CallerAgent(Agent):
    """Composes what gets said, and refuses what cannot be."""

    #: Event-shaped rather than polled. It ticks slowly to report bridge state
    #: and does its real work when the call asks something of it.
    interval_s = 2.0

    def __init__(self, mesh: ObservationSource, master: object | None = None) -> None:
        super().__init__(identity("caller"))
        self._mesh = mesh
        # The MasterAgent instance. Typed loosely on purpose: when the transport
        # lands this becomes a verified client rather than an object reference,
        # and pinning the type now would bake the in-process shortcut into the
        # signature.
        self._master = master
        self.bridge = Bridge()
        # The resident-facing half. Same incident, same verified state, second
        # audience. See `agents/caller/guidance.py`.
        self.resident = ResidentChannel()

    # ------------------------------------------------------------------ the job

    def tick(self) -> AgentObservation:
        provenance = Provenance(
            source=Source.AGENT_INFERENCE,
            producer=self.identity.name,
            ansname=self.identity.ansname,
        )
        state = self.bridge.leg_state_summary()
        return self.observe(
            assertions=(
                Assertion(
                    field="caller.bridge_state",
                    value=state,
                    severity_ceiling=Severity.INFORMATIONAL,
                    confidence=1.0,
                    basis=(
                        "Per-leg send and receive on the server-side bridge. Silence is "
                        "enforced here rather than on the device: if the bridge never sends "
                        "audio, there is nothing for iOS to play and no volume floor to fight."
                    ),
                    provenance=provenance,
                ),
            ),
            note=state,
        )

    # -------------------------------------------------------------- outbound

    def opening_report(self, incident_type: IncidentType, address_spoken: str) -> list[Utterance]:
        """What gets said when the operator picks up.

        Location and life status first. This is a dispatcher taking a call, not
        a reader, and the first fifteen seconds decide what gets sent.

        Fire crews already know the house is burning. **What nobody knows is who
        is still inside and where**, and that is the entire value of the call.
        """
        if self._master is None:
            return [
                Utterance(
                    text="I cannot place this call: I have no connection to the incident coordinator.",
                    claim_fields=(),
                    attributed_to=self.identity.name,
                )
            ]

        lines: list[Utterance] = [
            Utterance(
                # The agent identifies itself as an agent, immediately and
                # without being asked. A synthetic voice that lets a dispatcher
                # assume it is a person is the project's own threat model being
                # performed by the project.
                text=(
                    f"This is an automated call from a home monitoring system at "
                    f"{address_spoken}. I am not a person. A resident at this address has "
                    f"reported a {incident_type.value}."
                ),
                claim_fields=(),
                attributed_to=self.identity.name,
            )
        ]

        speakable = [c for c in getattr(self._master, "admitted", []) if c.spoken]
        if not speakable:
            # The refusal, said out loud, on the call. It is better than silence
            # and far better than speaking something unverified: a dispatcher
            # told "I can't confirm that" can still send a unit, and a
            # dispatcher told a fabricated fact cannot unhear it.
            lines.append(
                Utterance(
                    text=(
                        "I have no independently verified information about the interior to "
                        "give you. I will not repeat anything I cannot verify."
                    ),
                    claim_fields=(),
                    attributed_to=self.identity.name,
                )
            )
            return lines

        worth_saying = [c for c in speakable if worth_reporting(c.assertion)]
        if not worth_saying:
            # Verified, and nothing to report. That is a real answer and a
            # dispatcher can act on it: the system is working and sees nothing.
            lines.append(
                Utterance(
                    text=(
                        "I can verify my sensors but I have nothing to report about the "
                        "interior beyond that."
                    ),
                    claim_fields=(),
                    attributed_to=self.identity.name,
                )
            )
            return lines

        for claim in _priority_order(worth_saying):
            lines.append(
                Utterance(
                    text=_speak(claim.assertion),
                    claim_fields=(claim.assertion.field,),
                    attributed_to=claim.result.agent.name,
                )
            )
        return lines

    def speak_resident_context(self, text: str) -> Utterance:
        """The resident's typed context, attributed as theirs.

        "The resident reports the smoke is coming from the laundry" is honest;
        stating it as a system observation is not. The same rule that keeps an
        operator's authority from widening what this agent trusts keeps a
        frightened resident's typing from doing it: what they type is context,
        never instruction.
        """
        return Utterance(
            text=f"The resident reports: {text}",
            claim_fields=(),
            attributed_to="resident",
        )

    # --------------------------------------------------------------- inbound

    def answer_operator(self, question: str) -> Utterance:
        """Parse one operator question, fan it out, answer in one sentence."""
        # The agent never talks over a human. The operator is speaking, so it
        # yields first and decides what to say afterwards.
        self.bridge.yield_to_human()

        field = route_question(question)
        if field is None:
            return Utterance(
                text="I don't know - I can't answer that from what I can verify.",
                claim_fields=(),
                attributed_to=self.identity.name,
            )
        if self._master is None:
            return Utterance(
                text="I don't know - I have no connection to the sensing agents right now.",
                claim_fields=(),
                attributed_to=self.identity.name,
            )

        value, why = self._master.answer(field)  # type: ignore[attr-defined]
        if value is None:
            # Short, and it says which kind of unknown it is. A dispatcher can
            # act differently on "the sensor cannot see that room" than on "I
            # refused a claim about it", and both are better than a guess.
            return Utterance(
                text=f"I don't know. {_shorten(why)}",
                claim_fields=(field,),
                attributed_to=self.identity.name,
            )
        return Utterance(
            text=_speak_value(field, value),
            claim_fields=(field,),
            attributed_to="agents/" + field.split(".", 1)[0],
        )

    def operator_said(self, text: str) -> tuple[Instruction, ...]:
        """What the operator just said, turned into instructions for the resident.

        Drives the resident's phone. "I've dispatched units" or "they're two
        minutes out" become notifications, matched on **meaning rather than
        exact strings** - a dispatcher will not say the phrase anyone hardcoded.

        Relaying anything also makes the resident channel defer: from here on it
        relays the dispatcher's instructions rather than generating its own.
        """
        lowered = text.lower()
        cues = tuple(cue for cue, phrases in OPERATOR_CUES if any(p in lowered for p in phrases))
        return tuple(self.resident.relay(cues))

    def resident_guidance(self, incident_type: IncidentType) -> tuple[Instruction, ...]:
        """First aid for the situation, unless the dispatcher is already giving some."""
        return tuple(self.resident.first_aid(incident_type))

    # ------------------------------------------------------------- ending it

    def end_call(self, *, cancelled_by_resident: bool, resident_reachable: bool) -> Utterance:
        """Never a silent hang-up.

        **An abandoned 911 call causes a dispatch.** PSAPs treat a dropped call
        as a real emergency, call back, and send units when they cannot reach
        anyone. So the leg does not close until this has been said.

        An accidental raise that is immediately cancelled should cost the
        dispatcher ten seconds, not a truck. That is also why raising an
        incident is hold-to-confirm in the app: the cheapest false alarm is the
        one that never gets placed.
        """
        if cancelled_by_resident:
            return Utterance(
                text=(
                    "This incident is being cancelled by the resident. There is no emergency "
                    "at this address. I am sorry for the interruption."
                ),
                claim_fields=(),
                attributed_to=self.identity.name,
            )
        if not resident_reachable:
            # Staying on the line is the right answer. Dropping a call to a
            # PSAP because we could not reach our own user is the worst of both
            # outcomes: a dispatch we did not ask for, with nobody to answer.
            return Utterance(
                text=(
                    "I cannot reach the resident to confirm. I am staying on the line rather "
                    "than hanging up."
                ),
                claim_fields=(),
                attributed_to=self.identity.name,
            )
        return Utterance(
            text="The resident is ending this call. Thank you.",
            claim_fields=(),
            attributed_to=self.identity.name,
        )

    # ----------------------------------------------------------- the resident

    def request_resident_voice(self) -> str:
        """The operator asks for the resident. Surfaced, never granted here."""
        return self.bridge.request_resident()

    def resident_joins(self, mode: ParticipationMode) -> str:
        """A human tapped. Opening a microphone to 911 is always their decision."""
        return self.bridge.set_mode(mode, by_human=True)


# ---------------------------------------------------------------- composition


#: What a dispatcher needs first. Life status and location before anything else.
SPEAK_PRIORITY: tuple[str, ...] = (
    # The pivot's contribution to this list, and it is near the top on purpose.
    # A dispatcher taking a burglary call already knows a system says someone is
    # in the house. What nobody else can give them is a description of who,
    # produced by a camera that could not have been watching a minute earlier,
    # and whether that person is carrying something.
    "vision.description",
    "vision.carrying",
    "presence.zone",
    "vision.people_visible",
    "intruder.unexpected_presence",
    "intruder.occupied_zones",
)


def _priority_order(claims: list[object]) -> list[object]:
    def rank(claim: object) -> int:
        field = claim.assertion.field  # type: ignore[attr-defined]
        return SPEAK_PRIORITY.index(field) if field in SPEAK_PRIORITY else len(SPEAK_PRIORITY)

    return sorted(claims, key=rank)


def route_question(question: str) -> str | None:
    """Question to the field that answers it, or None.

    None is a good outcome. An unrecognised question becomes "I don't know",
    which is correct, rather than the nearest match, which would be a guess
    delivered to emergency services in a confident synthetic voice.
    """
    lowered = question.lower()
    for field, phrases in QUESTION_ROUTES:
        if any(phrase in lowered for phrase in phrases):
            return field
    return None


#: Claims whose negative value is not worth a dispatcher's attention.
#:
#: "No unexpected presence" and "nobody unaccounted for" are meaningful to the
#: system and noise on a live call. A dispatcher has seconds and needs what IS
#: happening; a list of things that are not is how the one thing that matters
#: gets buried. They stay in the verification feed, where they belong.
#
# The empty string and "nothing" are here for `vision.carrying`, which is empty
# most of the time: the model only reports an object when it sees one. "The
# camera is describing them carrying nothing" is a sentence that sounds like a
# finding and is not one.
NEGATIVE_VALUES = frozenset({"false", "at least 0", "0", "", "none", "nothing"})


def worth_reporting(assertion: Assertion) -> bool:
    """Whether this claim earns a sentence on a live 911 call.

    Separate from whether it is *verified* and separate from whether it is
    *true*. A verified, true, negative claim is still not something to read to a
    dispatcher.
    """
    return assertion.value.strip().lower() not in NEGATIVE_VALUES


def _speak(assertion: Assertion) -> str:
    return _speak_value(assertion.field, assertion.value, zone=assertion.zone_scope)


def _speak_value(field: str, value: str, *, zone: str | None = None) -> str:
    """One short sentence a dispatcher can act on. No jargon, no hedging stack."""
    where = f" in the {zone.replace('_', ' ')}" if zone and zone != "site" else ""
    match field:
        case _ if field == UNSENSED_VITALS:
            return (
                "I cannot tell you that. This system does not sense breathing or a "
                "pulse - it has a camera, and a camera cannot see either one. I will "
                "not guess at it."
            )
        case "presence.zone":
            return f"There was movement in the {value.replace('_', ' ')}."
        case "presence.devices_home":
            return f"{value} resident(s) are home, by the devices on the home network."
        case "intruder.unexpected_presence":
            return (
                "There is someone in the house that no registered device accounts for."
                if value == "true"
                else "Everyone the radio resolves is accounted for by a registered device."
            )
        case "intruder.intruder_zone":
            return f"The unaccounted person is in the {value.replace('_', ' ')}."
        case "intruder.occupied_zones":
            rooms = ", ".join(z.replace("_", " ") for z in value.split(","))
            return f"People are in: {rooms}. I cannot tell you which one is the stranger."
        case "intruder.resident_zones":
            rooms = ", ".join(z.replace("_", " ") for z in value.split(","))
            return f"The residents are in: {rooms}."
        case "master.co_ppm":
            return f"Carbon monoxide is at {float(value):.0f} parts per million."
        # The camera. Every one of these leads with what produced it, because
        # `vision/CLAUDE.md` requires the 911 script to say "the camera is
        # describing a person in a dark jacket" and never "the intruder is
        # wearing a dark jacket". The model describes; it does not identify, and
        # the sentence a dispatcher hears has to carry that difference.
        case "vision.description":
            return f"The camera is describing{where}: {value}"
        case "vision.people_visible":
            people = "person" if value == "1" else "people"
            return (
                f"The camera can see {value} {people}{where}. That is a count of one room, "
                "not of the building."
            )
        case "vision.carrying":
            return f"The camera is describing them carrying {value}."
        case "vision.matches_resident":
            if value == "no_match":
                return (
                    "Not one of the people who live here, as far as the camera can tell. "
                    "That is all it means - it is not a match against any database."
                )
            if value.startswith("match:"):
                return "The camera matches them to someone enrolled as living at this address."
            return "I cannot tell you whether that person lives here."
        case "vision.lighting":
            if value == "too_dark":
                return (
                    "The room is too dark for the camera to describe anything. I will not "
                    "guess at what is in it."
                )
            if value == "low":
                return "The room is dimly lit. The camera is describing what it can make out."
            return "The room is lit and the camera can see it."
        case _:
            return f"{field.split('.', 1)[1].replace('_', ' ')}: {value}{where}."


def _shorten(reason: str, limit: int = 140) -> str:
    """Trim a verification reason to something sayable on a live call."""
    reason = " ".join(reason.split())
    if len(reason) <= limit:
        return reason
    return reason[: limit - 1].rsplit(" ", 1)[0] + "."
