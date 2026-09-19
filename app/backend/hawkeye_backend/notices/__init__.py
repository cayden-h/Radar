"""Notices: the inform step of "detect, classify and inform".

A notice is information a person acts on. It is not an incident and it does not
dial. See `hawkeye_backend/models/notice.py`.
"""

from hawkeye_backend.notices.detector import NoticeDetector

__all__ = ["NoticeDetector"]
