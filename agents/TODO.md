# agents/ - what is left

Written 2026-09-19, after the five agents and the wire between them landed.

`CLAUDE.md` is the contract and the reasoning. This is the work queue: what is
unfinished, why it matters, where the seam is, and what it blocks.

**Read the priority order literally.** It is not a wish list in severity order,
it is a dependency order. Item 1 blocks the primary track outright; several
things below it are cheap only once it is done.

## Where things stand

| | |
|---|---|
| Five agents, domain logic | **Done.** 74 tests |
| The wire between them | **Done.** Pull-only A2A, server-issued challenge, verified against published cards |
| Both cards per agent | **Done.** Byte-stable build artifacts, drift check in CI |
| Verification and the refusal path | **Done.** Thirteen battery shapes plus three challenge probes |
| Hosted and reachable | **Not started.** This is the hard track requirement |
| Real identity: domain, certificates, transparency log | **Not started.** Blocking dependency for most of the rest |
| The mesh talking to the app | **Not started.** Master serves no hub API |

---

## 1. Deploy the five agents so they are reachable

**The hard requirement of the primary track.** The track owner said it directly:
agents must be built and hosted on the internet, reachable. Localhost does not
count.

Nothing else on this list matters until agents answer at public names, and the
deploy path is where the hours disappear. **Host them before they are
finished**; five empty agents reachable tonight beats five complete agents on a
laptop Sunday morning.

- Five processes on Vultr, one per agent, one hostname each.
- `HAWKEYE_PEERS` wired so master can reach its peers by hostname rather than by
  loopback port.
- TLS termination in front of each.
- A process supervisor, because an agent that dies silently during judging is
  indistinguishable from one that was never deployed.

**Blocks:** items 2, 3, 4, 10. **Blocked by:** nothing.

## 2. ~~Register the domain, then the agents~~ DONE 2026-09-19

**All five are ACTIVE in ANS production.** `batradar.club`, registered at
Porkbun; `.club` is a GoDaddy Registry TLD, so the MLH Best Domain Name stack
survives the registrar.

| Agent | ANSName | Agent ID |
|---|---|---|
| people | `ans://v0.1.0.people.batradar.club` | `45a25803-d61d-44e2-a75f-f06f8f0a0ec3` |
| intruder | `ans://v0.1.0.intruder.batradar.club` | `98662238-c1e3-4be8-9b62-ac12a9d2eb6c` |
| master | `ans://v0.1.0.master.batradar.club` | `b5359778-1e03-4901-b261-5a0915ef7271` |
| caller | `ans://v0.1.0.caller.batradar.club` | `52470f49-0c31-44e6-85b1-4ffdd1a62f55` |
| replay | `ans://v0.1.0.replay.batradar.club` | `55d9935f-d496-491c-8639-c9e35b8ffca2` |

Each cleared DOMAIN_VALIDATION, CERTIFICATE_ISSUANCE and DNS_PROVISIONING.
`scripts/register-agents.sh` and `scripts/verify-agents.sh` reproduce it; both
are idempotent, so re-running is the way to check rather than a risk.

Held locally under `agents/.ans/<slug>/`, **gitignored and they must stay that
way** - the identity key *is* the agent:

- `identity.key` / `server.key`, and the CSRs they came from
- `identity-certs.json`, `server-certs.json` - issued off those CSRs
- `badge.json` - the **SCITT transparency-log receipt**, with a real Merkle
  inclusion proof and a signed checkpoint from
  `transparency.ans.godaddy.com`. This is the artifact that makes Gold tier
  possible; see item 3.

### The ANSName shape was not a preference

ANS publishes `_ans.<host>` and `_ans-badge.<host>` **per registration**, so
five agents on one host would collide on them. Subdomain per agent, decided by
the protocol rather than by taste.

### Three things that cost time, recorded so they cost nobody else any

- **An OTE API key fails production with a bare `Unauthorized`.** Nothing in the
  error names the environment. The key must be created as type **Production**,
  completing the mobile-PIN prompt, at
  https://classic-developer.godaddy.com/keys. Test with
  `curl -H "Authorization: sso-key $ANS_API_KEY" https://api.godaddy.com/v1/domains`:
  401 is the wrong key, 403 is the right key on a gated endpoint.
- **The wildcard `CNAME *.batradar.club` shadows every unpublished name.** A
  resolver that queried `_ans.<agent>` before the record existed caches
  `pixie.porkbun.com` for the wildcard's TTL and keeps answering with it - the
  registry's own resolver does this, which is why `verify-dns` reports records
  as missing minutes after they are live. Retrying clears it. **Check the
  authoritative nameservers, not a public resolver**, when deciding whether a
  record is really published. The wildcard also has to go before the agents
  deploy, or it will answer for hosts that should be theirs.
- **Porkbun's minimum TTL is 600**, not the 300 the CLI suggests.

### DNSSEC and DANE

**DNSSEC is on** (Porkbun DNSSEC toggle, 2026-09-19). The zone is signed - two
DNSKEYs, a 257 KSK and a 256 ZSK, algorithm 13 - and Porkbun submitted the DS
to the `.club` registry automatically, being the registrar as well.

**All five TLSA records are published** at `_443._tcp.<host>`, `3 0 1` over the
real server-certificate hash ANS issued, verified identical on all four
authoritative nameservers. `verify-dns` now returns clean for every agent with
nothing missing.

**The DS landed at the `.club` registry** the same evening, on all three parent
nameservers:

    DS batradar.club 2371 13 2 677C73444892311DF145630754361DDD93A8534FAE99A1BF5511E6F7923D1ABD

**The chain validates end to end.** All five TLSA records answer with the `ad`
flag set on independent validating resolvers (Quad9, OpenDNS, Verisign), which
is the real test - a published TLSA under an unvalidated chain proves nothing.
**DANE is live and Silver is claimable**, honestly, as of 2026-09-19.

Verify it the way a judge would:

    dig +dnssec TLSA _443._tcp.master.batradar.club @9.9.9.9 | grep flags

**Demo caution: use 9.9.9.9, not 8.8.8.8.** Google and Cloudflare cached the
zone as *insecure* during the window between DNSSEC going on and the DS
propagating, so they answered `ad=0` for `people` and `intruder` for a while
afterwards. The records are correct; the caches were stale. This is a good thing
to know before running the command in front of someone.

- The optional `HTTPS 1 . alpn=h2` record per agent is still unpublished.
  Discovery-purpose only; it costs nothing and can wait for deployment.

## 3. Real certificates, and the chain nobody validates yet

`agents/core/discovery.py` loads the raw public key from the trust card's
`keys[].x` and does not look at `keys[].x5c` at all, because no certificates
exist. That is **Bronze at best: one trust channel, the card itself.**

- Validate `x5c` against the ANS private CA. It is a check inside
  `_agent_from_card`, not a restructuring.
- DANE TLSA records for Silver.
- Stapled SCITT receipt in the trust card for Gold, which is what makes
  verification work offline. On a live incident, a hop that needs a network
  round trip to verify is a hop that can be starved.

**Target Gold on the `master` to `caller` hop at minimum.** That is where a
claim becomes a 911 call.

**Blocked by:** 2.

## 4. Certificate drift detection, which is the strongest ANS story we have

Version-bound certificates record the code running at registration. A sensing
agent whose fingerprint drifted mid-run should be distrusted and its claims
discarded, and **that is the cheapest, most demonstrable use of ANS available to
us.**

Today `SourceAgent.certificate_version` is `None` in every verification result
(`agents/master/gate.py`), so the app renders nothing there and a drifted agent
is indistinguishable from a healthy one.

- Record the fingerprint master saw at discovery. `discover()` already returns
  it and nothing consumes it yet.
- Re-fetch cards on a timer and compare. A card that changed without a
  re-registration is exactly what a compromised agent looks like.
- Surface the version in `SourceAgent` so the verification feed can show it.

**Blocked by:** 2, 3. **Worth doing even partially:** comparing fingerprints
across refreshes needs no certificates at all and could ship today.

## 5. Live Trust Index lookups

Profiles come from the roster's own expectation today, in two places:
`TrustGate.__init__` and `discovery.discover`. **A profile master assumes is a
profile an attacker does not have to earn.**

- Query the Trust Index per agent, cache with a short TTL, refresh in the
  background. Not inside the verification path: same starvation argument as the
  stapled receipt.
- Consume `recommendedProfile` rather than inventing a parallel score. Using the
  track's own policy vocabulary is free credibility.
- Confirm the response shape against `agent-trust-discovery`: are dimensions
  0-1 or 0-100, what is the JSON key, does it distinguish "unimplemented" from
  "scored 0"? The 0-1 range in `TrustIndexScore` is our choice, not a verified
  fact.

**Also here: ship a safety-dimension evidence producer.** Only integrity and
identity are implemented upstream; solvency, behavior and safety are scored 0
until plug-in signals are registered. Our sensing layer is a natural producer
for safety, and POSTing observations to `/v1/internal/observations/import` is
the documented extension path. **This is the strongest available differentiator
on the track** and it is the one place the hardware and the ANS work genuinely
fuse.

## 6. Master's API for the hub, which does not exist

`app/backend/hawkeye_backend/master/live.py` is written against five endpoints
on master: `/v1/state`, `/v1/sensor`, `/v1/agents`, `/v1/incident`,
`/v1/stream`. **Master serves none of them**, so `HAWKEYE_MODE=live` on the hub
cannot work and the app has no path to the real mesh.

This is the largest functional gap on the list after deployment, and it is
independent of everything ANS, so it parallelises well.

- `/v1/state` - master's aggregated `InteriorState`, built from admitted claims.
- `/v1/agents` - reachability, which master already knows from its fetches.
- `/v1/incident` - raise, context, replay fetch.
- `/v1/stream` - the websocket the hub subscribes to.
- Answer the three `TODO(master)` questions in `live.py` while you are here:
  merged state document or fan-out, websocket or SSE or webhook, and whether the
  hub must present an ANS identity to raise an incident.

**Blocked by:** nothing.

## 7. Wire the incident lifecycle through the agents

The pieces all exist and are not connected to each other.

- **`caller` has no master.** `__main__` builds `CallerAgent(mesh)` with no
  master reference, so a deployed caller can do nothing at all.
- **`replay` is never called.** Nothing writes to it. Master should record every
  claim, every discard, every utterance and every operator reply.
- **`master.release_for_call()` releases nothing.** It sets a flag; no path
  connects it to `caller` dialling.
- **The incident id never reaches the transport.**
  `A2AObservationSource.incident_id` is set to `steady-state` at construction
  and never updated, so claims produced during an incident do not bind to it.
- **`dispatched_incidents` is never populated**, so the protection battery #12
  tests - a claim naming an already-dispatched incident is spent - is inert in
  the running system even though the verifier implements it.

That last pair is the important one: **two real security properties are
implemented, tested, and currently switched off in production** because nobody
sets the field.

## 8. The impostor, as a real process

The refusal is the submission, and today it is proved in-process by
`tests/test_wire.py`. For the demo it should be **a sixth process at a lookalike
hostname**, presenting real claims that fail real checks, so a judge watches a
discard happen rather than reading that it would.

Build it in the thirteen shapes. Stage `underpay_valid_sig` specifically: a
genuinely valid signature that must still be refused, which demonstrates the
difference between authentication and authorization to a room.

**Say it plainly that we reimplemented the shapes** rather than implying we ran
his suite. The battery cannot be aimed at us; it is hardwired to
`supplier.webmesh.ai`.

## 9. The dispatch address commitment is built and not usable

`scripts/build_cards.py` computes the commitment, puts it on the card, and then
**discards the salt** (`del salt`). So `caller` cannot recompute the commitment
over the address it is about to speak, which is the entire point of the
mechanism.

The salt and plaintext are sealed at registration and never served. Persisting
them belongs with registration rather than with card generation, which is why it
is not done here, but until it is, the binding is decorative.

**This is the single most important binding in the project.** An agent that can
change where a response is sent is a swatting tool no matter how well the claims
upstream verify.

**Blocked by:** 2.

## 10. mTLS between agents

Declared on every card as `ansIdentityCert` and explicitly not enforced, which
`x-security-note` says out loud.

The ordering is deliberate: **mTLS proves the connection, JWS proves the claim**,
and our threat model is a compromised agent whose connection is perfectly valid.
JWS also survives a reverse proxy where mTLS terminates at the edge.

Enable it at the proxy, and **update `x-security-note` in the same commit**. A
card that overclaims is a signed, published, machine-checkable lie on the
surface the judge inspects first.

**Blocked by:** 1, 3.

## 11. ElevenLabs voice, and the phone leg

`caller` composes utterances and speaks to nobody. The outbound half is a
near-zero-work stack on a sponsor track.

- ElevenLabs synthesis on `opening_report` and `answer_operator`.
- A real outbound PSTN leg to a phone we control. **Never to a real PSAP.**
- Transcription of the far side, feeding `operator_said`.
- Voice barge-in, which is load-bearing rather than a nicety: it is the instant
  path that makes the deliberate 1.5s hold on TAKE OVER safe.

## 12. The conference bridge and whisper mode

The switch matrix, the mode rules and the announcements are all implemented in
`agents/caller/bridge.py`. What does not exist is a bridge.

- Server-side mixing with independent send and receive per leg.
- The resident's leg as **in-app WebRTC, not a phone call**, so iOS does not own
  the audio routing and there is no volume floor to fight.
- Hold the leg open from the start of the call with both switches off, so
  switching modes is one server-side bit and not a handshake mid-emergency.

**Whisper is the feature no existing product has, so cut it last.** The fallback
if time runs out is PSTN dial-in for full voice, with whisper on the roadmap.

## 13. Tune the sensing thresholds against real capture

Two constants are placeholders with a stated rationale and no data behind them.
Each is marked `TODO(sensor)`:

| Constant | File | What it decides |
|---|---|---|
| `PERSONHOOD_STRENGTH` | `people/respiration.py` | Whether a perturbation is a living body |
| `OCCUPIED_EXCESS` | `people/presence.py` | Whether a zone is occupied |

Both need the same thing: an empty room and an occupied room from the same
link, same channel, same geometry. `docs/hardware/bring-up-checklist.md` is the
path.

**Blocked by:** the CSI capture path, which is the project's largest single risk.

## 14. Real CSI, replacing the synthetic feed

`agents.core.dev.SyntheticCsiFeed` is a development fixture and says so. Every
reading it produces carries `ruview-sim`, which computes to simulated, so it
cannot be presented as measured.

Replace with replayed capture first, live capture last. **The agent layer must
never block on the hardware**, which is why this is at the bottom rather than
the top.

Also here: `DEMO_ZONES` in `__main__` is hardcoded and should come from the
one-time enrollment walk.

## 15. Housekeeping

Small, and each removes a way for two things to disagree.

- **Delete the duplicate roster.** `app/backend/hawkeye_backend/master/scenario.py`
  carries a copy of the five agents. `agents/core/identity.py` is the source of
  truth; the hub should import from it.
- **`replay.seal()` returns `transparency_receipt: None`.** Submit to SCITT and
  staple it. Until then the record is tamper-evident to whoever holds it and to
  nobody else, and it must be described that way.
- **Refresh the trust store periodically.** `discover()` runs once at startup, so
  an agent that re-registers mid-run is never picked up.
- **Push the corrected Mermaid diagrams to Notion.** The copies there still show
  nine agents.

## Roadmap, not this weekend

One line each on the Devpost page, because they show the architecture has
somewhere to go.

- **MCP alongside A2A.** All the webmesh.ai agents speak both. It is a second
  adapter over the same handlers, so it buys presentation rather than
  capability - which is exactly why it was cut.
- **Per-person agents.** Each resident gets an agent holding their context:
  medical conditions, mobility, where they usually sleep. The current design is a
  step toward this, not away from it.
- **Live PSAP-side ANS resolution.** The moment a dispatch center can resolve an
  ANSName, live verification falls out of what is already built here. That is
  also the right closing line, because it names the one thing we do not solve.
