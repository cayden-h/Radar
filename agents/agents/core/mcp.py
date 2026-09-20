"""The `/mcp` endpoint: a second envelope over the same handlers as `/a2a`.

## Why this exists, having been deliberately deferred

`agents/CLAUDE.md` called MCP "a second adapter over the same handlers" that
"buys presentation rather than capability", and deferred it. That judgement was
wrong, and the thing that falsified it is the track owner's own verifier.

`agent.webmesh.ai verify_agent`, pointed at every one of our agents on
2026-09-20, returned `identity: pass` and `auth: pass` and exactly one warning:

    protocol  warning  speaks A2A v0.3.0; cross-talk needs the v0.3.0
                       compat adapter or MCP

with `mcp_capable: false` and `can_traveler_transact: "with-adapter"`. MCP is
named in his remedy line. It was the only dimension between us and a clean
verdict from the tool he wrote, so it stopped being presentation.

## Why not simply claim A2A 1.0 instead

That was the cheaper fix and it is not available to us honestly. We implement
JSON-RPC over `/a2a` with our own methods, not the A2A 1.0 surface, and the card
is the one artifact where an overclaim is signed, published and machine
checkable. `ans/CARD.md` measure 5 exists for this exact temptation. So
`protocolVersion` stays `0.3.0`, which is true, and we add the interface he
asked for, which is also true.

## One implementation, two doors

Every tool here calls `transport.observe` or an entry from the agent's own
`a2a_methods`. Nothing is reimplemented. An agent that answered "what do you
have right now" differently depending on which endpoint you asked would be
exactly the inconsistency the whole verification story is built to rule out,
and the shared call is what makes that structurally impossible rather than
merely intended.

**This endpoint signs the same claims and takes the same grants.** It is not a
read-only convenience surface: `shutter_open` over MCP moves a physical object
if and only if the grant verifies, by the same gate, because it is the same
function. The transport was never what authorized anything.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Response
from pydantic import ValidationError

from agents.core.base import Agent
from agents.core.signing import ClaimSigner
from agents.core.transport import METHOD_OBSERVE, ObserveParams, observe

logger = logging.getLogger(__name__)

#: Where the card says the MCP server is. One per agent, like `/a2a`.
MCP_PATH = "/mcp"

#: The MCP revision we implement. Matches what the reference agents publish, so
#: a client that works against `agent.webmesh.ai` works against us unchanged.
MCP_PROTOCOL_VERSION = "2025-03-26"


#: MCP tool names are an identifier grammar, not our dotted method names.
#: `hawkeye.observe` becomes `hawkeye_observe`, and the mapping is mechanical so
#: a method added to `a2a_methods` shows up here without being registered twice.
def _tool_name(method: str) -> str:
    return method.replace(".", "_")


_OBSERVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "audience": {
            "type": "string",
            "description": "The caller's ANSName. A claim addressed elsewhere is refused.",
        },
        "nonce": {
            "type": "string",
            "description": "The challenge this fan-out issues. The verifier holds it, "
            "so an agent cannot produce a usable claim unbidden.",
        },
        "incident_id": {"type": "string", "default": "steady-state"},
        "target": {
            "type": "string",
            "description": "Endpoint the possession proof must bind to.",
        },
    },
    "required": ["audience", "nonce", "target"],
}


def mcp_router(
    agent: Agent,
    signer: ClaimSigner,
    *,
    extra: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
) -> APIRouter:
    """The `/mcp` endpoint, over the same handlers `/a2a` serves."""
    router = APIRouter()
    extra = dict(extra or {})

    def tools() -> list[dict[str, Any]]:
        listed: list[dict[str, Any]] = [
            {
                "name": _tool_name(METHOD_OBSERVE),
                "description": (
                    f"{agent.identity.question} Returns this agent's current signed "
                    "observation, bound to the nonce you supply. It reports what the "
                    "agent already computed on its own tick; it does not run the "
                    "sensing logic on demand."
                ),
                "inputSchema": _OBSERVE_SCHEMA,
            }
        ]
        # An agent's own methods. Only `shutter` has any: it is the one agent
        # that takes an order rather than answering a question.
        listed += [
            {
                "name": _tool_name(method),
                "description": f"{agent.identity.name}: {method}. Same handler as /a2a.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            }
            for method in extra
        ]
        return listed

    def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One tool call to one MCP result. Errors are results, not exceptions.

        An MCP client distinguishes "the tool ran and said no" from "the server
        broke", and those must not share a representation here for the same
        reason a shutter refusal is a signed result rather than a JSON-RPC
        error: a refusal is an observation and it belongs in the record.
        """
        if name == _tool_name(METHOD_OBSERVE):
            try:
                params = ObserveParams.model_validate(arguments)
            except ValidationError as exc:
                return _text(
                    f"invalid params: {exc.error_count()} error(s)", is_error=True
                )
            return _text(observe(agent, signer, params).model_dump())

        for method, handler in extra.items():
            if name == _tool_name(method):
                return _text(handler(arguments))

        return _text(f"unknown tool {name!r}", is_error=True)

    @router.post(MCP_PATH)
    async def mcp(request: dict[str, Any]) -> Response:
        method = request.get("method")
        rpc_id = request.get("id")

        # A notification carries no id and takes no response body at all.
        if (
            rpc_id is None
            and isinstance(method, str)
            and method.startswith("notifications/")
        ):
            return Response(status_code=202)

        def ok(result: dict[str, Any]) -> Response:
            return _json({"jsonrpc": "2.0", "id": rpc_id, "result": result})

        def error(code: int, message: str) -> Response:
            return _json(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": code, "message": message},
                }
            )

        if method == "initialize":
            return ok(
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": agent.identity.name, "version": "0.1.0"},
                    "instructions": agent.identity.summary,
                }
            )
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": tools()})
        if method == "tools/call":
            params = request.get("params") or {}
            name = params.get("name")
            if not isinstance(name, str):
                return error(-32602, "tools/call requires a tool name")
            return ok(call(name, params.get("arguments") or {}))

        return error(-32601, f"unknown method {method!r}")

    return router


def _text(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    """An MCP tool result. Structured content alongside the text, not instead of it."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": body}],
        "isError": is_error,
    }
    if not isinstance(payload, str):
        result["structuredContent"] = payload
    return result


def _json(body: dict[str, Any]) -> Response:
    return Response(content=json.dumps(body), media_type="application/json")
