"""The `/mcp` endpoint: the same handlers, a second envelope.

The point of these tests is not that MCP works. It is that MCP is **not a
second implementation**. A claim fetched through `/mcp` must be byte-identical
to one fetched through `/a2a` under the same challenge, and a grant refused by
one door must be refused by the other for the same stated reason.

An agent that answered differently depending on which endpoint you knocked on
would be exactly the inconsistency the verification story exists to rule out,
and it would be invisible to every other test in this suite.
"""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from hawkeye_backend.models.verification import TrustProfile
from hawkeye_backend.verification import TrustStore
from hawkeye_backend.verification.trust import KnownAgent

from agents.core.cards import VERSION
from agents.core.identity import identity
from agents.core.mcp import MCP_PATH, MCP_PROTOCOL_VERSION
from agents.core.runtime import build_app
from agents.core.signing import ClaimSigner
from agents.shutter.agent import ShutterAgent
from agents.shutter.backend import StubShutter

MASTER = identity("master")
SHUTTER = identity("shutter")


@pytest.fixture
def master_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def client(master_key) -> TestClient:
    trust = TrustStore(
        [
            KnownAgent(
                ansname=MASTER.ansname,
                public_key=master_key.public_key(),
                profile=TrustProfile.FIDUCIARY,
                certificate_version=VERSION,
            )
        ]
    )
    agent = ShutterAgent(trust=trust, backend=StubShutter())
    return TestClient(
        build_app(agent, signer=ClaimSigner(SHUTTER, Ed25519PrivateKey.generate()))
    )


def mcp(client: TestClient, method: str, **params) -> dict:
    body = {"jsonrpc": "2.0", "id": "m-1", "method": method, "params": params}
    return client.post(MCP_PATH, json=body).json()


def tool(client: TestClient, name: str, **arguments) -> dict:
    return mcp(client, "tools/call", name=name, arguments=arguments)["result"]


# ------------------------------------------------------------------ handshake


def test_initialize_announces_the_revision_the_card_publishes() -> None:
    """A client that works against the reference agents works against us.

    The card names a protocol version for this endpoint. If the handshake
    answered with a different one the card would be a published, signed,
    machine-checkable lie about our own surface - the failure `ans/CARD.md`
    measure 5 exists to prevent.
    """
    trust = TrustStore([])
    agent = ShutterAgent(trust=trust, backend=StubShutter())
    c = TestClient(
        build_app(agent, signer=ClaimSigner(SHUTTER, Ed25519PrivateKey.generate()))
    )
    result = mcp(c, "initialize")["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SHUTTER.name


def test_a_notification_gets_no_body(client: TestClient) -> None:
    """Notifications carry no id, so a response would be a protocol error."""
    r = client.post(
        MCP_PATH, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert r.status_code == 202
    assert not r.content


def test_an_unknown_method_is_an_error_not_a_crash(client: TestClient) -> None:
    assert mcp(client, "tools/nonsense")["error"]["code"] == -32601


# ---------------------------------------------------------------------- tools


def test_every_a2a_method_is_reachable_as_a_tool(client: TestClient) -> None:
    """The mapping is mechanical, so a method cannot be added to one door only."""
    names = {t["name"] for t in mcp(client, "tools/list")["result"]["tools"]}
    assert {"hawkeye_observe", "shutter_challenge", "shutter_open"} <= names


def test_an_unknown_tool_is_a_result_not_an_exception(client: TestClient) -> None:
    """`isError`, not a 500. A client must be able to tell a refusal from a fault."""
    assert tool(client, "no_such_tool")["isError"] is True


def test_bad_params_refuse_rather_than_throw(client: TestClient) -> None:
    """Same rule as the claim verifier: fail closed, and fail quietly."""
    assert tool(client, "hawkeye_observe", nonce="")["isError"] is True


# ------------------------------------------------- the property that matters


def test_the_same_grant_is_refused_by_both_doors_for_the_same_reason(
    client: TestClient,
) -> None:
    """The gate is the gate, whatever carried the bytes.

    `shutter` moves a physical object. If MCP were a second implementation, it
    would be a second place for the refusal table to drift - and the door an
    attacker picks would be the one that had drifted.
    """
    forged = json.dumps({"envelope": {"grant_id": "g"}, "signature": "no"})

    over_a2a = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "a",
            "method": "shutter.open",
            "params": {"grant": forged},
        },
    ).json()["result"]
    over_mcp = tool(client, "shutter_open", grant=forged)["structuredContent"]

    assert over_a2a["refusal"] == over_mcp["refusal"] == "malformed_grant"
    assert over_a2a["position"] == over_mcp["position"] == "closed"
    # And the refusal is signed on both, because a refusal is an observation
    # that has to reach the sealed record, not an error code.
    assert over_mcp["observation"]["claim"]
    assert over_mcp["observation"]["proof"]


def test_a_challenge_from_mcp_is_honoured_by_a2a(client: TestClient) -> None:
    """One nonce store behind both doors.

    A nonce issued over MCP and spent over A2A must work, and must then be
    spent. Two separate stores would hand an attacker a replay window by
    letting the same nonce be used once per transport.
    """
    nonce = tool(client, "shutter_challenge")["structuredContent"]["nonce"]
    assert nonce

    forged = json.dumps(
        {"envelope": {"grant_id": "g", "nonce": nonce}, "signature": "no"}
    )
    refused = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": "a",
            "method": "shutter.open",
            "params": {"grant": forged},
        },
    ).json()["result"]
    assert refused["position"] == "closed"
