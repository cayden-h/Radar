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

    # Origin of this app-facing edge service, as `agents/caller` reaches it to
    # POST the operator-supplied police email to `/v1/incident/{id}/courier`.
    # The `caller` process runs separately from the hub, so it needs the hub's
    # own address rather than assuming co-location. Just the origin: the courier
    # client appends the `/v1/...` path itself.
    edge_base_url: str = "http://127.0.0.1:8787"

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

    # The replay archive. Separate from `store_backend` on purpose.
    #
    # `store_backend` decides where the hub's whole working state lives, which
    # is on the incident path: a motion claim has to reach a wrist in about
    # three seconds and there is no room in that budget for a round trip to
    # Atlas. This decides only where a *sealed* record goes, which happens once,
    # when a 911 call ends, and is the one piece whose entire purpose is to be
    # read after the process that wrote it is gone.
    #
    # So the hackathon path is `store_backend=memory` with
    # `replay_archive=mongodb`, and that combination is deliberate rather than
    # half-finished.
    replay_archive: Literal["off", "mongodb"] = "off"

    # The edge link. The Pi holds the camera and the servo and dials this
    # process; nothing here ever dials the Pi. It is headless and its lease
    # moves, so the only address in this system is this hub's own.
    #
    # The token is not optional theatre. Without it any host on the same WiFi
    # could inject frames into the camera feed, and the camera feed is the one
    # surface a human is asked to believe.
    edge_token: SecretStr = SecretStr("")

    # Frames older than this are not presentable as current. See
    # hawkeye_backend/edge/camera.py.
    camera_stale_after_s: float = 3.0

    # How often a thumbnail is pushed onto the event stream for the watch.
    # Deliberately slow: it is a wrist, not a monitor.
    camera_thumbnail_interval_s: float = 1.0

    # Long edge of that thumbnail, in pixels.
    camera_thumbnail_long_edge: int = 320

    # The room this one fixed camera covers. One camera sees one room, and every
    # vision claim carries that scope rather than implying it has none. Authored,
    # not sensed: the system does not map walls and cannot, because walls are the
    # static baseline the radio subtracts to see motion.
    camera_room: str = "Living room"

    # How long to wait for a shutter to answer a grant before reporting the
    # position unknown. A grant's own TTL is ten seconds, so waiting longer than
    # that is waiting for something that has already expired.
    shutter_timeout_s: float = 8.0

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

    # Twilio Voice + ElevenLabs, for the call bridge. All of these plus the SMS
    # four above are required for a real call. Missing any one reads as unconfigured
    # and the call bridge refuses to place a real call rather than half-placing one.
    twilio_voice_number: str = ""
    twilio_conference_app_sid: str = ""
    mock_911_number: str = ""
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_voice_id: str = ""
    public_base_url: str = ""

    # Twilio Voice Access Tokens, for the app's own leg of the conference (the
    # resident's phone joining as a WebRTC leg; see app/CLAUDE.md's mode table).
    # A separate credential pair from the REST credentials above: minting a
    # client Access Token needs an API Key/Secret, not the account auth token,
    # and a TwiML Application SID to route the connecting client into.
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: SecretStr = SecretStr("")
    twilio_application_sid: str = ""

    # Retell AI, the real call transport (Twilio Voice is paywalled and now
    # dormant). All three of api key, from number, and websocket secret are
    # required for a real call; missing any one reads as unconfigured, the same
    # all-or-nothing rule as the Twilio blocks above. The operator's phone is
    # `mock_911_number`, reused - it is exactly the fake 911 operator's phone.
    # ElevenLabs stays: it is configured on the Retell agent as the TTS voice,
    # so `elevenlabs_voice_id` above is still consumed.
    retell_api_key: SecretStr = SecretStr("")
    retell_from_number: str = ""
    retell_agent_id: str = ""
    retell_websocket_secret: str = ""
    # Which call transport the caller agent wires at startup: retell | twilio |
    # simulated. Default retell; twilio is retained but dormant.
    call_transport: str = "retell"

    # Replay recording. The record opens on a human tap and seals when the 911
    # call ends; these bound what goes into it in between.
    #
    # State ticks run at roughly 2 Hz during an incident, and a record that kept
    # every one of them would be mostly frames. One frame every half second is
    # plenty to animate the map, and a frame whose presence states changed is
    # always kept regardless of this interval, so nothing important is thrown
    # away to save space.
    replay_frame_interval_s: float = 0.5

    # Ceiling on entries per record. On reaching it the recorder stops recording
    # frames and says so on the record; it never stops recording claims,
    # discards, transcript or instructions. Those are the point, and they are
    # bounded by the length of a phone call rather than by a tick rate.
    replay_max_entries: int = 10000

    # Serve the replay console at /replay. Off in live mode would be a
    # deployment decision, not a code one, so it is a flag rather than a
    # condition on `mode`.
    replay_site_enabled: bool = True

    # Serve the live console at /live. Same kind of decision as the replay
    # console, and a sharper one: this page carries Start Incident, which is the
    # only control that releases `caller` to dial 911, plus shutter open and
    # close. It is served unauthenticated to whatever LAN the hub is on, so
    # being able to turn it off is not optional.
    live_site_enabled: bool = True

    # The courier: who sends a sealed record to the responding department.
    # Off by default and for the same reason the replay archive is - a hub that
    # is not part of a live deployment must not mail anybody - but the stakes
    # here are higher than durability. An accidental send during development
    # puts an incident record in a stranger's inbox and cannot be recalled.
    courier: Literal["off", "resend"] = "off"

    # SecretStr so the key cannot reach a log, a traceback, or a repr.
    resend_api_key: SecretStr = SecretStr("")

    # The From address. Must be on a domain verified in the Resend dashboard.
    # **An unverified domain accepts the send, returns a message id, and
    # delivers nothing**, so the chain records a success that did not happen.
    # Nothing in an API response distinguishes that case; verify by hand, once.
    courier_from: str = "Hawk Eye <hawkeye@cayden.tech>"

    # Fallback destination for the automatic send on seal. The real path is an
    # address a 911 operator gives on the call, which arrives on the request
    # and is recorded as `operator_supplied`; this one is recorded as
    # `configured`, and the difference is carried into the chain rather than
    # flattened. Empty means the automatic send is skipped, and the record says
    # it was skipped for want of an address.
    courier_to: str = ""

    # Where /motion sends a browser. The RSSI motion detector in
    # wifi-rssi-motion-template/ is a separate, deliberately self-contained
    # process with its own server and its own page, so the hub does not embed
    # it or proxy it - it just knows the address and hands the browser over.
    # Set it empty to drop the /motion route entirely.
    motion_console_url: str = "http://localhost:8766/index.html"

    # Used to render the local time in an SMS. The demo home is in Blacksburg.
    site_timezone: str = "America/New_York"

    host: str = "0.0.0.0"
    port: int = 8787

    @property
    def caller_ansname(self) -> str:
        """The ANSName of the agent that speaks to the operator.

        Derived from master's rather than configured separately, because the two
        are siblings under one registered domain and letting them drift apart in
        config is a way to print the wrong identity on a sealed record.
        """
        return self.master_ansname.replace("master.", "caller.", 1)

    @property
    def edge_configured(self) -> bool:
        """True when the edge link can actually authenticate anyone.

        An empty token means the link refuses every connection rather than
        accepting every connection. A camera feed that anyone on the WiFi can
        write to is worse than no camera feed.
        """
        return bool(self.edge_token.get_secret_value())

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

    @property
    def twilio_voice_configured(self) -> bool:
        """True only when every value needed for a voice call is present."""
        return all((
            self.twilio_account_sid,
            self.twilio_auth_token.get_secret_value(),
            self.twilio_voice_number,
            self.twilio_conference_app_sid,
            self.mock_911_number,
            self.elevenlabs_api_key.get_secret_value(),
            self.elevenlabs_voice_id,
            self.public_base_url,
        ))

    @property
    def twilio_call_token_configured(self) -> bool:
        """True only when every value needed to mint a client Access Token is present."""
        return all((
            self.twilio_account_sid,
            self.twilio_api_key_sid,
            self.twilio_api_key_secret.get_secret_value(),
            self.twilio_application_sid,
        ))

    @property
    def retell_configured(self) -> bool:
        return all(
            [
                self.retell_api_key.get_secret_value(),
                self.retell_from_number,
                self.retell_websocket_secret,
            ]
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
