"""The two cards every agent publishes, built as artifacts rather than responses.

`ans/CARD.md` measure 2: the card is a **build artifact, not a response**.
`card_drift_watch` hashes the signed card and compares it against the previous
run, and drift without a re-registration event is a finding. A card assembled
per request will drift on its own - map ordering, a timestamp, a counter - and
hand a monitor a finding we earned by accident.

So: `scripts/build_cards.py` calls into here, writes bytes to disk, and the
runtime serves those bytes and nothing else. Nothing dynamic goes in a card.

Three of the ten measures are implemented here and the rest are deployment:

- **1, sign the card.** `sign_card` from `hawkeye_backend.verification.card`,
  which produces the JWS shape `fraud.webmesh.ai` uses, over the JCS
  canonicalization with `signatures` removed. One JCS implementation across all
  five agents, which is what `canonicalization_probe` is looking for.
- **4, attest the dispatch address without publishing it.** The card carries
  `sha256(salt || canonical_address)`; the salt and plaintext are sealed at
  registration and never served.
- **5, declare only what is enforced.** `x-security-note` says plainly what is
  not yet turned on, copied from the track owner's own card. A card that
  overclaims is a signed, published, machine-checkable lie sitting on the
  surface the judge inspects first.

Measure 7 is the one to hold in mind while editing: **nothing sensitive in
either card.** No resident names, no street address in plaintext, no room label
that identifies a person. `zone_3` is not a privacy leak; "Grandma's room" is.
"""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hawkeye_backend.verification.b64 import b64u_encode, key_thumbprint
from hawkeye_backend.verification.canonical import canonicalize
from hawkeye_backend.verification.card import AddressCommitment, card_fingerprint, sign_card

from agents.core.identity import DOMAIN, VERSION, AgentIdentity, Role

A2A_CARD_PATH = "/.well-known/agent-card.json"
A2A_CARD_ALIAS = "/.well-known/agent.json"
TRUST_CARD_PATH = "/.well-known/ans/trust-card.json"

# Copied from the track owner's own card, and so is the discipline behind it.
# Update this string the moment a hop actually starts enforcing mTLS; a stale
# version of this field is worse than not having it, because it is the field
# that claims to be the truthful one.
SECURITY_NOTE = (
    "The read-only surfaces of this agent are publicly accessible with no "
    "authentication required (noAuth). The ansIdentityCert scheme (mutual TLS, ANS "
    "private CA) is declared for agent-to-agent calls and is NOT currently enforced: "
    "the inter-agent transport is not yet wired as of this card version. The card "
    "accurately describes what is enforced."
)


def _skills(identity: AgentIdentity) -> list[dict[str, Any]]:
    return [
        {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "tags": sorted(skill.fields),
        }
        for skill in identity.skills
    ]


def _security(identity: AgentIdentity) -> dict[str, Any]:
    """Measure 6: `securitySchemes` must match reality, per role.

    Sensing agents should only ever accept `master`. Read-only surfaces we
    expose for a judge to poke at are `noAuth`, and they are declared as such.
    An agent that declares mTLS and accepts anonymous calls fails a live A2A
    probe from `verify_agent`, which reports the credential we actually required.
    """
    schemes: dict[str, Any] = {
        "noAuth": {"type": "noAuth", "description": "Read-only card and health surfaces."},
        "ansIdentityCert": {
            "type": "mutualTLS",
            "description": "ANS identity certificate, private CA. Chain in keys[].x5c of the trust card.",
        },
    }
    if identity.role is Role.SENSING:
        expected_caller = "agents/master only. This agent has no other legitimate caller."
    elif identity.slug == "master":
        expected_caller = "The five sensing agents inbound; caller, guidance and replay outbound."
    else:
        expected_caller = "agents/master."
    return {
        "securitySchemes": schemes,
        "securityRequirements": [{"ansIdentityCert": []}],
        "x-expected-caller": expected_caller,
    }


def build_a2a_card(
    identity: AgentIdentity,
    *,
    address_commitment: AddressCommitment | None = None,
) -> dict[str, Any]:
    """The A2A card. Capabilities, skills, `securitySchemes`.

    Everything in here is derived from `AgentIdentity`, which is the same object
    the running agent carries. That is deliberate: a card generated from the
    agent's own identity cannot describe a different agent than the one running,
    which is the drift a monitor is looking for.
    """
    card: dict[str, Any] = {
        "protocolVersion": "0.3.0",
        "name": identity.name,
        "description": identity.summary,
        "version": VERSION,
        "url": f"{identity.base_url}/a2a",
        "preferredTransport": "JSONRPC",
        "provider": {
            "organization": "Hawk Eye",
            "url": f"https://{DOMAIN}",
        },
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": identity.slug == "replay",
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": _skills(identity),
        **_security(identity),
        "x-security-note": SECURITY_NOTE,
        # ans/CLAUDE.md: our inference genuinely runs on the Pi, and interior
        # occupancy of a private home is about as sensitive as telemetry gets.
        # This is the strongest safety claim we can make honestly, and it is
        # true today rather than aspirational.
        "dataEgressPolicy": "LOCAL_ONLY",
        "safetySignals": {
            # The 2026 agentic list (ASI01-ASI10) is not yet an accepted enum
            # value upstream, so CUSTOM plus a standardUri is the honest
            # encoding. Worth raising with the track owner as a real, specific
            # observation rather than as a compliment.
            "guardrailCertification": {
                "standard": "CUSTOM",
                "standardUri": f"https://{DOMAIN}/docs/threat-landscape",
            },
            # No TEE exists. Scoring zero here is correct, and saying why is the
            # behaviour the Trust Vector's five independent scores ask for.
            "enclaveAttestation": None,
        },
        "x-hawkeye": {
            "tier": identity.tier,
            "role": identity.role.value,
            "question": identity.question,
            "recommendedProfileExpected": identity.profile.value,
            "consumes": [f"agents/{s}" for s in identity.consumes],
            # The honesty rule, on the published surface. An agent reading a
            # simulated input says so here, and it says so in every reading's
            # provenance, so the two cannot disagree.
            "simulatedInputs": list(identity.simulated_inputs),
            "mustNotClaim": list(identity.must_not_claim),
        },
    }
    if address_commitment is not None:
        card["x-hawkeye"]["dispatchAddressCommitment"] = address_commitment.card_fragment()
    return card


def build_trust_card(
    identity: AgentIdentity,
    *,
    public_key_b64: str,
    kid: str,
    agent_id: str,
    x5c: list[str] | None = None,
    transparency_receipt: str | None = None,
) -> dict[str, Any]:
    """The ANS card. Identity, keys, chain, stapled receipt.

    `transparencyReceipt` stapled rather than fetched is what lets a verifier
    reach Gold offline, using only the log's public key. On a live incident a
    hop that needs a network round trip to verify is a hop that can be starved,
    so the staple is a resilience property and not a convenience.

    `x5c` and the receipt are None until `ans/` has a registration. They are
    serialized as null rather than omitted so the card's shape does not change
    when they arrive - a key set appearing is a re-registration, a key
    *structure* appearing is gratuitous drift.
    """
    return {
        "ansName": identity.ansname,
        "version": VERSION,
        "agentHost": identity.host,
        "agentId": agent_id,
        "endpoints": [
            {
                "protocol": "A2A",
                "agentUrl": f"{identity.base_url}/a2a",
                "metaDataUrl": f"{identity.base_url}{A2A_CARD_PATH}",
            }
        ],
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": public_key_b64,
                "use": "sig",
                "kid": kid,
                "x5c": x5c,
            }
        ],
        "transparencyReceipt": transparency_receipt,
        "botProfile": {
            "client_name": identity.name,
            "trigger": "agent",
            "purpose": identity.question,
        },
    }


def sign(card: dict[str, Any], key: Ed25519PrivateKey, identity: AgentIdentity) -> dict[str, Any]:
    """Sign a card with the JWS shape the reference cards use.

    `jku` points at our own trust card and `kid` matches the `keys[].kid` there,
    so a verifier that has the card can find the key without being told where.
    """
    public = key.public_key()
    return sign_card(
        card,
        key,
        trust_card_url=f"{identity.base_url}{TRUST_CARD_PATH}",
        kid=key_thumbprint(public),
    )


def serialize(card: dict[str, Any]) -> bytes:
    """Card to bytes, canonically. These bytes are what gets served.

    JCS, the same implementation the claim envelope uses. Two agents serializing
    the same value differently produce signature mismatches that look exactly
    like tampering, and that is far likelier to bite us as an ordinary bug than
    as an attack.
    """
    return canonicalize(card)


def fingerprint(card: dict[str, Any]) -> str:
    """The `card_drift_watch` analogue. Hashes the canonical form.

    Reformatting is not drift. A changed value is.
    """
    return card_fingerprint(card)


def public_key_b64(key: Ed25519PrivateKey) -> str:
    """Raw Ed25519 public key, base64url unpadded, for the `x` member."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return b64u_encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
