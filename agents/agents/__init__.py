"""The nine ANS-registered agents behind Hawk Eye.

One subpackage per agent, named exactly as `agents/CLAUDE.md` names it, so
`agents/biometrics` in the prose is `agents.biometrics` in the code and there is
no translation table to keep current.

Shared machinery lives in `agents.core`. Read `agents/CLAUDE.md` first, then
`docs/research/agent-briefs.md` for the agent you are about to touch.

**What is deliberately not here yet: the wire.** Every agent produces and
consumes `AgentObservation`, and the ports in `agents.core.ports` are where a
transport gets plugged in. Nothing in this package signs, sends, or fetches an
observation from another agent. That is the next conversation, and keeping it
out of the first one is what stops the domain logic from being shaped by a
transport decision nobody has made yet.
"""
