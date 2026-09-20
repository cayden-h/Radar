"""The courier. Sends a sealed record to the responding department.

The last step of an incident, and the only one aimed at somebody who was never
on the call. A detective opening the email gets the whole bundle
`replay/export.py` builds - the record, the readable chain, the standalone
verifier and the README that says plainly what the record does and does not
prove - as one zip attachment.

## The address is reported, never trusted

The destination is supplied by the operator on a live phone call and read back
for confirmation. It is **not** a binding and must never be treated as one.
`docs/fraud-13.md` makes the general version of this argument: an agent that can
change where a response is sent is a swatting tool no matter how well the claims
upstream verify, which is why the dispatch address is bound at registration and
sealed.

The police email is the pivot's new instance of that problem and is handled
differently on purpose. It cannot be bound at registration, because which
department responds is not known until somebody answers the phone. So it is
carried with its provenance attached - `operator_supplied` or `configured` -
and recorded as what it is rather than promoted to authorization. Nothing
downstream reads it as permission to do anything.

## Failure is an outcome, not an exception

`send` returns a `CourierReceipt` for every path including the failures, and
raises only on a programming error. A send that failed must land in the record
as loudly as one that succeeded: a chain saying nothing is indistinguishable
from a chain saying the email went out, and the second is a lie a detective
would act on.

**An unverified sending domain is the failure this is built to catch.** Resend
accepts the send, returns a message id, and delivers nothing. The receipt is
`sent` and the inbox is empty. Nothing in an API response can distinguish that
case, so it is called out in the README of `app/backend` and checked once by
hand rather than papered over with a field that would be guessing.
"""

from __future__ import annotations

import logging
from base64 import b64encode
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

from hawkeye_backend.models.common import utc_now
from hawkeye_backend.models.incident import ReplayRecord
from hawkeye_backend.replay.export import build_export

logger = logging.getLogger(__name__)

RESEND_API = "https://api.resend.com"

#: How the destination was arrived at. Carried on the receipt and into the
#: chain, so a reader never has to infer it from context.
#:
#: `operator_supplied` is the real path: a 911 operator said it out loud and
#: `caller` read it back. `configured` is a static address from this service's
#: own settings, which is what a rehearsal and the auto-on-seal path use.
AddressProvenance = Literal["operator_supplied", "configured"]

#: Every terminal state of a send attempt.
#:
#: `skipped` is not a failure. No courier configured, or no address to send to,
#: is the ordinary case for a hub that is not part of a live deployment, and
#: conflating it with `failed` would train a reader to ignore failures.
Outcome = Literal["sent", "failed", "skipped"]


class CourierReceipt(BaseModel):
    """What happened when the bundle was handed off. One per attempt."""

    outcome: Outcome
    to: str = Field(default="", description="The destination. Empty when skipped for want of one.")
    provenance: AddressProvenance | None = Field(
        default=None,
        description=(
            "How the address was arrived at. Null only when there was no address. "
            "Recorded because the operator-supplied case is a human statement on a "
            "phone call, not a verified binding, and the record must not blur the two."
        ),
    )
    message_id: str = Field(
        default="",
        description=(
            "The provider's id for the message, when there is one. It proves the "
            "provider accepted the send. It does not prove delivery, and an "
            "unverified sending domain returns one while delivering nothing."
        ),
    )
    detail: str = Field(default="", description="Why, in one line. Always set on `failed`.")
    attachment_bytes: int = Field(default=0, ge=0)
    attachment_name: str = Field(default="")
    at: datetime = Field(default_factory=utc_now)

    @property
    def summary(self) -> str:
        """The one line that goes in the chain."""
        match self.outcome:
            case "sent":
                return f"Record sent to {self.to} ({self.provenance})"
            case "failed":
                where = self.to or "no destination"
                return f"Record NOT sent to {where}: {self.detail}"
            case _:
                return f"Record not sent: {self.detail}"


def bundle_name(record: ReplayRecord) -> str:
    """The attachment filename. Carries the incident id so two never collide."""
    return f"hawkeye-{record.incident_id}.zip"


@runtime_checkable
class Courier(Protocol):
    """Where a sealed record goes on its way out of the building."""

    async def send(
        self, record: ReplayRecord, *, to: str, provenance: AddressProvenance
    ) -> CourierReceipt: ...

    async def close(self) -> None: ...


class NullCourier:
    """Sends nothing, and says so in terms the chain can carry.

    The default. A hub with no courier configured is the normal case, and it
    must be distinguishable in the record from a hub whose send failed.
    """

    async def send(
        self, record: ReplayRecord, *, to: str, provenance: AddressProvenance
    ) -> CourierReceipt:
        logger.info("courier: not configured, %s was not sent", record.incident_id)
        return CourierReceipt(
            outcome="skipped",
            to=to,
            provenance=provenance if to else None,
            detail="no courier is configured on this hub",
        )

    async def close(self) -> None:
        return None


class ResendCourier:
    """Emails the bundle through the Resend API.

    `httpx` directly rather than the `resend` package, matching `TwilioSink`:
    the API is one JSON POST with a bearer token, `httpx` is already a
    dependency, and this service holds the line on adding dependencies it does
    not need.
    """

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._from = from_address
        # Generous relative to an HTTP POST, because the bundle is an
        # attachment and the alternative to waiting is a false `failed` on a
        # send that actually went out.
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        # Only close what we created; a caller that injected a client owns it.
        self._owns_client = client is None

    def _body(self, record: ReplayRecord, to: str, provenance: AddressProvenance) -> str:
        """The email itself. Plain text, because a detective's mail client is
        not a thing this project gets to have an opinion about.

        It states the address provenance in the body rather than only in the
        attachment. The person reading this decides whether to act on it, and
        "you gave us this address on the call" is the sentence that lets them
        notice if they did not.
        """
        sealed = record.sealed_at.isoformat() if record.sealed_at else "not sealed"
        origin = (
            "You gave this address to the caller during the call, and it was read "
            "back to you for confirmation."
            if provenance == "operator_supplied"
            else "This address is configured on the Hawk Eye hub, not supplied on the call."
        )
        return (
            f"Hawk Eye incident record {record.incident_id}\n"
            f"Sealed: {sealed}\n"
            f"Entries: {len(record.entries)}\n\n"
            f"{origin}\n\n"
            "The attached zip holds the full record, a readable copy of its hash "
            "chain, a standalone verifier that needs nothing but Python 3.8, and a "
            "README stating what the record proves and what it does not.\n\n"
            "Run the verifier before relying on any of it:\n\n"
            "    python3 verify.py record.json\n\n"
            "It prints INTACT, or names the first entry that does not match.\n\n"
            "This record is tamper-evident to whoever holds it. It has NOT been "
            "submitted to a transparency log, so it is not independently verifiable "
            "by a third party who does not already hold a copy. The README says so "
            "too, at greater length.\n"
        )

    async def send(
        self, record: ReplayRecord, *, to: str, provenance: AddressProvenance
    ) -> CourierReceipt:
        name = bundle_name(record)
        bundle = build_export(record, utc_now())
        payload = {
            "from": self._from,
            "to": [to],
            "subject": f"Hawk Eye incident record {record.incident_id}",
            "text": self._body(record, to, provenance),
            "attachments": [{"filename": name, "content": b64encode(bundle).decode("ascii")}],
        }

        def failed(detail: str) -> CourierReceipt:
            return CourierReceipt(
                outcome="failed",
                to=to,
                provenance=provenance,
                detail=detail,
                attachment_bytes=len(bundle),
                attachment_name=name,
            )

        try:
            resp = await self._client.post(
                f"{RESEND_API}/emails",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            logger.error("courier: could not reach resend for %s: %s", record.incident_id, exc)
            return failed(f"could not reach the mail provider: {exc}")

        if resp.status_code >= 400:
            # The status and the provider's own error name, never the body.
            # Resend echoes the request back on some errors, and the request
            # contains the destination address and the whole bundle.
            try:
                name_ = str(resp.json().get("name", ""))
            except ValueError:
                name_ = ""
            detail = f"the mail provider refused the send: HTTP {resp.status_code}"
            if name_:
                detail = f"{detail} ({name_})"
            logger.error("courier: %s for %s", detail, record.incident_id)
            return failed(detail)

        try:
            message_id = str(resp.json().get("id", ""))
        except ValueError:
            message_id = ""

        logger.info(
            "courier: sent %s to %s, %d bytes, message %s",
            record.incident_id, to, len(bundle), message_id or "(no id)",
        )
        return CourierReceipt(
            outcome="sent",
            to=to,
            provenance=provenance,
            message_id=message_id,
            attachment_bytes=len(bundle),
            attachment_name=name,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
