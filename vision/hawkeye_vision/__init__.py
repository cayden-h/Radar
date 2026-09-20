"""The camera path. Capture, lighting, tracking and recording.

Deliberately a separate package from `agents/`. It pulls in torch, ultralytics
and OpenCV, and the agents test suite must stay fast and must stay runnable on a
machine with no model weights. `agents/agents/vision/` imports from here; the
dependency points one way and never back.
"""

__version__ = "0.1.0"
