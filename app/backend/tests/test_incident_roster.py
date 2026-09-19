"""The incident roster. Two types, both raised by a human."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hawkeye_backend.models.incident import IncidentType

# `agents` lives beside `app/backend` in the repo, and the guidance-coverage test
# below reads its protocol table. Nothing else here needs it.
_AGENTS_ROOT = Path(__file__).resolve().parents[3] / "agents"
if _AGENTS_ROOT.is_dir() and str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))


def test_the_roster_is_burglary_and_fire():
    assert {t.value for t in IncidentType} == {"burglary", "fire"}


def test_faint_is_gone():
    assert not hasattr(IncidentType, "FAINT")


def test_every_incident_type_has_resident_guidance():
    """No incident type may reach a resident with no instructions.

    This lives here rather than with the guidance change because it asserts
    full coverage of the enum, and the enum only becomes correct in this task.
    """
    try:
        from agents.caller.guidance import PROTOCOL
    except ImportError as exc:  # pragma: no cover - only when agents is absent
        pytest.skip(f"agents package not importable: {exc}")

    for incident_type in IncidentType:
        assert PROTOCOL.get(incident_type), incident_type

