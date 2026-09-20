"""The Pi-to-Mac edge link.

The Pi holds the camera and the servo and nothing else. It dials this process
over one websocket, pushes JPEG frames up it, and receives shutter grants back
down it.

The Pi dials out rather than serving, so nothing here ever has to discover the
Pi's address. It is a headless box whose DHCP lease moves every time the network
changes, and the only two things it needs to know about the world are a WiFi
password and this hub's mDNS name.
"""

from hawkeye_backend.edge.camera import LiveCamera
from hawkeye_backend.edge.wire import (
    EdgeAttestation,
    EdgeChallenge,
    EdgeChallengeRequest,
    EdgeError,
    EdgeFrameHeader,
    EdgeGrant,
    EdgeHello,
    EdgeMessage,
    decode_edge_message,
)

__all__ = [
    "EdgeAttestation",
    "EdgeChallenge",
    "EdgeChallengeRequest",
    "EdgeError",
    "EdgeFrameHeader",
    "EdgeGrant",
    "EdgeHello",
    "EdgeMessage",
    "LiveCamera",
    "decode_edge_message",
]
