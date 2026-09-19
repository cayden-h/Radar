"""The conference bridge, and the one bit that keeps a hiding person hidden.

Settled 2026-09-19: **the call is a server-side conference bridge, and the
resident's phone is not a leg of it by default.**

    conference bridge (backend)
     |- agents/caller        agent voice
     |- 911 operator         outbound leg
     |- resident             added on demand, never by default

This is not an optimisation. Putting the call on the resident's phone means iOS
owns the audio routing, and **call audio cannot be silenced below a floor**.
During a burglary a speaking phone gives away a hiding person's position.
Keeping them off the bridge by default means there is no audio stream to
suppress in the first place.

## The switch matrix

Every leg has an independent **send** and **receive**. Whisper is simply
send-only.

| Leg                | Send | Receive |
|--------------------|------|---------|
| `agents/caller`    | on   | on      |
| 911 operator       | on   | on      |
| resident, watching | off  | off     |
| resident, whisper  | **on** | **off** |
| resident, full     | on   | on      |

**Silence is enforced at the bridge, not on the device.** If audio is
transmitted to the phone, iOS decides how to play it and the floor is not zero.
If the bridge never sends it, there is nothing to play. That is the difference
between *muted*, which is a promise the phone makes, and *silent*, which is a
fact about what is on the wire.

Switching modes is flipping one bit server-side, so the app never has to be
trusted to stay quiet.

## Who may change the mode

**Automation may only ever move toward quieter. Going louder requires a human
hand.** Guessing wrong toward silence costs one tap; guessing wrong toward audio
makes a phone audible while someone is hiding. The two failures are not
comparable, so inference is trusted in one direction only, and that asymmetry is
enforced here rather than remembered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Leg(StrEnum):
    """Who is on the bridge."""

    CALLER = "agents/caller"
    OPERATOR = "911-operator"
    RESIDENT = "resident"


class ParticipationMode(StrEnum):
    """The resident's three modes, named by consequence in the UI, not by this jargon."""

    WATCHING = "watching"
    """Mic off, no audio out. Default for Burglary. Transcript only."""

    WHISPER = "whisper"
    """Mic open, nothing comes back. Hiding, but needs to be heard.

    The feature no existing product has, and the last thing to cut. Someone in a
    closet can say "he is in the kitchen, I am upstairs" and stay silent to the
    room around them. Typing cannot carry urgency or let a dispatcher hear a
    tone of voice; this can, without the phone making a sound.

    **Known cost, stated rather than hidden:** whisper is half-duplex. The
    resident speaks in real time but reads replies with a second or two of
    transcription lag, so it behaves more like a radio exchange than a phone
    call. That is the correct trade against a phone that reveals where someone
    is hiding, and they can switch to full voice the moment it is safe.
    """

    FULL_VOICE = "full_voice"
    """Mic open, audio out. Faint, Fire, or Burglary once safe."""


class ModeChangeRefused(RuntimeError):
    """Automation tried to make something louder. Only a human may do that."""


@dataclass(frozen=True)
class LegState:
    send: bool
    receive: bool


#: The matrix, as data. One table, so the app, the bridge and the tests cannot
#: disagree about what whisper mode means.
MODE_STATE: dict[ParticipationMode, LegState] = {
    ParticipationMode.WATCHING: LegState(send=False, receive=False),
    ParticipationMode.WHISPER: LegState(send=True, receive=False),
    ParticipationMode.FULL_VOICE: LegState(send=True, receive=True),
}


def _louder(before: ParticipationMode, after: ParticipationMode) -> bool:
    """Does this transition turn anything on that was off?

    Send and receive are considered independently. Watching to whisper turns the
    microphone on, which is louder toward the operator even though the phone
    stays silent, and opening a microphone to emergency services is a human
    decision.
    """
    a, b = MODE_STATE[before], MODE_STATE[after]
    return (b.send and not a.send) or (b.receive and not a.receive)


@dataclass
class Bridge:
    """Server-side call state. The app never holds any of this."""

    resident_mode: ParticipationMode = ParticipationMode.WATCHING
    agent_speaking: bool = True
    """False after a take-over. The agent goes silent mid-sentence, not at the
    end of its thought, and does not resume on its own."""

    operator_requested_resident: bool = False
    """The operator may request that the resident speak. Only the resident grants."""

    announcements: list[str] = field(default_factory=list)
    """Every transition, announced. See `announce_transition`."""

    def leg_state(self, leg: Leg) -> LegState:
        if leg is Leg.RESIDENT:
            return MODE_STATE[self.resident_mode]
        if leg is Leg.CALLER:
            # The agent's send follows take-over. Its receive never closes: it
            # keeps listening so it can keep feeding the app, which is what
            # makes it a teleprompter after the resident takes the microphone.
            return LegState(send=self.agent_speaking, receive=True)
        return LegState(send=True, receive=True)

    # ------------------------------------------------------------ mode changes

    def set_mode(self, mode: ParticipationMode, *, by_human: bool) -> str:
        """Change the resident's participation. Returns the announcement.

        Automation may move toward quieter freely. Anything that opens a
        microphone or a speaker requires `by_human=True`, and the refusal is an
        exception rather than a silent no-op: a mode change that appeared to
        work and did not is worse than one that failed loudly.
        """
        if mode is self.resident_mode:
            return ""
        if _louder(self.resident_mode, mode) and not by_human:
            raise ModeChangeRefused(
                f"automation may not move {self.resident_mode.value} -> {mode.value}: that "
                "turns on a microphone or a speaker. Automation may only ever move toward "
                "quieter; going louder requires a human hand."
            )
        before, self.resident_mode = self.resident_mode, mode
        announcement = self.announce_transition(before, mode)
        return announcement

    def request_resident(self) -> str:
        """The operator asks for the resident. It is a request, not a change.

        The operator requests; only the resident grants. An authority figure
        asking is exactly the pressure this system is built to not fold under.
        """
        self.operator_requested_resident = True
        return "The operator has asked to speak with you. You decide whether to join."

    # ------------------------------------------------------------- take-over

    def take_over(self) -> str:
        """The resident takes the microphone. Agent silent, mid-sentence.

        Held 1.5s in the app, consistent with every other risky control there,
        so nothing misfires from a stray palm or a pocket. Handing back is a
        separate deliberate action; this does not resume on its own.
        """
        self.agent_speaking = False
        return self.announce("The resident is taking over.")

    def yield_to_human(self) -> None:
        """Voice barge-in. Instant, not held, and the reason the button can be deliberate.

        **The agent never talks over a human.** Not the operator, not the
        resident. Either speaks, it yields. That one rule covers most of the
        failure modes on a live call, and it is why the deliberate 1.5s hold on
        the button is safe: there is already an instant path.
        """
        self.agent_speaking = False

    # ---------------------------------------------------------- announcements

    def announce(self, text: str) -> str:
        self.announcements.append(text)
        return text

    def announce_transition(self, before: ParticipationMode, after: ParticipationMode) -> str:
        """No unexplained voice changes on a call.

        This is a project whose threat model is impersonation. A dispatcher who
        hears the voice swap with no explanation has every reason to doubt the
        call, so every transition is narrated.
        """
        if after is ParticipationMode.WHISPER:
            # This line is real information, not politeness. It tells a
            # dispatcher there is an active threat, that the caller is
            # concealed, and how to speak to them. Silent 911 is a known hard
            # problem and Text-to-911 coverage is uneven.
            return self.announce(
                "The resident is joining but cannot hear you. They are hiding and will "
                "respond by voice only."
            )
        if after is ParticipationMode.FULL_VOICE:
            return self.announce("The resident is joining. They can hear you.")
        if before is not ParticipationMode.WATCHING:
            return self.announce("The resident has stepped back from the call.")
        return ""

    def leg_state_summary(self) -> str:
        """One line naming every leg's send and receive. What goes in the feed.

        Rendered from `leg_state` rather than from `resident_mode`, so the
        summary cannot disagree with the switch that is actually set.
        """
        parts = []
        for leg in Leg:
            state = self.leg_state(leg)
            parts.append(
                f"{leg.value}: send={'on' if state.send else 'off'} "
                f"recv={'on' if state.receive else 'off'}"
            )
        return "; ".join(parts)
