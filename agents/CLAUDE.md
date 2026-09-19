# agents/

The five ANS-registered agents behind Hawk Eye. All of them live on the user side, inside the home.
This is the GoDaddy track submission. Everything else supports it.

Read the root `CLAUDE.md` first. `agents/README.md` is how to run them; this file is the contract.

**Status, 2026-09-19.** All five agents are written and tested, **and the wire between them exists.** `master` issues a challenge, sensing agents sign their current observation against it, and every claim is verified against the key the producer publishes in its own trust card before anything downstream sees a field. Verified end to end over real HTTP in `tests/test_wire.py`, including the refusals.

What is still missing is deployment: real certificates, a registered domain, mTLS at the edge, and the agents reachable at public ANSNames.

## Why five agents instead of one

A judge will ask this. The answer is **context separation and speed, not redundancy.**

Each agent holds one narrow context and answers one kind of question, so none of them carries a prompt describing the whole system.
Narrow context is faster, cheaper, and less likely to hallucinate across concerns.
They run in parallel, so an operator's question fans out and returns at the speed of the slowest single answer rather than the sum of them.

It is also what makes the ANS story real rather than decorative.
One agent verifying itself is theater. Five independently registered agents that must verify each other before anything reaches a dispatcher is the track's actual model.

## Why five and not nine

The roster was nine until 2026-09-19. The merge is worth being able to explain, because "we had nine and cut to five" sounds like a retreat and it is the opposite.

**The principle: an agent is a context boundary, not a task.**
Two components that read the same input, hold the same state, and always run in the same order are one agent with two steps. Splitting them buys three deployments, three certificates to keep current, and three chances to disagree about what the radio said.

| Was | Went to | Why |
|---|---|---|
| `biometrics` | `people` | Personhood is what makes a presence a person. Everything `people` says is conditioned on it |
| `occupancy` | `people` | Same CSI window, same rolling baseline, same tick |
| `collapse` | `people` | A fall is a state a *person* is in, and it needed the respiration verdict to interpret |
| `environment` | `master` | A sensor attached to the host has no counterparty to authenticate |
| `guidance` | `caller` | `caller` is the agent that talks to humans, and there are two of them on a live incident |

**Fall detection was then cut outright on 2026-09-19**, after the merge, and the `collapse` reader was deleted with it.
It was the weakest link in the chain: a debounce problem dressed as a clinical variable, where sitting down fast, lying down to sleep and a child playing all look like a fall for an instant.
The question a dispatcher actually needs answered is narrower and defensible - whether the people inside can respond - and respiration already answered it.
What `people` carries now is `people.respiration_lost`: seconds since a breathing signature was last resolvable on a presence that previously had one.

**What the merge did not touch is the line the ANS story runs along.**
Every hop that carries a claim from something that senses, to something that decides, to something that speaks, is still a hop between independently registered agents.
`people` to `master` is the hop where a compromised sensor would have to get past verification, and it is untouched.

Two of the merges cost something, and both costs are stated where they live rather than glossed:

- **`environment` into `master`** means the CO reading skips the gate, because master is now both its producer and its consumer. The reading is labelled unverified-by-construction and capped at CORROBORATING rather than quietly inheriting master's FIDUCIARY standing. If the gas sensor ever moves onto separate hardware it gets its own identity and goes back through the gate; that is a deployment change, not a redesign. See `agents/master/environment.py`.
- **`guidance` into `caller`** puts both human boundaries in one agent. That is also the gain: one agent holds one picture of the incident and says it twice, which is what stops the operator and the resident being told different things.

`intruder` was **not** merged into `people`, and the reason is the same principle read forwards: it does not share an input.
`people` reads the radio; `intruder` reads `people` plus the network. Different evidence, different failure modes, and a claim from each one corroborating the other is worth something - which two views of one CSI stream would not be.

## Always running

**Every agent runs continuously.** Nothing spawns on incident.

This is a requirement, not an optimization. It is what allows the system to notice things nobody asked it to look for:
an unidentified person in the house at 3am, a breathing signature that was there a minute ago and is not now, CO climbing while everyone sleeps.

An architecture that only wakes on a button press cannot do the thing that makes this project worth building.

It is structural in the code rather than conventional: `agents.core.base.Agent` has no "handle a request" entry point, only a `tick` that runs whether or not anyone is asking.

## How they talk to each other

Settled 2026-09-19. **Pull-only, A2A JSON-RPC, with a server-issued challenge.**

```
master ──POST /a2a {nonce}──►  people     "what do you have right now?"
       ──POST /a2a {nonce}──►  intruder
           ◄── SignedClaim[] + PossessionProof, bound to that nonce
```

### Pull, not push, and the reason is binding strength

`master` asks; sensing agents answer. Nothing is pushed.

**With pull, master controls the nonce**, so a claim is bound to a specific question asked at a specific moment. With push the producer picks its own nonce and master can only check it has not seen it before, which is strictly weaker: a compromised sensing agent could prepare a batch of plausible claims in advance and fire them at an incident. Under pull it cannot, because it cannot guess the challenge.

It also collapses two code paths into one. The steady-state tick and the operator fan-out are the same mechanism, so the beat that matters in the demo is exercised continuously rather than only during a call.

The cost is up to one second of detection latency. Against a `people.respiration_lost` clock measured in minutes, that is nothing.

### The challenge

`PossessionProof.nonce`, added 2026-09-19. The DPoP `nonce` analogue: **the verifier issues it, not the presenter.** It is covered by the proof signature, so it cannot be rewritten onto a claim prepared earlier, and it is required and non-empty, because "the verifier did not ask for one" and "the presenter omitted it" must not share a wire representation.

Three probes in `app/backend/tests/test_battery.py` cover it, alongside the thirteen.

### A2A, because that is what we published

Our cards declare `preferredTransport: JSONRPC` at `https://<host>/a2a`, and `agent.webmesh.ai verify_agent` sends a **live A2A message** and reports the credential we actually required. An agent whose card advertises an endpoint that is not there fails the judge's own verifier on the surface we called our best demo beat.

**MCP is deliberately not implemented.** All the webmesh.ai agents speak both and ours should eventually; it is a second adapter over the same handlers and it buys presentation rather than capability. Roadmap, not this weekend.

### The trap the transport is built around

`ClaimVerifier` verifies **bytes**. If the transport parses a claim into a dict and re-serializes it anywhere in between, every signature breaks and the failure looks exactly like tampering.

So claims cross the wire as **opaque JSON strings inside the JSON-RPC result**, never as nested objects. `tests/test_wire.py::test_the_signed_bytes_survive_the_json_layer` is the guard.

### Where trust comes from

`master` builds its trust store by **fetching each agent's published trust card**, not from a configured key list. A hardcoded list would verify signatures perfectly and prove nothing about identity, because the keys would be trusted for having been typed in.

Fetching them ties acceptance to the same document `verify_agent` reads, the same document whose hash is sealed at registration, and the same document `card_drift_watch` monitors. One artifact, three consumers, and no private channel by which we could trust something the public surface does not say.

A peer whose card cannot be fetched is **left out of the store**, so its claims are refused as coming from an unregistered agent. A reachable-but-unverifiable agent is exactly what an impostor looks like.

### mTLS is the second layer, not the first

ANS-2 wants mTLS and the cards declare `ansIdentityCert`. It is not enforced yet and the card says so.

That ordering is deliberate rather than an excuse: **mTLS proves the connection, JWS proves the claim.** Our threat model is a compromised sensing agent that is exactly who it says it is at the TLS layer, with a perfectly valid connection. The layer that catches it is the signed envelope, verified by the application, and that layer also survives a reverse proxy where mTLS terminates at the edge.

Add mTLS at the proxy once the agents are reachable, and update `x-security-note` in the same commit that turns it on.

### Verification is per fetch, never a process-wide flag

`FetchedObservation.envelope_verified` is set by the transport that just verified this agent's claims, and `TrustGate.admit` takes it per call. Trust is a property of an agent at an instant: one that answered a verified challenge a minute ago may fail the next because its certificate drifted, and a flag set once at startup cannot express that.

`agents/intruder` applies the same rule one hop earlier. If the personhood verdict did not arrive verified, it still reports what it computed and caps that report at CORROBORATING, because an unverified verdict is not a verdict to send officers on.

## Topology

```
              router ──► sensor/ ──► CSI              gas sensor (simulated)
                                      │                        │
                        ┌─────────────┴───────┐                │
                        ▼                     │                │
                     people                   │                │
              count, location, personhood,    │                │
              respiration, movement,          │                │
              responsiveness                  │                │
                        │                     │                │
                        │ ANS                 │                │
                        ▼                     │                │
                    intruder  ◄───── roster + device association│
              which body no device accounts for                │
                        │                                      │
                   ANS  │                                      │
                        ▼                                      ▼
                            master (coordinator)  ◄─────────────
                     verifies, classifies, aggregates, routes
                          │                            │
                     ANS  │                       ANS  │
                          ▼                            ▼
                      caller                        replay
                          │      │                     │
           ElevenLabs     │      │ iOS app             │ sealed log
              voice       ▼      ▼                     ▼
                911 operator   the user      post-incident review
```

**The boundary is the point.**
Human to agent is plain English, in both directions, on both ends. There is no ANS there and there cannot be, because the far ends are people.
Agent to agent is ANS, every hop.

`caller` is the translator, in both directions and to both audiences.
Nothing crosses a human boundary that was not verified first.

## The cast

Five agents. Priority tiers are marked; build in tier order when time is short.

**Domain research for every agent is in `docs/research/agent-briefs.md`**: the thresholds each one acts on, the statistics behind it, and what it must not claim.
Read your agent's brief before writing it. The "must not claim" lines are the ones that lose the judging conversation.

They are also **published on each agent's card** under `x-hawkeye.mustNotClaim`, and each one has a test in `agents/tests/`. A limit that only exists in prose is a limit nobody checks.

### Sensing tier

#### agents/people **[tier 1]**

How many people are in the building, where each one is, whether each one is breathing, and whether a dispatcher should expect an answer from any of them.

**The load-bearing agent, and the only consumer of the CSI stream.** If only one sensing agent works, make it this one.

Two readers run in a fixed order each tick, because the second depends on the first:

```
respiration  ->  is this a person, breathing at what rate, moving or not,
                 and how long since a signature we had went missing
presence     ->  which zone, how many, what coarse class
```

There was a third, `collapse`, until 2026-09-19. It is gone and so is fall detection.

##### The personhood verdict

`agents/people/respiration.py`, and it is the component everything downstream is conditioned on. It is not a reporting channel; it is what decides a presence is human.

A perturbation showing quasi-periodic modulation in a physiological band is a living body. A fan, a curtain, a rolling cart, a swinging door: none of them produce that signature.
Three properties make it load-bearing:

1. **Calibration-free.** Periodicity does not depend on knowing what an empty room looks like. This works on minute one; the zone baseline does not.
2. **It discriminates human from non-human motion**, which nothing else in the stack can do.
3. **It works on someone who is not moving**, which is exactly where motion detection fails and exactly the case that matters.

**Use respiration for the personhood decision, never heart rate.**
Breathing moves the chest wall roughly 5-12mm; a heartbeat moves it a few tenths of a millimetre, usually buried under respiration harmonics.
RuView lists heart rate at 40-120 BPM. Treat it as a stretch goal and as a good number to say on the 911 call. Respiration at 0.1-0.5 Hz carries the verdict.

It separates three states a headcount cannot tell apart: moving, still but breathing, and neither.
"I had a breathing signature in the main bedroom four minutes ago and I do not have one now" is the most valuable sentence this system can say to a dispatcher, and it comes from here.
Note the shape of that sentence. It reports a measurement and a clock, and it stops there.

**Do not treat absence of respiration as absence of a person.** Shallow breathing, breath-holding, and range limits all degrade toward invisible.
There is no cross-check reader any more, so the uncertainty is escalated rather than resolved silently: a signature that was present and is now gone raises an `Unknown` on `people.respiration`, the most urgent uncertainty this system can produce.

##### Location and class

Coarse, room-level zones. Not coordinates.
Presence IDs are stable within a session only; we do not do person re-identification and must not claim to.

**The class split is grounded in respiration rate**, not in signal amplitude. Resting rates: adult 12-20, child 20-30, infant 30-60, dog and cat 15-30+.
That is physically defensible where "mass perturbs the signal differently" was not, and an RF-literate judge will press on the difference.
It does **not** cleanly separate a dog from a child. State the overlap rather than hiding it; the honest resolution is "adult versus small and fast-breathing."

**This is the part that needs a baseline**, and the only part of the system that does. Counting and localization are the capabilities that require knowing what empty looks like.
See the calibration section in `sensor/CLAUDE.md`: build a rolling percentile baseline with slow adaptation, not a calibration step. The adaptation constant decides whether a motionless person stays visible.

The baseline is over the **disturbance level**, not raw amplitude. What a baseline is *of* matters: a baseline over raw amplitude tracks the static multipath structure, which is not the thing a person changes.

##### What counting can actually deliver on this hardware

Settled 2026-09-19. **Presence: reliable. An exact count: not reliable.**

The BCM43455c0 is **1x1**. One antenna means frequency diversity across subcarriers and no spatial diversity at all. Most CSI counting in the literature uses Intel 5300 or Atheros NICs with two or three antennas, because antenna diversity is where spatial resolution comes from.
RuView says the same in its own terms: single-node deployments have limited spatial resolution and 2+ nodes are recommended. Its "3-5 people per AP" figure assumes the multi-node mesh, not one link.

| Scenario | Realistic outcome |
|---|---|
| Two people apart, at least one moving | Detectable as "more than one", moderate confidence |
| **Two people within ~1m** | **Reads as one.** Occlusion plus overlapping Fresnel geometry |
| One moving, one still | The mover dominates; the still one is near-invisible to motion |

That last row is our actual scenario, which is why the respiration reader rather than motion is what finds the person who has stopped moving.

**Respiration is a better route to a count than motion is.** Two people breathing at different rates give two spectral peaks in the 0.1-0.5 Hz band, and two resolvable peaks is real evidence of two bodies. Two people breathing at similar rates, say both near 15 BPM, produce overlapping peaks a single link cannot separate, and it only works while they are still.

A small room cuts both ways: a 3m router-to-Pi span is in the sweet spot and SNR is strong, but two people in 100 square feet are necessarily close together, which is the case that merges, and nearby walls produce dense multipath that makes the channel harder to read rather than easier.

**Therefore: take the count from the roster, not the radio.** Device association tells us two residents are home with certainty, because it comes from the network. See `docs/research/identity.md`. The radio then only has to answer *which room* and *is this one breathing*, which it can.
Where a sensed count is reported at all, it carries a confidence, is phrased as "at least", and is capped at CORROBORATING so it can never move anybody on its own.

##### Responsiveness, and why it replaced fall detection

Someone had a breathing signature, and now they do not.

`people.respiration_lost` carries the elapsed seconds since a breathing signature was last resolvable on a presence that previously had one.
**The transition is the signal.** A presence that never resolved a signature produces nothing here, because shallow breathing, breath-holding and range limits are indistinguishable from an empty room, and a claim that cannot tell those apart is worth nothing to a dispatcher.

This is what a dispatcher actually needs: whether to expect an answer from a room.
It is a narrower claim than "someone fell", and unlike that one it is defensible from the physics.

**It is stamped from the last resolvable signature, not from the moment the agent became confident.** The sentence that matters to a dispatcher is "I had breathing there four minutes ago", not "we decided twenty seconds ago".

**A lost signature is never a finding that someone has stopped breathing**, it is a reason to look, and that limit is published on the card under `x-hawkeye.mustNotClaim` and tested.
The escalated `Unknown` on `people.respiration` says so in the claim itself.

`people` does not raise a 911 call. It surfaces the loss in the app and stamps the clock onto the incident record, so that when a human does call, the dispatcher learns the signature went missing four minutes ago rather than being told "I found her like this."

**Fall detection was cut on 2026-09-19 and `agents/people/collapse.py` was deleted.**
Debounce was the whole engineering problem and it never got better: sitting down fast, lying down to sleep and a child playing all look like a fall for an instant, and a system that calls 911 when someone flops onto a couch is worse than no system.
RuView does ship fall detection upstream, at sub-200ms, with `fall-risk`, `no-movement` and `bed-exit`; we are not using it.
The statistics that used to justify the feature are kept, as history, in `docs/research/incidents.md`.
Saying "we cut the feature whose false-positive rate we could not defend" is a stronger answer to a judge than a demo that flags the couch.

#### agents/intruder **[tier 1]**

Detects and tracks a presence that should not be there.

Distinct from `people` in the question it asks, which is why it stayed separate through the merge. `people` says how many and where; `intruder` says **which of them is not supposed to be here**, and keeps a continuous track once it decides.

It consumes the personhood verdict from `agents/people`. A perturbation without a respiration signature is not an intruder, it is a curtain, and calling police on a curtain is the failure mode to design against.

**The decision rule, settled 2026-09-19: roster plus device association.** Full reasoning in `docs/research/identity.md`.

```
CSI:        3 distinct presences
Roster:     2 registered residents      (configuration, not discovery)
Associated: 2 resident phones on the network
            -------------------------------------
            1 body with no corresponding device
```

The household is known, not discovered. An unexpected presence is a body that no registered device accounts for.

This survives the question a judge will certainly ask - how do you tell a burglar from a roommate - because the roommate's phone is on the network.
**Name the holes rather than pretending there are none:** a resident who left their phone in the car, a guest, a burglar carrying a phone that never associates. Every real security product has these gaps, and every assertion this agent makes carries them in its basis so they get said out loud.

We do **not** recognise individuals. Gait-based WiFi identification needs per-person enrollment, the same room it was trained in, and a subject who is walking - which our headline victim, motionless on a floor, is not.

**There is one thing it refuses to answer, and the refusal is deliberate.**
When the house is registered empty and one body is inside, the zone is attributable and it says so. When residents are also home, it knows there is an extra body and **cannot say which resolved presence is the stranger**, because that would need re-identification. It reports every occupied zone and states that it cannot pick one, rather than guessing and sending officers to the wrong room.
That is still an extremely useful answer, and it is the honest one.

The track is **sticky**: once declared it is held through clear ticks rather than dropped on the first one. A track that flickers off because one window missed a breath tells a responding officer the intruder left.

For the burglary incident type this is the agent that matters: **where the intruder is and where the resident is, tracked separately.**

### Coordination tier

#### agents/master **[tier 1]**

The incident coordinator. Classifies what is happening, aggregates what the sensing agents report, and routes to `caller` and `replay`.

Incident types: **Burglary and Fire.** **Both are user-triggered from the iOS app.**
Faint was the third until 2026-09-19; it went with fall detection.

The classification table, which `agents/master/classify.py` quotes in its own docstring and `docs/research/agent-briefs.md` holds in full:

| Observation | Verdict | Confidence |
|---|---|---|
| Elevated CO + a lost breathing signature | Fire, with someone in that room who may not be able to respond | 0.8 |
| Elevated CO + a still, breathing presence | Fire, with someone who is not moving. This cannot distinguish unconsciousness from sleep and says so | 0.65 |
| Elevated CO + every resolved presence up and breathing | Fire, and the moment to leave | 0.6 |
| Elevated CO + no presence resolved at all | Fire, occupancy unknown. Says explicitly that this is also what an unreachable or fully-discarded `people` looks like | 0.45 |
| Unexpected presence + residents also in the building | Burglary in progress with occupants home | 0.6 |
| Unexpected presence + house registered empty | Burglary, no occupants at risk | 0.7 |

**The top two rows are the ones to lead with, and they are the only rows built from two independent modalities**: CSI resolved the breathing, a separate simulated gas sensor read the air.
Two views of one CSI stream agreeing is not corroboration; this is.

`master` never initiates a 911 call. Sensing agents inform it continuously; it classifies and holds state; a human tap is what releases `caller` to dial.
Detections surface as alerts in the app so a person can act on them, which is the whole point of detecting them. They do not dial.
Classification table and the reasoning behind each combination: `docs/research/agent-briefs.md`.

This agent holds the only full picture, which makes it the place where verification must be strictest.
Every claim it accepts carries the identity of the agent that made it, that agent's Trust Index score at that instant, and a verification result. Anything unverifiable is discarded and logged as discarded.

##### Air quality, and what absorbing it cost

`master` reads a carbon monoxide sensor directly. Carbon monoxide, not oxygen, and **not from CSI**.

**No gas sensor is being purchased.** The reading is simulated, and that is disclosed rather than hidden.

Real here: the agent, its ANS registration, its certificate, its card, its place in the mesh, and the driver interface.
Simulated: the number. It carries the literal string `demo-trigger` so a simulated reading cannot be presented as measured by accident.

`environment` was its own agent until 2026-09-19. Absorbing it has a cost and the cost is named in `agents/master/environment.py` rather than glossed: **read locally, the reading skips the gate**, because there is no counterparty to authenticate.
What matters is that it is labelled unverified-by-construction rather than quietly inheriting master's FIDUCIARY standing. Its severity is capped at CORROBORATING no matter how high the number climbs, it is never speakable to an operator on its own, and the two corroborated Fire rows each require a CSI-derived respiration claim alongside it.

Why CO and not oxygen: **CSI cannot sense gas composition.** Oxygen absorption is a ~60 GHz phenomenon, which is why 802.11ad lives there; the BCM43455c0 is a 2.4/5 GHz radio. See `sensor/CLAUDE.md`.

CO is the better signal anyway. It is what incapacitates people in structure fires before flame reaches them, and it is the likeliest reason someone in a house that is not visibly burning stops responding.
`people` says a breathing signature went missing; the air reading proposes why. **Different modalities agreeing is real corroboration; two views of one CSI stream agreeing is not** - and that is precisely why this one is not a CSI consumer.

**Say it precisely: this is possible with the right hardware.** Never "CSI can detect gas." The claim is about the architecture, not the radio, and that distinction is what makes it survive a question.
Swapping in a real MQ-7 on the Pi's GPIO is a driver behind an interface that already exists, and nothing above it changes.
### Verification order

Derived from the `fraud.webmesh.ai` battery, which is thirteen ways of asking one question: **does this implementation treat a valid signature as authorization?**
Ten of the thirteen pass only if the answer is no. Full mapping in `docs/fraud-13.md`.

**This is implemented**, in `app/backend/hawkeye_backend/verification/`, with all thirteen shapes as passing tests.
It lives in the hub for now only because `master` does not exist yet; it is a standalone package with no FastAPI or hub imports, so moving it is an import change.
Do not write a second verifier. Import that one.

1. **Verify the envelope.** mTLS handshake, then JWS signature over the canonical payload. **Nothing downstream ever sees an unverified field.** Verify first, parse second, never the reverse.
2. **Check bindings.** Audience (this `master`, not any coordinator that will listen), zone scope, incident ID, nonce.
3. **Check schema version.** Reject an under-specified claim rather than interpreting it charitably. This will bite us for ordinary reasons: five agents at different build stages all weekend.
4. **Then, and only then, apply the profile gate.** What this agent's `recommendedProfile` permits this claim to trigger.
5. **Log what was discarded, with the reason.** Sealed via `agents/replay`.

Step 5 is not an afterthought.
"The agent that speaks to 911 only repeats claims it can cryptographically verify, and it tells you what it discarded" is the sentence that carries the submission, and the discard log is what makes it checkable rather than assertable.

Fail closed and fail **quietly**. A verifier that throws mid-incident is a worse outcome than one that rejects a claim; the battery's `corrupt_jws_attack` probe exists specifically to catch implementations that crash instead of refusing.

### The dispatch address

**The physical address is the single most important binding in this project, and it does not travel in a claim.**

Implemented as a commitment in `verification/card.py`: the card carries `sha256(salt || address)`, the salt and plaintext are sealed at registration, and `caller` recomputes over the address it is about to speak.
The card is world-readable, so publishing the street address of someone who cannot get off the floor would be a worse outcome than the attack. A test asserts the address is not recoverable from the published fragment; another asserts two installations at the same address produce different commitments, so cards cannot be linked.

It is bound at registration to the installation's ANSName and sealed into the transparency log.
No sensing agent, and no operator question, can change where a response is sent.

The reasoning is short: an agent that can change the dispatch address is a swatting tool, and no amount of claim verification upstream matters if the destination is forgeable.
`fraud.webmesh.ai` probes the same property under `payTo_binding_check`, where the asset at risk is a settlement address rather than a street address. Same structure, higher stakes.

Also generate a `traceparent` at incident open and propagate it to every agent. See the transparency-log section of `ans/CLAUDE.md` for why.

Classification is the interesting part and should be visible.
Elevated CO plus a breathing signature that has gone missing is a fire with an occupant who may not be able to respond, not two separate incidents.
An unexpected presence plus a resident in a different room is a burglary, not a visitor.
Show that reasoning; it is what makes the system look like it is thinking rather than switching.

### Human-boundary tier

#### agents/caller **[tier 1]**

**The agent that talks to humans**, and since 2026-09-19 that is both of them: the 911 operator by phone through ElevenLabs, and the resident in the iOS app. The only agent that acts on the outside world.

The phone half is below; the resident half is under "the resident's side of the call".

**Outbound.** Reports the incident in plain English. Every claim it speaks has a verified source or it does not get spoken.

**Inbound.** The operator talks back, mid-call, in English.
"Is the child still breathing?" "Anyone outside the front door?" "How long since you had breathing from that room?"
`caller` parses each question, fans it out through `master` as ANS-verified queries, and speaks the result.

Rules for the inbound path:

- **Answer from a live verified query, not cached state.** The operator asks now because the answer may have changed, and an agent trusted ninety seconds ago may not be trusted now.
- **"I don't know" must be available and must be used.** An agent that invents an answer for a dispatcher is worse than one that admits a gap.
- **An operator question must never widen what the agent will trust.** Pressure from an authority figure is a social-engineering vector, and an agent that relaxes verification because someone official-sounding asked is exactly the failure this project exists to prevent. The bar does not move.
- Keep answers short. This is a dispatcher on a live call, not a chat window.

Operator speech also drives the user's phone. Keywords like "I've dispatched units" or "they're two minutes out" fire notifications to the resident, through the same agent - see the resident's side of the call, below.
Match on meaning, not exact strings; a dispatcher will not say the phrase you hardcoded.


### The resident's place on the call

Settled 2026-09-19. **The call is a server-side conference bridge. The resident's phone is not a leg of it by default.**

```
conference bridge (backend)
 |- agents/caller        agent voice
 |- 911 operator         outbound leg
 |- resident             added on demand, never by default
```

This is not an optimisation. Putting the call on the resident's phone means iOS owns the audio routing, and **call audio cannot be silenced below a floor**. During a burglary a speaking phone gives away a hiding person's position. Keeping them off the bridge by default means there is no audio stream to suppress.

#### Three participation modes

| Mode | Mic | Audio out | Used for |
|---|---|---|---|
| **Watching** | off | none | Default for Burglary. Transcript only. |
| **Whispering** | **open** | **none** | Hiding, but needs to be heard |
| **Full voice** | open | on | Fire, or Burglary once safe |

**Whisper mode is the one worth building.** The resident's voice reaches the call; nothing comes back through the speaker. They speak and read the replies on screen.

Someone in a closet can say "he is in the kitchen, I am upstairs" in a whisper and stay silent to the room around them. Typing cannot carry urgency or let a dispatcher hear a tone of voice. This can, without the phone making a sound.

#### The bridge switch matrix

Every leg has an independent **send** and **receive**. Whisper is simply send-only.

| Leg | Send (heard by others) | Receive (hears the mix) |
|---|---|---|
| `agents/caller` | on | on |
| 911 operator | on | on |
| resident - watching | off | off |
| resident - **whisper** | **on** | **off** |
| resident - full voice | on | on |

**Silence is enforced at the bridge, not on the device.** If audio is transmitted to the phone, iOS decides how to play it and the floor is not zero. If the bridge never sends it, there is nothing to play.
That is the difference between muted, which is a promise the phone makes, and silent, which is a fact about what is on the wire.

Switching modes is flipping one bit server-side. The app never has to be trusted to stay quiet.

#### Whisper mode, step by step

The app holds a WebRTC leg to the bridge from the moment the call starts, **send off and receive off**. No ring, no call UI, no sound.

1. Resident taps **Whisper**
2. App starts mic capture
3. Bridge sets `send = on` for that leg
4. Operator hears the resident
5. Bridge still sends nothing back. **The app never subscribes to an inbound audio track**, so there is no stream to render even by accident
6. `caller` announces: "The resident is joining but cannot hear you. They are hiding and will respond by voice only."
7. Resident follows the conversation on the transcript

Since nothing is played, there is no echo path and no acoustic echo cancellation to configure.

**Known cost, state it rather than hide it:** whisper is half-duplex. The resident speaks in real time but reads replies with a second or two of transcription lag, so it behaves more like a radio exchange than a phone call.
That is the correct trade against a phone that reveals where someone is hiding, and they can switch to full voice the moment it is safe.

#### Why whisper mode is possible

The resident's leg is **in-app audio over WebRTC to our own bridge**, not a phone call.

A phone call hands audio routing to iOS, which is the source of the volume floor, plus a connect tone and call UI that are noisy in their own right. An app that owns its `AVAudioSession` opens the microphone and simply never renders the far-side stream. Skip CallKit so it does not present as a call.

Output-silent is not a mute being fought. There is nothing being played.

**Fallback if in-app audio does not fit the remaining time:** PSTN dial-in for full voice, whisper mode on the roadmap. Whisper is the feature no existing product has, so cut it last.

#### Taking over

**One button, permanently on screen, large: TAKE OVER.**

- **Hold to confirm, 1.5s**, consistent with every other risky control in the app. Nothing in this UI misfires from a stray palm or a pocket.
- The agent goes silent **mid-sentence**, not at the end of its thought.
- It does not resume on its own. Handing back is a separate deliberate action.
- **Voice barge-in is the instant path and is not held.** A human starts speaking, the agent yields immediately. That is what makes it safe for the button to be deliberate, so barge-in is load-bearing rather than a nicety.

Add **voice barge-in** alongside the button: if a human starts speaking, the agent yields immediately.

**Rule: the agent never talks over a human.** Not the operator, not the resident. Either speaks, it yields. That one rule covers most of the failure modes here.

After takeover the agent stops speaking **on the call** but keeps feeding the app: CO reading, room, respiration, and the seconds since a breathing signature was last resolvable. **The resident becomes the voice and the agent becomes the teleprompter.** That is better than the agent guessing what a frightened person wants said.

Three controls, kept visually distinct because someone panicking will hit the biggest one:

| | Effect |
|---|---|
| **Take over** | Agent silent, resident speaks. Call continues. Hold 1.5s in the app. |
| **End call** | Hang up. Hold-to-confirm in the app, and **never a silent drop**; see false alarms below. |
| **Automatic yield** | Agent stops the instant any human speaks. Not a button, so it cannot misfire, and it is the instant path when the hold is too slow. |

#### Who may change the mode

**Automation may only ever move toward quieter. Going louder requires a human hand.**

Guessing wrong toward silence costs one tap. Guessing wrong toward audio makes a phone audible while someone is hiding. The two failures are not comparable, so inference is trusted in one direction only.

- `master` may set **receive off** on its own, from the incident type or from the resident's typed context.
- **Send on is never automatic.** Opening a microphone to emergency services is a human decision.
- `caller` may surface an operator's request to speak. **The operator requests; only the resident grants.**

Full UI treatment, including labelling modes by consequence rather than by our jargon, is in `app/CLAUDE.md`.

#### Ending a call, and false alarms

**An abandoned 911 call causes a dispatch.** PSAPs treat a dropped call as a real emergency and will call back, and send units when they cannot reach anyone.

So `End call` must never be a silent hang-up. Before the leg closes, `caller` says what happened:

- "This incident is being cancelled by the resident. There is no emergency at this address."
- Or, if the resident is unreachable or cannot speak, it stays on and says so rather than dropping.

An accidental raise that is immediately cancelled should cost the dispatcher ten seconds, not a truck.
This is also why raising an incident is hold-to-confirm in the app: the cheapest false alarm is the one that never gets placed.

#### Announce every transition

**No unexplained voice changes on a call**, on a project whose threat model is impersonation. A dispatcher who hears the voice swap with no explanation has every reason to doubt the call.

- "The resident is taking over."
- "The resident is joining. They can hear you."
- "The resident is joining but cannot hear you. They are hiding and will respond by voice only."

That last line is real information. It tells a dispatcher there is an active threat, the caller is concealed, and how to speak to them. Silent 911 is a known hard problem; Text-to-911 exists but PSAP coverage is uneven.


This is the fiduciary agent. It speaks to emergency services on a human's behalf. Treat it accordingly.
#### The resident's side of the call

Merged into `caller` on 2026-09-19, and the merge is principled rather than a headcount cut: **`caller` is the agent that talks to humans**, and there are two of them on a live incident.
The operator hears it by phone; the resident reads it in the app. Both are the same boundary - plain English, no ANS, a person on the far end - and both are fed by the same verified state.

Keeping them in one agent removes a failure this system cannot afford: two independent agents translating the same incident could tell the operator and the resident different things. One agent holds one picture and says it twice.

Two jobs, and they are the same job: telling a frightened person what to do next.

1. **Relay.** What the operator and responders have said, translated into what it means for the user. "Units are two minutes out. Stay where you are, unlock the front door if you can do it safely."
2. **Safety instructions.** What to do in the situation at hand. Get out and stay out, stay low, do not confront anyone, wait for responders.

**There is no patient-care protocol in the table, and the absence is deliberate.**
CPR and the recovery position went with the Faint incident type on 2026-09-19.
Neither surviving incident type is one where staying to help is correct guidance: during a fire the resident's protocol is to leave and stay out, and during a burglary it is to stay hidden and not confront anyone.
Telling a resident to stay in a burning building and do CPR would be a worse instruction, not a missing one.

Handle this carefully. Safety instructions delivered badly are a real-world harm, not a demo bug.

- Stay inside well-established public guidance. Fire-ground protocol, and the dispatcher's own words. Do not improvise medical advice.
- **Always defer to the operator.** If the dispatcher is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained for exactly this and the agent is not. This is enforced: relaying anything sets a deferral flag, and from that point the agent relays rather than generates.
- Never tell a user to do something that could hurt them or the person they are worried about. The protocol table carries the do-nots explicitly rather than leaving them absent: do not go back into a fire, do not go looking during a burglary, do not confront anyone.
- Say "wait for responders" when that is the right answer, which is often.

**`agents/caller/guidance.py` is the only place medical text exists in the entire system.** The iOS client contains none and must not acquire any: hardcoding first-aid copy in a view puts it outside the one component that gets reviewed against these rules.

The relay half is the high-value one. The safety-instruction half is the one to cut if time runs out.
#### agents/replay **[tier 2]**

The incident recorder. Logs what happened, in order, with who said it and whether it verified.

Promoted from tier 3 on 2026-09-19. With five agents rather than nine there is more riding on each remaining hop being auditable, and this is the agent that makes them auditable.

Movement through the house, sensing claims, verification results, **every discard with its reason**, what the caller told the operator, what the operator said back, what guidance the user received.
Hash-chained locally, then sealed into the SCITT transparency log, where entries cannot be altered after the fact.

**The chain and the seal are different properties and the difference is load-bearing.** The local hash chain makes tampering detectable by whoever holds the record. The transparency log is what makes the record verifiable by someone who does not already have it. `seal()` returns `transparency_receipt: None` until that hop is wired, rather than implying a receipt it does not have.

Discards are recorded with exactly the same weight as acceptances. "It tells you what it discarded" is the sentence that carries the submission, and a record that only keeps what was accepted cannot support it.

Two audiences:

- **Detectives.** After a burglary, a tamper-evident record of where the intruder moved through the house and when is genuinely useful evidence.
- **Accountability for the system itself.** If the agents got something wrong, the record shows which agent said what and on whose authority.

This is also where non-repudiation lives. The operator cannot verify us live, but an investigator can verify the record afterward, and swatting investigations are entirely post-hoc.

This resurrects the superseded flight-recorder idea in its proper place. The idea was sound; it was a feature rather than a product.

## The trust problem

The 911 operator talks to our agent in plain English and the agent talks back. That conversation is two-way.
What it is not is an ANS channel, because the far end is a person on a phone. The same is true of the user in the app.

**So neither human can verify us, and we must not claim otherwise.**
A voice asserting "this call is cryptographically verified" is worth exactly what a voice asserting "there is a fire" is worth.

ANS governs every machine hop behind those voices, which is where it belongs.

### Primary: agents verifying agents

This is the submission, and it is the track owner's own model: client agent to server agent, his shopper-and-bank example.

`master` is the client. `people` and `intruder` are servers. `caller` and `replay` are clients of `master` in turn.

Before anything reaches a human, its source is verified.
The system is about to tell emergency services that a child is unresponsive in a back bedroom. If the agent that produced that claim is not who it says, or is running code that changed since it registered, this verification is the last thing standing between a compromised sensor and an armed response to someone's address.

Use the mechanisms rather than mentioning them:

- **Version-bound certificates** record the specific code running at registration. A sensing agent whose fingerprint drifted mid-run gets distrusted and discarded. Strongest single use of ANS available to us, and cheap to demo.
- **Trust Index `recommendedProfile`** gates what a claim is allowed to trigger.
- **SCITT transparency log** seals the record, via `replay`.

| Profile of source agent | What master does with its claims |
|---|---|
| UNTRUSTED | Discards. Logs. Does not relay. |
| READ_ONLY | Corroboration only, never sole basis for a call. |
| TRANSACTIONAL | Relays as a reported observation, attributed. |
| FIDUCIARY | Relays as an assertion the system stands behind. |

This runs continuously, not once at startup. Every operator question fans out into fresh verified queries, so ANS is load-bearing throughout the call.

The sentence that carries it:

"The agent that speaks to 911 only repeats claims it can cryptographically verify. Everything else it discards, and it tells you what it discarded."

### Secondary: non-repudiation

The incident seals into the transparency log as it happens. The operator cannot check it live; an investigator can check it afterward.

We do **not** claim this prevents a malicious call. It makes one attributable, which beats tracing a spoofed number.

### What we do not solve

Say it before a judge does.

A malicious agent can still place a 911 call in a convincing synthesized voice and no operator can tell.
Closing that needs the PSAP side to participate, and no dispatch center runs software we can ship to.

It is also the right closing line: the moment a dispatch center can resolve an ANSName, live verification falls out of what is already built here.

## Threat model

The Infinite Impostor, from Zafar et al. 2026: an agent that interposes itself between two parties who already trust each other.

Instantiated here as a compromised sensing agent between a real house and a real `master`.
Every participant behaves correctly. The house is real, the emergency may be real, `caller` is doing its job faithfully.
The only defect is that one source is not what it claims, and the cost is an armed response sent on fabricated evidence.
The messages are indistinguishable from legitimate ones, which is the paper's point: detection-based defenses are finished, and only domain-anchored identity helps.

In the 2026 OWASP taxonomy this is ASI07 (insecure inter-agent communication) escalating into ASI08 (cascading failures) and landing as ASI09 (human-agent trust exploitation), which is the one that costs a real person a police response rather than money.
Full mapping, plus MAESTRO layers, OSI coverage, and the sandbox-breakout material the track owner asked for, in `docs/threat-landscape.md`.

## Hard requirement

**These agents must be hosted on the internet and reachable.**
The track owner said this directly. Localhost does not count.

**Fixing the broken deployment is the highest-priority open item.** Nothing else matters until agents answer at public ANSNames.

Host them before they are finished. Five empty agents reachable tonight beats five complete agents on a laptop Sunday morning, because the deploy path is where the hours disappear.

Five is also materially easier to deploy than nine was, and that is a real argument for the merge rather than a consolation: five hostnames, five certificates, five cards to keep current, and five things that can be stale on the surface the judge inspects first.

All five support A2A and MCP, consistent with the live agents at webmesh.ai.
Each publishes an agent card, and the cards must be kept current. Public agents surface on GoDaddy's Trust Index, which the judge maintains, so a stale card is a visible defect on the most-inspected surface.

## The demo

Two of them, carrying different claims. See `media/CLAUDE.md` for the split.

**The video, recorded at home.** Live CSI, real walls, a real person whose breathing signature goes missing. The only honest venue for the physical claims.

**The live demo at judging.** This is the one the track is actually scored on, and it needs no hardware:
the agents are hosted and reachable, so ANS verification, the agent cards on the Trust Index, the `fraud.webmesh.ai` probes, the refusal, the ElevenLabs call, and the operator question fan-out all run from a laptop on any network.
Sensing input comes from replayed CSI captured at the house. Downstream agents cannot tell the difference.

**Bring the Pi and router to the table anyway.** Not for the full pipeline, which the environment cannot support, but for one scoped live bit that does work in a crowded hall: movement.
No calibration, no baseline, no walls. Someone waves a hand near the router and the signal visibly responds. A judge can try it themselves.

This is not a consolation prize, and there is a principled reason it works: **motion sensing is environment-independent.** It needs no baseline at all, which is exactly why it survives a room we did not calibrate in.
Counting and localization are the capabilities that need a reference, and they are the ones that stay in the video.

Worth knowing if a judge asks why you are not demoing the rest: a baseline captured in a hall decays as the hall fills, because bodies are reflectors and the static multipath structure you calibrated against stops existing. Occupancy also assumes a bounded space, and an open hall has no wall defining who is inside.

Full sequence, as filmed:

1. `people` loses a breathing signature. It had one in the main bedroom and it no longer does, and the clock starts from the last resolvable frame. The app raises an alert; **no call is placed.**
2. `intruder` and the roster corroborate. **Keep the sensed claim to one resolved presence**, and take the headcount from the roster rather than the radio: two residents registered, both phones associated, and an occupant in the west bedroom who was breathing at 6 a minute. An exact sensed count of two or three is beyond a 1x1 link; see the counting limits under `agents/people`.
3. **A human taps Fire.** This is the only thing that releases `caller` to dial, and saying so on stage is a feature, not an apology.
4. `master` classifies, verifies every source, discards what it cannot verify, and routes.
5. `caller` dials. ElevenLabs voice to a human operator, reporting only verified claims - including the forty seconds that elapsed before anyone tapped.
   The line that wins the demo is about **one** person: "I had a breathing signature from an occupant in the west bedroom four minutes ago and I do not have one now, and that is not the same as them having stopped breathing." That needs exactly one resolved presence, which is what the hardware can give.
6. The resident watches a live transcript on their phone while `caller` tells them what to do. One agent, both audiences, one picture of the incident.
7. **The operator asks a follow-up in plain English.** "Is the child still breathing?" The question fans out as ANS-verified queries, live, and comes back as a spoken answer. This is the beat that shows ANS working during the call rather than before it.
   Then **the resident taps TAKE OVER and the agent goes silent mid-sentence.** Five seconds of footage that answers the room's biggest doubt about this entire project: what if the AI says something wrong. A human starts the call, a human can take it, a human can end it. The agent only ever holds the microphone on loan.
8. **Then run it again with a compromised sensing agent** and show the system refusing to escalate on its claims.
   Build the attacker locally, in the thirteen shapes `fraud.webmesh.ai` uses. **His battery cannot be aimed at us** (no target parameter, hardwired to `supplier.webmesh.ai`, verified 2026-09-19), so we implement the probes rather than invoke them, and we say that plainly rather than implying we ran his suite.
   Stage `underpay_valid_sig`: a genuinely valid signature that must still be refused. It demonstrates the difference between authentication and authorization to a room, and its Hawk Eye analogue lands on a non-technical judge immediately. Per-probe translations in `docs/fraud-13.md`.
9. **Then the beat that is better than the refusal.** Point `agent.webmesh.ai verify_agent` at our five hostnames, live, and let the judge's own verifier confirm our identity in front of him. It checks DNS, DNSSEC, TL proof, and our published cards, then sends a live A2A message. Preparation is entirely card work: `ans/CARD.md`.

Step 8 is the submission. Steps 1 through 7 are the setup. Step 9 is the one a judge cannot argue with, because he wrote the verifier.
Step 7 is what makes the architecture legible.

**Step 3 is not a gap in the demo, it is a claim.** Say it out loud: Hawk Eye does not call 911 by itself, a person does.
Every other agent demo this weekend argues its agent deserves more autonomy. Ours draws the line in the one place where drawing it is obviously correct, and a judge who has spent the weekend hearing about agent sandbox breakout will notice.

**Steps 4 through 9 are the live venue demo**, driven by replayed CSI. Steps 1 to 3 are the video's job, because they are the ones that need a real house.

## Build order

**`agents/TODO.md` is the work queue**, with every item's seam, what it blocks,
and what blocks it. This is the summary.

**Done:** all five agents with their domain logic; the wire between them
(pull-only A2A, server-issued challenge, claims verified against each producer's
published trust card); both cards per agent as byte-stable artifacts; the
verification order's authentication and authorization halves, with the thirteen
battery shapes and three challenge probes passing. 74 tests.

In dependency order rather than severity order:

1. **Deploy.** Five agents reachable at public names. The hard track requirement,
   and nothing below it is cheap until it is done.
2. **Register the domain, then the agents.** DNSSEC on.
3. **Real certificates.** `keys[].x5c` is not validated today, so we are Bronze.
   DANE for Silver, a stapled receipt for Gold.
4. **Certificate drift detection.** The cheapest and most demonstrable use of
   ANS available to us, and currently not surfaced at all.
5. **Live Trust Index lookups**, plus a safety-dimension evidence producer -
   the strongest available differentiator on the track.
6. **Master's API for the hub.** It serves none of the five endpoints
   `app/backend` is written against, so the app has no path to the real mesh.
7. **Wire the incident lifecycle.** `caller` has no master reference, `replay`
   is never called, and two implemented security properties are switched off in
   production because nobody sets the field.
8. **The impostor, as a real process** rather than an in-process test.
9. ElevenLabs voice, then the bridge. Whisper mode is cut last.
10. Real CSI, and the four sensing thresholds tuned against it. **Last on
    purpose.** The agent layer must never block on the hardware.

## Roadmap, not this weekend

Worth one line on the Devpost page because it shows the architecture has somewhere to go.

- **Per-person agents.** Each resident gets a dedicated agent holding their context: medical conditions, mobility, where they usually sleep. The current design is a step toward this, not away from it.
- Live PSAP-side ANS resolution, which closes the gap named above.
