"""The agent-mesh transport, behind a protocol.

`MasterClient` is the seam between this service and `agents/master`. Two
implementations:

- `LiveMasterClient` talks to a real, internet-reachable agents/master.
- `SimulatedMasterClient` drives a scripted incident end to end with realistic
  timing and needs no hardware and no agents.

HAWKEYE_MODE picks one. Nothing above this package knows which is running, apart
from the `mode` field on GET /v1/hub, which is reported honestly rather than hidden.
"""

from hawkeye_backend.master.base import EventSink, MasterClient, MasterUnavailable
from hawkeye_backend.master.live import LiveMasterClient
from hawkeye_backend.master.simulated import SimulatedMasterClient

__all__ = [
    "EventSink",
    "LiveMasterClient",
    "MasterClient",
    "MasterUnavailable",
    "SimulatedMasterClient",
]
