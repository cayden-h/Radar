"""Bonjour advertisement, so the phone can find this hub without being told where it is.

The iOS Connect screen browses `_hawkeye._tcp` and has no manual address field.
Until this module existed nothing advertised that service, so `useMocks = false`
left the app searching forever **and showing no error**, because an empty list is
what "no hub found" correctly looks like. That failure is indistinguishable from
a hub that is down, a phone on the wrong SSID, and an access point with client
isolation on, which is three wrong diagnoses for one symptom.

## The address goes in the TXT record, deliberately

The obvious design is to let the phone resolve the service instance to an A
record. It does not work: `URLSession` takes a hostname, and
`Radar._hawkeye._tcp.local.` is a *service instance name*, not a hostname.
Handing one to `URLSession` fails to resolve rather than returning anything the
app can report. `LiveHawkEyeClient.resolveBaseURL` was written that way and could
never have connected.

So this publishes `host` and `port` in the TXT record and the app builds its base
URL from those. One round trip, no second resolution step, and the address the
app dials is the one this process actually bound.

## Never fatal

A hub that cannot advertise still serves every route. The consoles work, the edge
link works, and a phone pointed at the address by hand works. Advertisement is a
convenience for discovery, so failing to register logs a warning and the hub comes
up regardless - the same rule the replay archive follows in `main.py`.
"""

from __future__ import annotations

import asyncio
import logging
import socket

from hawkeye_backend.config import Settings

logger = logging.getLogger(__name__)

#: The service type the iOS app browses. Must match `Config.bonjourServiceType`
#: and the `NSBonjourServices` entry in the app's Info.plist, all three, or
#: `NWBrowser` returns nothing and fails silently.
SERVICE_TYPE = "_hawkeye._tcp.local."


def primary_lan_address() -> str | None:
    """This machine's address on the LAN the phone is also on.

    `socket.gethostbyname(gethostname())` is the tempting one-liner and it is
    wrong on macOS: it commonly answers `127.0.0.1`, which advertises a loopback
    address to every phone on the network and produces a hub that is discovered
    and then refuses every connection.

    Opening a UDP socket toward a public address picks the interface the routing
    table would actually use, without sending a packet, which is the same
    interface the phone's traffic will arrive on.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Never transmitted. connect() on a UDP socket only sets the peer, and
        # that is enough for the kernel to choose a source interface.
        probe.connect(("8.8.8.8", 80))
        address: str = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    if address.startswith("127."):
        return None
    return address


class HubAdvertiser:
    """Registers this hub as `_hawkeye._tcp` for as long as the process lives."""

    def __init__(self, settings: Settings, port: int) -> None:
        self._settings = settings
        self._port = port
        self._zeroconf = None
        self._info = None

    async def start(self) -> None:
        """Register the service. Logs and returns on any failure; never raises."""
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            logger.warning(
                "bonjour: python-zeroconf is not installed, so this hub will not be "
                "discoverable. The app's Connect screen will search and find nothing. "
                'Install it with `pip install -e ".[discovery]"`.'
            )
            return

        address = primary_lan_address()
        if address is None:
            logger.warning(
                "bonjour: no non-loopback address found, so nothing was advertised. "
                "A phone cannot reach this hub at 127.0.0.1."
            )
            return

        # The instance name is what the app shows and what it uses as the hub's
        # identity in `PairingStore`, so it is the human-facing name rather than
        # the site id.
        instance = f"{self._settings.hub_name}.{SERVICE_TYPE}"

        # `host` and `port` are what the app dials; see the module docstring for
        # why the address is carried here rather than resolved. `ans` is checked
        # against `GET /v1/hub`'s `hub_ansname` on connect, and a mismatch aborts
        # the connection - so publishing a stale value here reads to the resident
        # as an identity mismatch, which is exactly what it is.
        properties = {
            "name": self._settings.hub_name,
            "ans": self._settings.hub_ansname,
            "host": address,
            "port": str(self._port),
            "site": self._settings.site_id,
            "mode": self._settings.mode,
        }

        try:
            self._zeroconf = AsyncZeroconf()
            self._info = ServiceInfo(
                SERVICE_TYPE,
                instance,
                addresses=[socket.inet_aton(address)],
                port=self._port,
                properties=properties,
                server=f"{socket.gethostname().split('.')[0]}.local.",
            )
            await self._zeroconf.async_register_service(self._info)
        except Exception as exc:
            logger.warning("bonjour: could not advertise this hub (%s)", exc)
            await self.stop()
            return

        logger.info(
            "bonjour: advertising %r on %s:%s as %s",
            self._settings.hub_name,
            address,
            self._port,
            self._settings.hub_ansname,
        )

    async def stop(self) -> None:
        """Withdraw the advertisement.

        Worth doing rather than leaving to process exit: an unregistered service
        lingers in other devices' caches, and a phone that finds a hub which is
        no longer listening is a worse failure than one that finds nothing.
        """
        if self._zeroconf is None:
            return
        try:
            if self._info is not None:
                await asyncio.wait_for(
                    self._zeroconf.async_unregister_service(self._info), timeout=2
                )
            await asyncio.wait_for(self._zeroconf.async_close(), timeout=2)
        except Exception as exc:
            logger.debug("bonjour: withdrawal was not clean (%s)", exc)
        finally:
            self._zeroconf = None
            self._info = None
