from __future__ import annotations

import pytest
from hawkeye_backend.master.base import AutonomousDialRefused, MasterClient
from hawkeye_backend.master.simulated import SimulatedMasterClient
from hawkeye_backend.models.incident import Incident, IncidentStatus, IncidentType, RaisedBy


def _incident(raised_by: RaisedBy) -> Incident:
    return Incident(
        incident_id="inc-001",
        site_id="site-demo-01",
        incident_type=IncidentType.BURGLARY,
        status=IncidentStatus.RAISED,
        raised_by=raised_by,
        address="1872 Ridgeview Lane, Blacksburg VA 24060",
    )


@pytest.mark.asyncio
async def test_start_call_refuses_a_system_raised_incident():
    """The structural gate: caller never dials without a human tap, even in
    simulated mode, so a bug can't quietly skip the one rule the whole
    project is built around."""
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    with pytest.raises(AutonomousDialRefused):
        await client.start_call(_incident(RaisedBy.SYSTEM))


@pytest.mark.asyncio
async def test_start_call_accepts_a_user_raised_incident():
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    await client.start_call(_incident(RaisedBy.USER))  # must not raise


@pytest.mark.asyncio
async def test_set_participation_mode_returns_an_announcement():
    client: MasterClient = SimulatedMasterClient(
        site_id="site-demo-01", address="1872 Ridgeview Lane, Blacksburg VA 24060"
    )
    await client.start_call(_incident(RaisedBy.USER))
    announcement = await client.set_participation_mode("inc-001", "whisper", by_human=True)
    assert isinstance(announcement, str)
    assert len(announcement) > 0
