"""Runtime configuration.

One env var decides whether this service talks to a real agent mesh or drives a
scripted incident with zero hardware and zero agents up: HAWKEYE_MODE.
"""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["simulated", "live"]


class Settings(BaseSettings):
    """Process configuration, read from the environment.

    Every field is prefixed `HAWKEYE_` in the environment, so `HAWKEYE_MODE=live`
    sets `mode`.
    """

    model_config = SettingsConfigDict(env_prefix="HAWKEYE_", env_file=".env", extra="ignore")

    # The one switch. "simulated" needs nothing but this process.
    mode: Mode = "simulated"

    # Identity of this hub, surfaced on GET /v1/hub.
    hub_name: str = "Hawk Eye Hub"
    site_id: str = "site-demo-01"

    # TODO(ans): replace with the ANSName actually registered through GoDaddy for
    # this hub once ans/ has a domain. Question to answer: is the hub itself an
    # ANS-registered agent, or does it inherit the identity of agents/master and
    # merely quote it? Root CLAUDE.md says every machine hop behind the human
    # boundary is ANS-verified; the app<->hub hop is a human-facing hop, so the
    # working assumption here is that the hub quotes master's anchor rather than
    # holding its own. Confirm against ans-registry before printing this on stage.
    hub_ansname: str = "hub.hawkeye.invalid"
    master_ansname: str = "master.hawkeye.invalid"

    # Street address the incident is anchored to. One resident, hardcoded, per app/CLAUDE.md.
    site_address: str = "1872 Ridgeview Lane, Blacksburg VA 24060"

    # Live mode only. Base URL of agents/master.
    master_base_url: str = "http://127.0.0.1:8900"
    master_timeout_s: float = 5.0

    # Simulated mode only. Multiply every scripted delay; 0.25 makes the demo run
    # four times faster for a rehearsal, 1.0 is realistic timing.
    sim_speed: float = 1.0

    # Start the scripted incident automatically on boot, so scripts/demo.sh can
    # just start the server and watch. When false the script waits for
    # POST /v1/demo/run.
    sim_autostart: bool = False

    # Storage seam. "memory" is the hackathon path; "mongodb" is the MongoDB Atlas
    # sponsor track and is not implemented yet (see store.py).
    store_backend: Literal["memory", "mongodb"] = "memory"
    mongodb_uri: str = ""
    mongodb_database: str = "hawkeye"

    # Notices. A notice is information the resident acts on, never a dispatch.
    # The hold before an unexpected presence becomes one; see
    # hawkeye_backend/notices/detector.py for why it is not zero.
    notice_hold_s: float = 5.0

    # How long a presence must be absent before its notice mark lapses, so a
    # genuine re-entry hours later notifies again while a brief CSI dropout
    # behind a wall does not.
    notice_forget_after_s: float = 900.0

    # Twilio, for the SMS sink. All four or none: three out of four is a
    # misconfiguration and is treated as unconfigured rather than as a partial
    # feature that fails at the moment it matters.
    #
    # Trial accounts only send to numbers verified in the Twilio console, and
    # prefix every message with "Sent from your Twilio trial account".
    twilio_account_sid: str = ""
    # SecretStr so the token cannot reach a log, a traceback, or a repr by
    # accident. Read it with .get_secret_value() at the one point of use.
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_from_number: str = ""
    twilio_to_number: str = ""

    # Rate limits on the SMS sink. A rehearsal loop must not be able to send
    # fifty texts, and a bug in the trigger must not burn the trial credit.
    twilio_min_interval_s: float = 60.0
    twilio_max_per_instance: int = 5

    # Used to render the local time in an SMS. The demo home is in Blacksburg.
    site_timezone: str = "America/New_York"

    host: str = "0.0.0.0"
    port: int = 8787

    @property
    def twilio_configured(self) -> bool:
        """True only when every value needed to send is present."""
        return all(
            (
                self.twilio_account_sid,
                self.twilio_auth_token.get_secret_value(),
                self.twilio_from_number,
                self.twilio_to_number,
            )
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Drop the cached settings. Tests only."""
    global _settings
    _settings = None
