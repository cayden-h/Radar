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
from agents.core.ports import ObservationSource

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
QUESTION_ROUTES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "people.respiration_lost",
        (
            "responsive",
            "respond",
            "answer",
            "how long",
            "when did",
            "since",
            "unconscious",
            "passed out",
        ),
    ),
    ("people.respiration", ("breathing", "breath", "respiration", "still alive", "conscious")),
    ("people.breathing_bpm", ("how fast", "breathing rate", "breaths")),
    ("people.headcount", ("how many", "anyone else", "who else", "occupants", "people")),
    ("people.zone", ("where", "which room", "what room", "located")),
    ("intruder.unexpected_presence", ("intruder", "someone else", "stranger", "break in")),
    ("intruder.resident_zones", ("where is the resident", "where are they", "homeowner")),
    ("master.co_ppm", ("carbon monoxide", "co level", "gas", "air", "smoke")),
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
    "people.respiration_lost",
    "people.respiration",
    "people.zone",
    "people.headcount",
    "intruder.unexpected_presence",
    "intruder.occupied_zones",
    "master.co_ppm",
    "people.breathing_bpm",
    "people.heart_bpm",
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
NEGATIVE_VALUES = frozenset({"false", "at least 0", "0"})


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
        case "people.respiration_lost":
            minutes = float(value) / 60.0
            ago = (
                f"{minutes:.0f} minutes ago" if minutes >= 1 else f"{float(value):.0f} seconds ago"
            )
            return (
                f"I had a breathing signature{where} {ago} and I do not have one now. "
                "That is not the same as them having stopped breathing - I cannot resolve "
                "shallow breathing. Do not expect them to answer."
            )
        case "people.respiration":
            return (
                f"They are breathing{where}."
                if value == "breathing"
                else f"I cannot resolve breathing{where}. That is not the same as them not breathing."
            )
        case "people.breathing_bpm":
            return f"Breathing about {float(value):.0f} a minute."
        case "people.heart_bpm":
            return f"Heart rate about {float(value):.0f}, best effort."
        case "people.zone":
            return f"There is a person in the {value.replace('_', ' ')}."
        case "people.headcount":
            return f"{value} resident(s) are home, by the devices on the home network."
        case "people.sensed_presences":
            return f"The radio resolves {value} breathing presence(s)."
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
        case _:
            return f"{field.split('.', 1)[1].replace('_', ' ')}: {value}{where}."


def _shorten(reason: str, limit: int = 140) -> str:
    """Trim a verification reason to something sayable on a live call."""
    reason = " ".join(reason.split())
    if len(reason) <= limit:
        return reason
    return reason[: limit - 1].rsplit(" ", 1)[0] + "."
