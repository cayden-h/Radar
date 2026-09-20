"""agents/presence - something moved, and which room it moved in.

Tier 1. The first link in the chain: its perturbation claim is what `master`
turns into a shutter grant, and nothing else in the system can start an
incident.
"""

from agents.presence.agent import PresenceAgent

__all__ = ["PresenceAgent"]
