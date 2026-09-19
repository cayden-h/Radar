"""Talks to the resident, in the app, while the incident is happening.

Part of `agents/caller` since 2026-09-19, and the merge is principled rather
than a headcount cut: **caller is the agent that talks to humans**, and there
are two of them on a live incident. The operator hears it by phone; the resident
reads it in the app. Both are the same boundary - plain English, no ANS, a
person on the far end - and both are fed by the same verified state.

Keeping them in one agent also removes a failure this system cannot afford: two
independent agents translating the same incident could tell the operator and the
resident different things. One agent holds one picture and says it twice.

Two jobs, merged because they are the same job: telling a frightened person what
to do next.

1. **Relay.** What the operator and responders have said, translated into what
   it means for them. "Units are two minutes out. Stay where you are, unlock the
   front door if you can do it safely."
2. **First aid.** Instructions for the situation at hand.

**This file is the only place medical text exists in the whole system.** The iOS
client contains none and must not acquire any, because hardcoding first-aid copy
in a view puts it outside the one component that gets reviewed against the
safety rules. Those rules are not style preferences - bad first-aid instruction
is real-world harm, not a demo bug:

- **Stay inside well-established public protocols only.** Get out and stay out,
  stay low, do not confront, wait for responders. Nothing improvised, and
  nothing generated.
- **Always defer to the dispatcher.** If the operator is giving instructions,
  relay theirs rather than producing competing ones. Dispatchers are trained in
  emergency medical dispatch protocols and this agent is not. `deferring` is a
  flag on every instruction and it suppresses the generated ones outright.
- **Never instruct an action that could injure the patient or the user.**
  Every such case in the table below is spelled out as a "do not" rather than
  being left absent: do not go back into a fire, do not go and look during a
  burglary, do not confront anyone.
- **"Wait for responders" is frequently the correct answer.** Make sure it can
  be given, and give it.

The relay half is the high-value one. The first-aid half is the one to cut if
time runs out.
"""

from __future__ import annotations

from dataclasses import dataclass

from hawkeye_backend.models.incident import IncidentType


@dataclass(frozen=True)
class Instruction:
    """One thing to tell the resident, and where it came from."""

    text: str
    origin: str
    """`operator` or `protocol`. The UI does not distinguish them because the
    user does not care, but the sealed record does, because accountability does."""

    urgent: bool = False
    defers_to_operator: bool = False
    """True when this exists only because the operator said it. Those are never
    suppressed and never competed with."""


#: What a relayed operator cue means for the person in the house.
#: `agents/caller` produces the cue by matching on meaning; this turns it into
#: something actionable. Keep these short: someone is reading them while
#: frightened, possibly in the dark, possibly one-handed.
RELAY: dict[str, str] = {
    "dispatched": "Help has been dispatched and is on the way.",
    "eta": "Responders are close - a couple of minutes out.",
    "unlock": "Unlock the front door if you can do it safely. If you cannot, do not try.",
    "stay_put": "The dispatcher says stay where you are.",
    "get_out": "The dispatcher says get out of the house now. Do not stop for anything.",
}


#: Established public protocol only. Every line here is standard public guidance
#: for a layperson and nothing in it is improvised.
#:
#: The fire timeline comes from `docs/research/incidents.md`: one to two minutes
#: to escape, a modern room unsurvivable in under three. So fire guidance is to
#: leave, never to investigate, and that is why there is no "check where the
#: smoke is coming from" line in this table.
#:
#: There is also no patient-care protocol here - no recovery position, no CPR -
#: and that is deliberate rather than an omission. Those lines belonged to the
#: Faint incident type, removed 2026-09-19. Neither surviving incident type is
#: one where staying to help is the right instruction: during a fire the
#: protocol is to leave and stay out, and during a burglary it is to stay hidden
#: and not go to look. Telling a resident to stay and do CPR in either case
#: would be a worse instruction, not a missing one.
PROTOCOL: dict[IncidentType, tuple[Instruction, ...]] = {
    IncidentType.FIRE: (
        Instruction("Get out now. Do not collect anything.", "protocol", urgent=True),
        Instruction("Stay low. Smoke and carbon monoxide rise, and the air is better near the floor.", "protocol", urgent=True),
        Instruction("Feel a door before opening it. If it is hot, use another way out.", "protocol"),
        Instruction("Once you are out, stay out. Do not go back in for anyone or anything.", "protocol", urgent=True),
    ),
    IncidentType.BURGLARY: (
        Instruction("Stay where you are if you are hidden. Do not go to look.", "protocol", urgent=True),
        Instruction("Keep your phone silent. It will not make a sound while this screen is open.", "protocol"),
        Instruction("If you can leave safely without being seen, do that instead.", "protocol"),
        Instruction("Do not confront anyone. Wait for officers.", "protocol", urgent=True),
    ),
}


class ResidentChannel:
    """The resident-facing half of `agents/caller`.

    Holds one piece of state that matters: whether the dispatcher has started
    giving instructions. Once they have, this stops generating its own and
    relays theirs, which is the safety rule that outranks every other line here.
    """

    def __init__(self) -> None:
        self._operator_active = False
        self._given: list[Instruction] = []

    # -------------------------------------------------------------------- relay

    def relay(self, cues: tuple[str, ...]) -> list[Instruction]:
        """Turn operator cues into resident instructions.

        Anything relayed sets the deferral flag, which suppresses this
        component's own protocol guidance from that point on. A dispatcher is
        now giving instructions, and two voices telling a frightened person
        different things is worse than one voice telling them nothing.
        """
        out: list[Instruction] = []
        for cue in cues:
            text = RELAY.get(cue)
            if text is None:
                continue
            self._operator_active = True
            instruction = Instruction(
                text=text,
                origin="operator",
                urgent=cue in ("get_out", "stay_put"),
                defers_to_operator=True,
            )
            self._given.append(instruction)
            out.append(instruction)
        return out

    # ---------------------------------------------------------------- first aid

    def first_aid(self, incident_type: IncidentType) -> list[Instruction]:
        """Protocol guidance, unless the dispatcher is already giving some.

        The refusal is the feature. Going quiet the moment a trained dispatcher
        starts talking is the single most important behaviour in this file.
        """
        if self._operator_active:
            return [
                Instruction(
                    text="Follow what the dispatcher is telling you.",
                    origin="operator",
                    defers_to_operator=True,
                )
            ]
        instructions = list(PROTOCOL.get(incident_type, ()))
        self._given.extend(instructions)
        return instructions

    def wait_for_responders(self) -> Instruction:
        """Frequently the correct answer, and always available."""
        instruction = Instruction(
            text="There is nothing more to do right now. Stay where you are and wait for responders.",
            origin="protocol",
        )
        self._given.append(instruction)
        return instruction

    @property
    def deferring(self) -> bool:
        """True once the dispatcher has started giving instructions."""
        return self._operator_active

    @property
    def given(self) -> tuple[Instruction, ...]:
        return tuple(self._given)
