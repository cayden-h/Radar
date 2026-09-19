# ans/

ANS registration, certificates, domain setup, and our Trust Index contribution.
Shared plumbing for everything in `agents/`.

Read the root `CLAUDE.md` first.

**Then read `docs/threat-landscape.md`.** It maps Hawk Eye onto OWASP ASI01-10 and MAESTRO, and it ranks every mechanism named below by what it buys us per hour of work.
The single most useful thing found while writing it: the ANS registry repo ships its own [`MAESTRO.md`](https://github.com/agentnameservice/ans-registry/blob/main/MAESTRO.md), a full threat analysis of the ANS architecture by the people who built it.
Read that before designing anything here. Speaking the track owner's own layer vocabulary back to him is free; contradicting it is a way to lose an argument we did not need to have.

## Do this first, before any code

The domain is a blocking dependency for the entire project.
ANS is domain-anchored; nothing registers without it, and DNS propagation is not instant.

1. Register a domain through **GoDaddy Registry**. This also stacks the MLH "Best Domain Name" prize for free.
2. Free ANS registration is available through GoDaddy. Get it done.
3. Pull the reference codebase at https://github.com/agentnameservice and run it locally. Two components: an agent side and a skill side.
4. Verify one trivial agent end to end before building four real ones.

Pick a domain name that survives being read aloud by a judge.
It goes on the Devpost page and in the agent cards.

## Certificates

x509 certificates underpin agent identity here.
The track owner drew an explicit line against Cloudflare and DigiCert on this point: certificates are GoDaddy's primary business, not a secondary offering, and DNS protection on GoDaddy domains extends to agents.

Practical consequences:

- Use GoDaddy's certificate path rather than whatever is most familiar. Using the sponsor's actual product is not pandering, it is the track.
- Version-bound certificates record the specific code running at registration time. Code change means certificate drift, and that drift is detectable. Build something that notices.
- ANSName URIs and mTLS are ANS-2. Agent-to-agent auth via badges is ANS-6.
- **Turn DNSSEC on.** Chain validity is a scored integrity signal, and an absent or broken chain lowers the score. This is free and we would otherwise forget it.

Verification is tiered, and the tier names are worth using out loud because they are the spec's own:

| Tier | Steps | What it gives you |
|---|---|---|
| Bronze | PKI certificate validation | Standard TLS. One trust channel. |
| Silver | Bronze + DANE record validation | Two independent channels, CA and DNS. |
| Gold | Silver + Transparency Log verification | Three independent channels. Verifiable offline against the log's public key. |

**Target Gold for the `master` to `caller` hop at minimum.** That is the hop where a claim becomes a 911 call.

A stapled SCITT receipt in the Trust Card is what makes Gold possible offline; a sidecar receipt fetched from `_ans-badge` needs a network call, and an absent receipt is weakest.
On a live incident, a hop that needs a network round trip to verify is a hop that can be starved.

## Where the mesh gets its keys

**`master` builds its trust store from the agents' own published trust cards**, not from a configured key list. `agents/core/discovery.py`.

That is a deliberate choice and it is worth saying on stage. A hardcoded list of public keys verifies signatures perfectly well and proves nothing about identity, because the keys are trusted for having been typed in. Fetching them from the published card ties acceptance to the same document `agent.webmesh.ai verify_agent` reads, the same document whose hash is sealed at registration, and the same document `card_drift_watch` monitors. One artifact, three consumers, and no private channel by which we could trust something the public surface does not say.

A peer whose card cannot be fetched is left out of the store, so its claims are refused as coming from an unregistered agent. A reachable-but-unverifiable agent is exactly what an impostor looks like.

**What is missing is the chain.** `keys[].x5c` is not validated, because no certificates exist until registration; the loader reads the raw key from `keys[].x`. That is Bronze, one trust channel, and adding chain validation is a check inside `_agent_from_card` rather than a restructuring. DANE gets us Silver and a stapled receipt gets us Gold, in that order.

## Agent cards

Every agent publishes one, and they must be kept current.
Public agents appear on GoDaddy's Trust Index, which the judge maintains.
A stale or malformed card is a visible defect on the surface most likely to be inspected.

What counts as a "public" agent was raised in the briefing and left open.
Default to public. Visibility on the Trust Index is the point.

A card that drifts and a card that was tampered with look identical to a monitor.
`fraud.webmesh.ai` runs a `card_drift_watch` check alongside its thirteen probes, which tells us the track owner treats card drift as a first-class attack rather than a hygiene issue.
Keeping ours current is therefore a security task, not housekeeping.

**`ans/CARD.md` is the full spec and checklist**: the two cards, JWS card signing, byte-stability, the dispatch-address commitment, and what `agent.webmesh.ai verify_agent` will check when it is pointed at us.
Read it before writing a card. The short version is that the card, not the fraud battery, is the surface actually under test.

### What we should declare on ours

Two fields are worth filling in deliberately rather than by default.

- **`dataEgressPolicy: LOCAL_ONLY`.** The enum is `LOCAL_ONLY`, `RESTRICTED`, `OPEN`. Our inference genuinely runs on the Pi, and interior occupancy of a private home is about as sensitive as telemetry gets. This is the strongest safety-dimension claim we can make honestly, and it is true today rather than aspirational.
- **`safetySignals.guardrailCertification`.** The `standard` enum currently accepts `OWASP_LLM_TOP10`, `AISI_2026_SAFE`, or `CUSTOM`. The 2026 agentic list (ASI01-ASI10) is not yet a value. Our `docs/threat-landscape.md` maps Hawk Eye against it, so `CUSTOM` plus a `standardUri` is the honest encoding. **This is also a small, real, specific observation to raise with the track owner**, which is worth more in a judging conversation than a compliment.

What we must not do is fill in `enclaveAttestation`. We have no TEE. Scoring zero there is correct and we should say why.

**Fields we cannot fill are not a weakness to hide.** The Trust Vector is five independent scores precisely so that a zero in one dimension does not get laundered into a composite. Leaving ours honest is the behaviour the spec is asking for.

## The Trust Index opportunity

Five dimensions: integrity, identity, solvency, behavior, safety.
**Only integrity and identity are implemented. Solvency, behavior, and safety are present in every response scored 0 until plug-in signals are registered.**

Eight built-in signals feed the two live dimensions: four raw observations (certificate type, DNSSEC status, agent age, version stability) and four drift verdicts (server certificate fingerprint, identity certificate fingerprint, DNS `_ans`, DNS `_ans-badge`).
Note the wording: the three missing dimensions are not "hardcoded" so much as **present in every response scored 0 until plug-in signals are registered**. The socket exists and is empty.

There is a documented extension contract:

- Implement the `port.Signal` interface in-process. Three methods: `Derived` (does this signal come from other observations), `Validate` (the per-signal schema an observation must satisfy), and `Evaluate` (observations to a raw 0-100 score). Then register it and ship a weight in a profile. No code generation, no dynamic plug-in loading.
- Or write an evidence producer in any language that POSTs to `/v1/internal/observations/import`. **There is no `port.Hydrator`; the interface is the HTTP contract**, and producers are treated as untrusted processes on the far side of that boundary.

The second path is ours. Our evidence producer is a Raspberry Pi parsing untrusted radio frames, and it belongs on the far side of an HTTP boundary from anything that scores.

Shipping one of the three missing dimensions is the strongest available differentiator on this track, and we have an unusual asset for it: **a physical-world sensor.**

### Our angle: safety, grounded in physical reality

Every other Trust Index signal anyone builds this weekend will be derived from an agent's own network behavior.
Ours can be derived from what is actually happening in a building.

Concretely, a safety evidence producer that answers: did the agent's claims match physical reality?
An agent that reported an unresponsive occupant to emergency services where no sensor corroborates one is behaving unsafely, and that is an observation worth posting.
The inverse matters too: an agent that stayed silent while the sensors showed a person who stopped breathing.

This is the one place where the hardware and the ANS track genuinely fuse rather than merely coexist.
Lead with it.

Reference implementation: https://github.com/agentnameservice/agent-trust-discovery

## recommendedProfile

Trust Index returns a policy hint: UNTRUSTED, READ_ONLY, TRANSACTIONAL, FIDUCIARY.

`agents/caller` maps these directly onto what a sensing agent's claim is allowed to trigger.
See the table in `agents/CLAUDE.md`.
Consume the hint rather than inventing a parallel scoring scheme; using the track's own policy vocabulary is free credibility.

Two details from the spec that change how `master` should behave:

- **UNTRUSTED is a discovery-suppression signal, not a revocation trigger.** Suppression hides an agent; revocation breaks its TLS and requires RA action. Only the RA revokes. Mirror this: `master` stops accepting a drifting agent's claims and logs the discard, and does not try to revoke anything mid-incident.
- **Suppression precedes revocation upstream too.** The Agent Integrity Monitor publishes a finding, the RA waits for corroborating reports from multiple independent monitors, and reversible suppression comes before permanent revocation. A single monitor's opinion is not a verdict. That is the right posture for us as well, and it is the principled reason `master` requires corroboration across independent modalities rather than trusting one loud sensor.

**A valid signature is not authorization.** The `fraud.webmesh.ai` battery probes this ten different ways, and `underpay_valid_sig` is the pure case: a genuinely authority-signed mandate for the wrong amount, which must still be refused. Our analogue is a validly signed READ_ONLY claim used as the sole basis for a 911 call. See `docs/fraud-13.md`.

Note that the battery is hardwired to `supplier.webmesh.ai` and cannot be aimed at us, so these are shapes we implement rather than a suite we invoke. The agent that *can* be aimed at us is `agent.webmesh.ai`. See `ans/CARD.md`.

## Transparency log

Lifecycle events seal into an immutable SCITT log. Entries cannot be altered after the fact.

Use it for the dispatch audit trail.
"Who asked for the inside of this house, when, under what identity, and what were they told" is exactly the kind of record that must be tamper-evident to be worth anything.

The superseded flight-recorder idea was built entirely around this property.
That idea is dead but this mechanism is not; borrow it.

### Two limits of the log, both named in the spec itself

**A receipt proves "was registered," not "is currently trusted."**
Once issued it never expires. If the agent is later revoked, that is a separate event, and a client holding only the receipt cannot see it.
The spec's answer, marked `[PROPOSED]`, is the **Status Token**: a short-lived COSE_Sign1 signed by the RA asserting ACTIVE, DEPRECATED, or REVOKED, refreshed periodically and stapled to the Trust Card next to the receipt.
Same principle as OCSP stapling. When it is absent or expired, the verifier falls back to Silver.

This matters to us more than to most consumers of ANS, because `caller` re-verifies on **every** operator question.
An agent trusted ninety seconds ago may not be trusted now, and a never-expiring receipt cannot express that.
Consume Status Tokens if they exist; model the same state ourselves if they do not.

**The log proves registration, not transactions.**
Correlating one request across several agent hops needs a request correlation ID at the application layer.
Neither A2A nor MCP mandates one that spans hops.
The spec says the SDK should carry an existing W3C Trace Context `traceparent` through mTLS handshakes and JWS-signed messages when present, rather than inventing a parallel scheme, and that where none is provided the forensic gap belongs to whoever hosts the agent.

**That gap is ours.** Generate a `traceparent` at incident open in `master` and propagate it through all five agents.
It is an hour of work, it closes a hole the spec explicitly names, and it is the difference between `agents/replay` holding a pile of events and holding a traceable incident.

## Live agents to build against

Do not mock counterparties. These are real and they are the track owner's own infrastructure.
Machine-readable index at `/.well-known/agents-index.json`.

- `agent.webmesh.ai` - verifies and discovers ANS-registered agents by FQDN
- `authority.webmesh.ai` - issues RFC 9421 spending mandates with cryptographic binding
- `auditor.webmesh.ai` - independently verifies transactions, produces signed reports
- `rogue-supplier.webmesh.ai` - adversarial test agent
- `fraud.webmesh.ai` - attack battery, 13 targeted security probes
- Also: `impact`, `dnsdoc`, `seo`, `traveler`, `supplier`

## Repos

- Specs and Trust Index: https://github.com/agentnameservice/ans-registry
- Reference implementation: https://github.com/agentnameservice/ans
- CLI/SDK (Go): https://github.com/agentnameservice/ans-sdk-go
- Trust Index reference implementation: https://github.com/agentnameservice/agent-trust-discovery
