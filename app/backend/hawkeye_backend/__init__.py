"""Hawk Eye app-facing backend.

The iOS app never talks to the five agents directly. It talks to this service,
which talks to `agents/master`. That keeps the ANS-verified agent-to-agent mesh
separate from the human-facing surface.
"""

__version__ = "0.1.0"
