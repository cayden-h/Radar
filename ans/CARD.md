# Agent cards: what ours must carry, and how we harden them

Written 2026-09-19, from the live cards at `webmesh.ai` and the ANS-5 / ANS-6 specs.
Read `ans/CLAUDE.md` first. The threat reasoning behind this file is in `docs/threat-landscape.md`.

## Correct one assumption before reading further

**The 13-attack battery at `fraud.webmesh.ai` cannot be pointed at our agents.**

Verified directly against its MCP endpoint on 2026-09-19. It exposes 16 tools, and `run_battery` plus every one of the 13 attack tools takes **no target parameter**:

```
underpay_valid_sig         props=[]
quote_swap_attack          props=[]
wrong_audience_attack      props=[]
...
run_battery                props=[]
```

Only three tools accept arguments at all, and those are `captured_mandate`, `captured_dpop_proof`, and `quote_id`. The target is hardwired to `supplier.webmesh.ai`.
Its card says so in the first line: it runs its attacks "against the real Supplier."

So nobody is going to aim thirteen attacks at us, and any plan that assumes otherwise wastes the weekend building a target for a gun that does not traverse.
The battery is a **reference implementation of a threat model**, not a scanner. Its value to us is the checklist in `docs/fraud-13.md`, and that value is real.

### What will actually be pointed at us

`agent.webmesh.ai`, the track owner's own verifier. It exposes:

```
verify_agent   props=['agent_host', 'environment']
```

It takes an **arbitrary hostname** and produces a `compatibility_verdict` plus an identity report, built from DNS records, DNSSEC signatures, ANS Transparency Log proof, and **the published agent card**. It also sends a live A2A message and reports what credential the agent required.

That is the thing to prepare for, and it makes the card the surface actually under test.
The instinct to harden the card is right. The reason is `verify_agent`, not the battery.

**The demo beat this unlocks is better than the one we were planning.** On stage, point the judge's own verification agent at our agents, live, and let his software say we are who we claim. That is a third party he trusts confirming us in front of him, and it costs us nothing but getting the cards right.

`get_encounter_history(agent_host)` also means his verifier **remembers**. Anything we publish gets recorded in a store we do not control, so a card we later fix does not erase the card he already saw. Get it right before the first fetch, not after.

## The two cards

Every agent publishes both. Model them on `agent.webmesh.ai`, which is the reference we were given.

| Path | What it is |
|---|---|
| `/.well-known/agent-card.json` | The A2A card. Capabilities, skills, `securitySchemes`. Also served at `/.well-known/agent.json`. |
| `/.well-known/ans/trust-card.json` | The ANS card. Identity, keys, x5c chain, stapled SCITT receipt. |

The trust card is small. This is the live one from `agent.webmesh.ai`, trimmed:

```json
{
  "ansName": "ans://v1.0.13.agent.webmesh.ai",
  "version": "1.0.13",
  "agentHost": "agent.webmesh.ai",
  "endpoints": [{ "protocol": "A2A", "agentUrl": "...", "metaDataUrl": ".../agent-card.json" }],
  "keys": [{ "kty": "OKP", "crv": "Ed25519", "x": "...", "use": "sig", "kid": "...", "x5c": ["MII..."] }],
  "agentId": "de02d013-...",
  "transparencyReceipt": "0oRYNKQBJgREyeL1hBk...",
  "botProfile": { "client_name": "...", "expected-user-agent": "...", "trigger": "fetcher", "purpose": "..." }
}
```

Three things to notice, because each is a requirement in disguise:

- **The version is inside the name.** `ans://v1.0.13.agent.webmesh.ai`, and the same string appears in the certificate SAN. That is what "version-bound" means concretely. Ship a code change, bump the version, re-register, get a new certificate.
- **`transparencyReceipt` is stapled.** A verifier reaches Gold tier offline, using only the log's public key, with no call to the RA. Staple ours.
- **`metaDataUrl` points at the A2A card, and its hash is sealed at registration.** The AIM re-fetches it and compares. If that document is not byte-stable, we generate a `Mismatch` finding against ourselves.

## The ten measures

Ordered by what they cost. The first four are the ones that matter.

### 1. Sign the agent card

He does, and it is the single highest-value measure. From `fraud.webmesh.ai`:

```json
"signatures": [{
  "protected": "eyJhbGciOiJFZERTQSIsImprdSI6Imh0dHBzOi8vZnJhdWQud2VibWVzaC5haS8ud2VsbC1rbm93bi9hbnMvdHJ1c3QtY2FyZC5qc29uIiwia2lkIjoiNF9SZ2RPNFB6SlpUSFZNZXktWmJhWFRWUDdMT0M0Zkxrc2JuOGQ4YW5EZyIsInR5cCI6ImFnZW50LWNhcmQrandzIn0",
  "signature": "8EvYOuzuivCvdIW7isnoE-FAmEE3PjQTW1AvijcVds-..."
}]
```

Decoded, the protected header is:

```json
{ "alg": "EdDSA",
  "jku": "https://fraud.webmesh.ai/.well-known/ans/trust-card.json",
  "kid": "4_RgdO4PzJZTHVMey-ZbaXTVP7LOC4fLksbn8d8anDg",
  "typ": "agent-card+jws" }
```

Copy this exactly: `alg` EdDSA, `typ` `agent-card+jws`, `jku` pointing at our own trust card, `kid` matching the `keys[].kid` there.
The signing payload is the card **JCS-canonicalized with `signatures` removed**.

That last detail is where `canonicalization_probe` lives. Pick one JCS implementation and use it in all five agents. Two agents serializing the same value differently produce signature mismatches that look exactly like tampering, and that is far more likely to bite us as an ordinary bug than as an attack.

### 2. Make the card byte-stable

`card_drift_watch` hashes the signed card and compares against the previous run. Drift without a re-registration event is a finding.

So the card is a **build artifact, not a response**. Generate it at build time, write it to disk, serve the bytes.

Nothing dynamic goes in it. No timestamps, no uptime counters, no request IDs, no "last seen", no map iteration order that varies between processes. Serialize with sorted keys. Serve with a strong `ETag` and let it cache.

A card assembled per request will drift on its own and hand a monitor a finding we earned by accident.

### 3. Bump the version and re-register on every change

Card content change, code change, and certificate are one unit. The ansName carries the version, the certificate SAN carries the ansName, and the TL seals the pair.

Changing the card without re-registering is the exact signature `card_drift_watch` looks for, and it is also what a compromised agent looks like.

Practical consequence for a 36-hour build: **stop editing cards by hand after Saturday.** Late cosmetic edits to a description field are indistinguishable from an attack to any monitor watching.

### 4. Attest the dispatch address, without publishing it

This is the `payto_binding_check` analogue and it is the most important binding in Hawk Eye. His probe fetches the supplier's payTo address and checks whether it is attested in the signed card, because an unattested payTo can redirect settlement.

Ours redirects an armed response instead.

The complication is that the card is world-readable, and publishing the street address of a house containing a person who cannot get off the floor is a worse outcome than the attack. So attest a **commitment**, not the address:

```json
"x-hawkeye": {
  "dispatchAddressCommitment": "sha256:base64url(...)",
  "commitmentScheme": "SHA-256 over salt || JCS(canonical_address)"
}
```

The salt and plaintext are sealed at registration and never served. At call time `caller` recomputes the commitment over the address it is about to speak and refuses if it does not match.

The property we want falls out: **the dispatch address cannot change without a re-registration**, and nobody reading the card learns where anyone lives. No sensing claim, no operator question, and no resident typing into the app can move it.

### 5. Declare only what is enforced

He wrote this into his own card as a field, and it is the closest thing to our honesty rule appearing in someone else's spec:

```json
"x-security-note": "This agent is publicly accessible with no authentication required (noAuth). The ansIdentityCert scheme (mutual TLS, ANS private CA) is declared for future ANS-to-ANS production calls but is not currently enforced. The card accurately describes what is enforced."
```

He declares `ansIdentityCert` as a `mutualTLS` scheme and then says plainly that it is not currently enforced.

Copy the field and the discipline. If `agents/master` reads a simulated sensor and mTLS is declared but not enforced on some hop by Sunday, the card says so.
A card that overclaims is a signed, published, machine-checkable lie sitting on the surface the judge inspects first. There is no worse place to be caught.

### 6. Match `securitySchemes` to reality

Three schemes on the reference cards: `noAuth`, `ansIdentityCert` (mutualTLS against the chain in `keys[].x5c`), and `httpMessageSignatures` (RFC 9421 over response components, public keys at `/.well-known/http-message-signatures-directory`).

For us the split is not uniform, and it should not be:

- **Sensing agents**: `ansIdentityCert` enforced. `master` is the only caller they should ever accept.
- **`master`**: `ansIdentityCert` enforced, both directions.
- **Read-only surfaces** we expose for the judge to poke at: `noAuth`, declared as such.

`securityRequirements` must match. An agent that declares mTLS and accepts anonymous calls fails a live A2A probe from `verify_agent`, which reports the credential the agent actually required.

### 7. Keep nothing sensitive in either card

Both are public and permanently recorded by at least one verifier we do not control.

Never: resident names, the street address in plaintext, room labels that identify a person ("Grandma's room" is a privacy leak, `zone_3` is not), internal hostnames, or anything that maps a presence ID to a human.

### 8. Staple the receipt, and serve the DNS

- `transparencyReceipt` stapled into the trust card, so verification reaches Gold offline.
- `_ans` and `_ans-badge` TXT records present and matching what the TL sealed. The AIM checks both and a content mismatch is a `Mismatch` finding.
- **DNSSEC on.** Chain validity is a scored integrity signal, and `verify_agent` checks DNSSEC signatures by name.
- DANE TLSA where we can get it, for Silver. **Blocked, deliberately, as of 2026-09-20.** The RA requires TLSA to be its own `3 0 1` over a certificate we do not serve, and refuses any other record - including a correct `3 1 1` published alongside it. DANE-correct and ANS-registered are mutually exclusive; registration wins. Full reasoning in `docs/deploy.md`

### 9. Harden the endpoint that serves the card

Free, and the judge's verifier fetches over HTTP so the headers are visible. His stack sets `strict-transport-security`, `x-content-type-options: nosniff`, `x-frame-options: DENY`, `content-security-policy: default-src 'none'; frame-ancestors 'none'`, `referrer-policy: strict-origin-when-cross-origin`, and `permissions-policy` with geolocation, camera, and microphone all empty.

That last one is worth setting deliberately rather than copying. A system whose entire pitch is "no camera, no microphone" should say so in a header a machine can read.

Rate-limit the card endpoints and cache them. They are the most-fetched surface we expose.

### 10. Watch our own drift

Run `card_drift_watch`'s logic against ourselves on a timer: hash both cards, compare to the last known-good, alert on change.

If a card changes and we did not ship a version, something is wrong, and we would rather find it than have `verify_agent` find it on Sunday morning.

## The implementation

Card signing, drift fingerprinting, and the address commitment are implemented in
`app/backend/hawkeye_backend/verification/card.py`, with `app/backend/tests/test_card.py` covering them.

- `sign_card(card, key, trust_card_url=..., kid=...)` produces the `signatures` array in the shape above.
- `card_fingerprint(card)` is the `card_drift_watch` analogue. It hashes the canonical form, so reformatting is not drift but a changed value is.
- `commit_address()` / `address_matches()` implement measure 4. A test asserts the address is not recoverable from the published fragment, and another asserts two installations at the same address produce different commitments, so cards cannot be linked.

Canonicalization is shared with the claim envelope (`verification/canonical.py`). One JCS implementation in the codebase, which is what measure 1 asks for.

## If we do build a verifying endpoint anyway

We do not need one to survive the battery, because the battery cannot reach us. But `master` needs these properties regardless, for its own claim envelope, and ANS-6 Method B specifies them exactly.

**Added 2026-09-19: a server-supplied nonce**, the DPoP `nonce` analogue, on `PossessionProof`. The verifier issues it and the presenter answers it, which is what makes the agent mesh pull-only: an agent cannot produce a usable claim unbidden, so a compromised sensing agent cannot prepare a batch of plausible claims in advance. It is covered by the proof signature and required non-empty. Three probes in `app/backend/tests/test_battery.py`.

**This is built**: `app/backend/hawkeye_backend/verification/verifier.py`, with the thirteen shapes as tests in `app/backend/tests/test_battery.py`. What follows is the order it implements, kept here because it is the part worth reviewing.

The verification order, from ANS-6 §7.4, cheapest and least stateful first:

1. Bound the proof size **before parsing**. The reference profile caps at 8 KiB.
2. Strict header decode: exactly `typ`, `alg`, `jwk`, `x5c`. **Any additional JOSE parameter rejects the proof** - a smuggled `kid`, a `crit`, anything.
3. `x5c` has exactly one entry, the leaf. A chain is a rejection, because trust comes from the status token and not from walking a chain.
4. **`jwk` equals the `x5c[0]` key byte-for-byte, compared before any signature work.** This is the order that makes a swapped `jwk` fail closed.
5. Verify the JWS under that single key.
6. `htm` matches the method; `htu` matches the normalized URL. `htu` excludes the query string, so **no authority-bearing parameters in a query string**, ever.
7. `iat` within skew, default 120 seconds.
8. Verify the status token and receipt.
9. Verify `ans_content_digest` against the body. Enforce size limits before hashing.
10. **Record the `jti` in the replay cache last**, after everything else has passed.

Step 10 is the one that is easy to get backwards and expensive to get wrong. Recording the `jti` early lets anyone holding a self-signed certificate flood a bounded cache and fail-close authentication for every legitimate caller. On this system that is a denial of service against a 911 call.

Also: reject a request where `DPoP`, `Authorization`, `X-SCITT-Receipt`, or `X-ANS-Status-Token` appears more than once. Fail closed when the replay cache is full or erroring. Share the cache across replicas, or a proof replays cleanly against a different one.

The line worth remembering, near-verbatim from the spec: a proof passing steps 1 through 7 is cryptographically well-formed but **not yet trusted**. Verifying the status token is what turns "someone holds this key" into "this registered, currently-valid agent holds this key."

## Checklist

Per agent, all five:

- [ ] `/.well-known/agent-card.json` served, plus `/.well-known/agent.json`
- [ ] `/.well-known/ans/trust-card.json` served
- [ ] Card signed, `typ: agent-card+jws`, `jku` to our trust card, `kid` matching
- [ ] One JCS implementation across all five agents
- [ ] Card is a build artifact, byte-stable, sorted keys, no dynamic fields
- [ ] ansName carries the version; certificate SAN carries the ansName
- [ ] SCITT receipt stapled. **Outstanding** - all seven are ANS ACTIVE with badges as of 2026-09-20, but `transparencyReceipt` is still `null` in every trust card, so verification needs a network round trip and cannot reach Gold offline
- [x] `_ans` and `_ans-badge` TXT published and matching the TL. Done 2026-09-20, all seven. A fourth record, `<host>` HTTPS `1 . alpn=h2`, is also required by `verify-dns`; see `docs/deploy.md`
- [x] DNSSEC enabled
- [ ] `securitySchemes` and `securityRequirements` match what is enforced
- [ ] `x-security-note` present and honest
- [ ] `dataEgressPolicy: LOCAL_ONLY` declared
- [ ] `dispatchAddressCommitment` present; plaintext never served
- [ ] No names, no plaintext address, no person-identifying zone labels
- [x] Security headers set, including an explicit empty `permissions-policy` for camera and microphone. Done 2026-09-20, all seven, in the Caddyfile's `(agent)` snippet; see `docs/deploy.md`
- [ ] Self-drift check running on a timer

Before judging:

- [ ] Run `agent.webmesh.ai verify_agent` against all five and fix every finding
- [ ] Re-run it and confirm a clean `compatibility_verdict`
- [ ] Stop editing cards
