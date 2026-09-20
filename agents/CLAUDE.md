# agents/

The seven ANS-registered agents behind Hawk Eye. All of them live on the user side, inside the home.
This is the GoDaddy track submission. Everything else supports it.

Read the root `CLAUDE.md` first, then `docs/PIVOT.md` if you have prior context on this repo. `agents/README.md` is how to run them; this file is the contract.

**Status, after the 2026-09-19 camera pivot.**
The trust layer is done and is untouched by the pivot: `master` issues a challenge, producing agents sign their current observation against it, and every claim is verified against the key the producer publishes in its own trust card before anything downstream sees a field.
Verified end to end over real HTTP in `tests/test_wire.py`, including the refusals: wrong key, unregistered agent, lookalike ANSName, replayed proof.

What the pivot changes is the cast, not the wire.
`people` becomes `presence` and loses everything but motion and device association. `master` loses the gas reading. Two new agents arrive, `shutter` and `vision`, and one of them can move a physical object.

What is still missing is deployment: real certificates, a registered domain, mTLS at the edge, and the agents reachable at public ANSNames.

## Why seven agents instead of one

A judge will ask this. The answer is **context separation and speed, not redundancy.**

Each agent holds one narrow context and answers one kind of question, so none of them carries a prompt describing the whole system.
Narrow context is faster, cheaper, and less likely to hallucinate across concerns.
They run in parallel, so an operator's question fans out and returns at the speed of the slowest single answer rather than the sum of them.

It is also what makes the ANS story real rather than decorative.
One agent verifying itself is theater. Seven independently registered agents that must verify each other before anything reaches a dispatcher, or before a lens is uncovered, is the track's actual model.

## Nine, then five, then seven

The roster was nine until 2026-09-19, when it was merged to five. It went to seven the same day, when the project pivoted to a camera.
Both moves follow one principle and it is worth being able to say it in a sentence.

**An agent is a context boundary, not a task.**
Two components that read the same input, hold the same state, and always run in the same order are one agent with two steps. Splitting them buys extra deployments, extra certificates to keep current, and extra chances to disagree about what the radio said.

### The merge, nine to five

| Was | Went to | Why |
|---|---|---|
| `biometrics` | `people` | Personhood is what makes a presence a person |
| `occupancy` | `people` | Same CSI window, same rolling baseline, same tick |
| `collapse` | `people` | A fall is a state a *person* is in |
| `environment` | `master` | A sensor attached to the host has no counterparty to authenticate |
| `guidance` | `caller` | `caller` is the agent that talks to humans, and there are two of them on a live incident |

Fall detection was then cut outright, and the `collapse` reader deleted with it.

### The pivot, five to seven

| Added | Why it is not a merge candidate |
|---|---|
| `shutter` | Shares no input with anything. One grant in, one position out, and no knowledge of what a camera is for. Folding it into `vision` makes the authorization gate internal to the agent that benefits from it, which is the structure this whole project argues against |
| `vision` | Different hardware, different failure modes, different cadence, and it is gated on a claim from another agent. Nothing it does resembles what `presence` does |

### And what the pivot deleted

`environment` went with the gas reading it absorbed, so `master`'s only unverified-by-construction input is gone.
That is a strict improvement to the trust story: **every input `master` now acts on came through the gate.**

The respiration, personhood and counting logic inside `people` went with the pivot, and what remains was renamed `presence` to stop the name implying a capability the agent no longer has.

**What none of this touched is the line the ANS story runs along.**
Every hop that carries a claim from something that senses, to something that decides, to something that acts, is a hop between independently registered agents.
The pivot added a hop of exactly that kind, and it is the best one in the project, because at the end of it something physical moves.

## Always running

**Every agent runs continuously.** Nothing spawns on incident.

This is a requirement, not an optimization. It is what allows the system to notice things nobody asked it to look for:
motion in the house at 3am that no registered device accounts for, and a shield that should be shut and is not.

An architecture that only wakes on a button press cannot do the thing that makes this project worth building.

It is structural in the code rather than conventional: `agents.core.base.Agent` has no "handle a request" entry point, only a `tick` that runs whether or not anyone is asking.

## How they talk to each other

Settled 2026-09-19. **Pull-only, A2A JSON-RPC, with a server-issued challenge.**

```
master ──POST /a2a {nonce}──►  presence   "what do you have right now?"
       ──POST /a2a {nonce}──►  intruder
       ──POST /a2a {nonce}──►  vision
           ◄── SignedClaim[] + PossessionProof, bound to that nonce
```

### Pull, not push, and the reason is binding strength

`master` asks; sensing agents answer. Nothing is pushed.

**With pull, master controls the nonce**, so a claim is bound to a specific question asked at a specific moment. With push the producer picks its own nonce and master can only check it has not seen it before, which is strictly weaker: a compromised sensing agent could prepare a batch of plausible claims in advance and fire them at an incident. Under pull it cannot, because it cannot guess the challenge.

It also collapses two code paths into one. The steady-state tick and the operator fan-out are the same mechanism, so the beat that matters in the demo is exercised continuously rather than only during a call.

The cost is up to one second of detection latency. Against the three-second motion-to-wrist budget in the root `CLAUDE.md`, one second is the largest single item and is why `presence` ticks fastest of the seven.

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
              router ──► sensor/ ──► CSI
                                      │
                                      ▼
                                  presence
                      something moved, which zone, which
                      registered devices are attached to it
                                      │
                                  ANS │
                                      ▼
                                  intruder  ◄───── roster + device association
                          motion no registered device accounts for
                                      │
                                 ANS  │
                                      ▼
                             master (coordinator)
                      verifies, classifies, aggregates, routes,
                      and issues the shutter grant
                          │                          │
                     ANS  │                     ANS  │
                          ▼                          │
                       shutter                       │
              SG92R, 90°, shield clears the lens,    │
              position attested and signed           │
                          │                          │
                     ANS  │ open                     │
                          ▼                          ▼
                       vision  ────────────────► master
              Gemini Live narration + mp4 to disk     │
                                          ┌──────────┴──────────┐
                                     ANS  │                     │ ANS
                                          ▼                     ▼
                                       caller                replay
                                          │      │              │
                           ElevenLabs     │      │ watch + iOS  │ sealed log + video
                              voice       ▼      ▼              ▼
                                911 operator   the user   Resend ──► police
```

**The boundary is the point.**
Human to agent is plain English, in both directions, on both ends. There is no ANS there and there cannot be, because the far ends are people.
Agent to agent is ANS, every hop.

`caller` is the translator, in both directions and to both audiences.
Nothing crosses a human boundary that was not verified first, and nothing physical moves that was not authorized first.

### The one place the pull rule inverts

Everywhere else `master` asks and producing agents answer, so `master` controls the nonce.

`shutter` is the exception, because here `master` is the one asking for something to happen.
So **`shutter` issues the challenge.** The invariant is not "master holds the nonce", it is **"the verifier holds the nonce"**, and this is the direction that makes that explicit.

Two round trips, DPoP-shaped: `shutter.challenge` returns a single-use nonce with a ten-second TTL, then `shutter.open` carries a grant covering it.
On localhost the extra trip costs under a millisecond against an 800ms budget.

Full contract, refusal table and limits: `shutter/CLAUDE.md`.

## The cast

Seven agents. Priority tiers are marked; build in tier order when time is short.

**Domain research for every agent is in `docs/research/agent-briefs.md`**: the thresholds each one acts on, the statistics behind it, and what it must not claim.
Read your agent's brief before writing it. The "must not claim" lines are the ones that lose the judging conversation.

They are also **published on each agent's card** under `x-hawkeye.mustNotClaim`, and each one has a test in `agents/tests/`. A limit that only exists in prose is a limit nobody checks.

### Sensing tier

#### agents/presence **[tier 1]**

**Was `agents/people` until the pivot, and it lost most of itself.**

Two questions, and no others:

1. **Did something move, and in which zone?**
2. **Which registered devices are attached to the network right now?**

That is the entire contract. It is a small agent on purpose.

| Field | Meaning |
|---|---|
| `presence.motion` | Boolean. A CSI perturbation crossed the threshold in this tick |
| `presence.zone` | Which enrolled zone. From the enrollment walk, never inferred |
| `presence.devices_associated` | Which roster devices are currently on the network |
| `presence.since_s` | How long motion has been continuously present |

**What it no longer does, and must never be described as doing:**
respiration, breathing signatures, personhood, headcount, localization beyond a zone, gait, identity, or anything about whether a person can respond.
All of that went with the pivot. See `docs/PIVOT.md`.

The reason motion survived when everything else was cut is that **motion sensing is environment-independent.**
It needs no baseline, which is exactly why it works in a crowded hall we did not calibrate in, and why it is the one live CSI beat that survives the judging table.

**It cannot tell a person from a curtain.** It never could. Before the pivot, respiration was the personhood test; now the camera is, and the camera is better at it and can be checked afterward.
So `presence.motion` is explicitly **not** a claim that a person is present, and `master` must not treat it as one. It is a reason to look.

#### agents/intruder **[tier 1]**

Decides whether motion is accounted for.

Distinct from `presence` in the question it asks, which is why it stayed separate through both the merge and the pivot. `presence` says something moved and which devices are on the network; `intruder` says **whether those two facts are consistent with each other.**

It does not share an input. `presence` reads the radio; `intruder` reads `presence` plus the network roster.
Different evidence, different failure modes, and a claim from each corroborating the other is worth something.

**The decision rule, unchanged by the pivot: roster plus device association.** Full reasoning in `docs/research/identity.md`.

```
presence:   motion in the living room
Roster:     2 registered residents      (configuration, not discovery)
Associated: 0 resident phones on the network
            -------------------------------------
            motion no registered device accounts for
```

The household is known, not discovered. Unaccounted motion is motion with no corresponding device.

This survives the question a judge will certainly ask - how do you tell a burglar from a roommate - because the roommate's phone is on the network.
**Name the holes rather than pretending there are none:** a resident who left their phone in the car, a guest, a burglar carrying a phone that never associates.
Every real security product has these gaps, and every assertion this agent makes carries them in its basis so they get said out loud.

**The pivot makes the holes much cheaper.**
Before, an unaccounted presence was the end of the chain and had to be right.
Now it is the trigger for a camera, and the camera resolves the ambiguity within seconds. A resident who left their phone in the car gets a shutter opening and a notification saying it is them, not a police call.
That is the single biggest practical improvement the pivot buys, and it is worth saying on stage.

We do **not** recognise individuals from the radio. Gait-based WiFi identification needs per-person enrollment and the same room it was trained in.

The verdict is **sticky**: once declared it is held through clear ticks rather than dropped on the first one, so a shutter does not flap.

### Actuation tier

#### agents/shutter **[tier 1]**

**New with the pivot, and the best ANS beat in the project.**

One GPIO pin, one TowerPro SG92R, one opaque shield in front of a camera lens.
It moves that shield for exactly one reason: a grant from `master`, signed, bound to a nonce `shutter` itself issued, verified against the key `master` publishes in its own trust card.

Everything else is a refusal, and a refusal is an observation rather than an error: **the lens stays covered and the agent says why**, signed, into the sealed record.

Refusals it owes tests for: `unregistered_issuer`, `lookalike_ansname`, `stale_nonce`, `replayed_grant`, `expired_grant`, `unknown_action`, `untrusted_profile`.

There must be **no code path from a failed verification to a GPIO write.** Enforce it structurally: the write lives behind a function taking a `VerifiedGrant` type that only the verifier can construct.

Full contract, grant fields, wiring and limits: `shutter/CLAUDE.md`.

#### agents/vision **[tier 1]**

**New with the pivot. The primary sensor.**

A Logitech USB camera on the Pi, doing two independent things:

- **Narrating**, through a Gemini Live session held open for the incident, producing the running description `caller` reads to the operator
- **Recording**, as continuous ten-second mp4 segments to local disk, which `replay` hashes into the chain and emails to the police

Those two paths share a camera and nothing else. **The recording never depends on the network**, because footage is the thing worth having when the WiFi drops mid-incident.

**The rule that governs it: `vision` produces no claim unless it holds a current, verified attestation from `shutter` saying the shield is clear.**
Not a config flag it sets itself. A signed attestation from a separate agent.
Without one it returns `Unknown(field="vision.description", reason="shield_closed")`, which the existing `Agent.blind()` helper already models.

Its limits are the most important thing about it and they live in `vision/CLAUDE.md`. The short version:
no face recognition against any database, one fixed camera seeing one room, roughly one observation per second, and every narration labelled `source: generated`.

### Coordination tier

#### agents/master **[tier 1]**

The incident coordinator. Classifies what is happening, aggregates what the producing agents report, routes to `caller` and `replay`, and **issues the shutter grant.**

**One incident type: Intrusion.** Burglary and Fire were the two until the pivot; Fire went with the simulated gas sensor. Faint went with fall detection earlier the same day.

The classification table, which `agents/master/classify.py` quotes in its own docstring and `docs/research/agent-briefs.md` holds in full:

| Observation | Verdict | Confidence |
|---|---|---|
| Unaccounted motion + camera shows a person who matches no enrolled resident | Intrusion, a person is in the building | 0.85 |
| Unaccounted motion + camera shows a person who matches an enrolled resident | Not an intrusion. A resident without their phone. Notify, do not escalate | 0.8 |
| Unaccounted motion + camera shows no person | Unresolved. Says explicitly that this is also what a curtain, a pet, and a stale shutter attestation look like | 0.3 |
| Unaccounted motion + shutter refused to open | **Nothing is claimed about the room.** The refusal itself is the finding, and it is reported as a system event, not an incident | n/a |
| Unaccounted motion + camera unreachable | Falls back to the pre-pivot claim: motion no device accounts for, and nothing more | 0.5 |

**The second row is the one to lead with in the pitch**, because it is the row where the system declines to escalate.
A design that only has a path to "call the police" is a design nobody should install.

**The fourth row is the submission.** A shutter that refused leaves `master` with no visual claim at all, and `master` must say so rather than reaching for the radio and dressing a motion event up as a person.

`master` never initiates a 911 call. Producing agents inform it continuously; it classifies and holds state; **a human tap on the watch is what releases `caller` to dial.**
It does open a shutter without a human, which is the only automatic physical action in the system, and the whole of `shutter/CLAUDE.md` exists to make that safe.

This agent holds the only full picture, which makes it the place where verification must be strictest.
Every claim it accepts carries the identity of the agent that made it, that agent's Trust Index score at that instant, and a verification result. Anything unverifiable is discarded and logged as discarded.

##### What the pivot gave master back

Before the pivot, `master` read a simulated carbon monoxide sensor directly, which meant **one input skipped the gate**, because master was both its producer and its consumer.
It was labelled unverified-by-construction and capped at CORROBORATING, and that was the honest handling of a genuine weakness.

The gas sensor is gone. `agents/master/environment.py` is deleted.

**Every input `master` now acts on arrived through the verification gate**, from an independently registered agent, over the signed transport.
That is a cleaner story than the one it replaces, and it costs a sentence to say: we removed the only thing in the system that could not be verified.

### Verification order

Derived from the `fraud.webmesh.ai` battery, which is thirteen ways of asking one question: **does this implementation treat a valid signature as authorization?**
Ten of the thirteen pass only if the answer is no. Full mapping in `docs/fraud-13.md`.

**This is implemented**, in `app/backend/hawkeye_backend/verification/`, with all thirteen shapes as passing tests.
It lives in the hub for now only because `master` does not exist yet; it is a standalone package with no FastAPI or hub imports, so moving it is an import change.
Do not write a second verifier. Import that one.

1. **Verify the envelope.** mTLS handshake, then JWS signature over the canonical payload. **Nothing downstream ever sees an unverified field.** Verify first, parse second, never the reverse.
2. **Check bindings.** Audience (this `master`, not any coordinator that will listen), zone scope, incident ID, nonce.
3. **Check schema version.** Reject an under-specified claim rather than interpreting it charitably. This will bite us for ordinary reasons: seven agents at different build stages all weekend.
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

### The police email, which is the other address problem

The dispatch address is bound at registration and never travels in a claim, for the reasons above.

**The police email address is the opposite case and is handled deliberately differently.**
It is supplied by a human operator, on a live call, and there is no way to bind it in advance without knowing which department will answer.

So it is not trusted, it is **recorded**:

1. Near the end of the call, `caller` asks the operator for a destination address for the incident package
2. `caller` reads it back, character by character where ambiguous, and waits for confirmation
3. The address is sealed into the record as `operator_supplied`, alongside the audio of the operator saying it and the audio of the readback
4. `replay` sends to that address via Resend, and the send result goes into the chain

It is never treated as authorization for anything. It is a destination for a copy of a record that is already sealed, and if it is wrong the record is still intact and still attributable.

Say this out loud if a judge asks: **we did not solve operator-supplied addresses, we made them auditable**, which is the same move the dispatch address makes from the other direction.

Classification is the interesting part and should be visible.
Unaccounted motion plus a camera that resolves it into a person who lives there is a notification, not an incident.
Unaccounted motion plus a shutter that refused to open is a system fault that must never be dressed up as a finding.
Show that reasoning; it is what makes the system look like it is thinking rather than switching.

### Human-boundary tier

#### agents/caller **[tier 1]**

**The agent that talks to humans**, and since 2026-09-19 that is both of them: the 911 operator by phone through ElevenLabs, and the resident in the iOS app. The only agent that acts on the outside world.

The phone half is below; the resident half is under "the resident's side of the call".

**Outbound.** Reports the incident in plain English. Every claim it speaks has a verified source or it does not get spoken.

**Inbound.** The operator talks back, mid-call, in English.
"What are they wearing?" "Are they still in the living room?" "Is anyone else in the house?" "Are they carrying anything?"
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

This is not an optimisation. Putting the call on the resident's phone means iOS owns the audio routing, and **call audio cannot be silenced below a floor**. During an intrusion a speaking phone gives away a hiding person's position. Keeping them off the bridge by default means there is no audio stream to suppress.

#### Three participation modes

| Mode | Mic | Audio out | Used for |
|---|---|---|---|
| **Watching** | off | none | The default. Transcript only. |
| **Whispering** | **open** | **none** | Hiding, but needs to be heard |
| **Full voice** | open | on | Once the resident is safe, or out of the building |

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

After takeover the agent stops speaking **on the call** but keeps feeding the app: the current narration, the room, how many people the camera can see, and how long since the last frame resolved. **The resident becomes the voice and the agent becomes the teleprompter.** That is better than the agent guessing what a frightened person wants said.

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
The surviving incident type is not one where staying to help is correct guidance: during an intrusion the protocol is to stay hidden, get out if it is safe to, and not confront anyone.
Telling a resident to go and check would be a worse instruction, not a missing one.

Handle this carefully. Safety instructions delivered badly are a real-world harm, not a demo bug.

- Stay inside well-established public guidance, and the dispatcher's own words. Do not improvise medical advice.
- **Always defer to the operator.** If the dispatcher is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained for exactly this and the agent is not. This is enforced: relaying anything sets a deferral flag, and from that point the agent relays rather than generates.
- Never tell a user to do something that could hurt them or the person they are worried about. The protocol table carries the do-nots explicitly rather than leaving them absent: do not go looking, do not confront anyone, do not open the door.
- Say "wait for responders" when that is the right answer, which is often.

**`agents/caller/guidance.py` is the only place medical text exists in the entire system.** The iOS client contains none and must not acquire any: hardcoding first-aid copy in a view puts it outside the one component that gets reviewed against these rules.

The relay half is the high-value one. The safety-instruction half is the one to cut if time runs out.

#### agents/replay **[tier 2]**

The incident recorder, and after the pivot also the courier.

Logs what happened, in order, with who said it and whether it verified.
Movement through the house, sensing claims, the shutter grant and the position it produced, **every discard and every refusal with its reason**, the narration as it was generated, what the caller told the operator, what the operator said back, what guidance the user received, and the hash of every video segment as it closes.

Hash-chained locally, then sealed into the SCITT transparency log, where entries cannot be altered after the fact.

**The chain and the seal are different properties and the difference is load-bearing.** The local hash chain makes tampering detectable by whoever holds the record. The transparency log is what makes the record verifiable by someone who does not already have it. `seal()` returns `transparency_receipt: None` until that hop is wired, rather than implying a receipt it does not have.

Discards are recorded with exactly the same weight as acceptances. "It tells you what it discarded" is the sentence that carries the submission, and a record that only keeps what was accepted cannot support it.

##### The video is covered by the chain, not attached to it

Each ten-second segment from `vision` is hashed as it closes, and the hash goes into the chain.
The mp4 itself lives on disk next to the record.

That ordering matters: it means the chain stays small and verifiable in a browser, the video can be delivered separately without weakening anything, and **a recipient can check that the footage they received is the footage the system recorded.**
The standalone verifier in the zip export checks segment hashes as well as chain links.

##### The police handoff

When the call ends, `replay` seals the record and sends a package to the address the operator supplied, via Resend:

- The video segments, in order
- The call transcript, both sides
- The claim log, including every discard and every refusal
- The chain, plus the standalone verifier that checks it without needing us

The send itself is an event in the chain. A package that failed to send is visible rather than silent.

Two audiences beyond the police:

- **Detectives.** A tamper-evident record of what a camera saw and when, with a cryptographic account of what the system believed and why
- **Accountability for the system itself.** If the agents got something wrong, the record shows which agent said what and on whose authority

This is also where non-repudiation lives. The operator cannot verify us live, but an investigator can verify the record afterward, and swatting investigations are entirely post-hoc.

This resurrects the superseded flight-recorder idea in its proper place. The idea was sound; it was a feature rather than a product.

## The trust problem

The 911 operator talks to our agent in plain English and the agent talks back. That conversation is two-way.
What it is not is an ANS channel, because the far end is a person on a phone. The same is true of the user in the app.

**So neither human can verify us, and we must not claim otherwise.**
A voice asserting "this call is cryptographically verified" is worth exactly what a voice asserting "there is an intruder" is worth.

ANS governs every machine hop behind those voices, which is where it belongs.

### Primary: agents verifying agents

This is the submission, and it is the track owner's own model: client agent to server agent, his shopper-and-bank example.

`master` is the client of `presence`, `intruder` and `vision`. `caller` and `replay` are clients of `master` in turn.

**And `shutter` inverts it**, which is the case that makes the model concrete: there `master` is the client asking for an action, `shutter` is the server holding the thing worth protecting, and `shutter` issues the challenge because the verifier always does.

Before anything reaches a human, its source is verified.
The system is about to tell emergency services that there is a stranger in someone's living room, and before that it is about to uncover a camera in that room. If the agent that produced the claim is not who it says, or is running code that changed since it registered, this verification is the last thing standing between a compromised sensor and both of those outcomes.

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

Instantiated here twice: a compromised sensing agent between a real house and a real `master`, and a compromised `master` between a real `intruder` verdict and a real camera shield.
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

Seven is more to deploy than five, and that is a real cost rather than a footnote: seven hostnames, seven certificates, seven cards to keep current, and seven things that can be stale on the surface the judge inspects first.

Two of the seven are cheap, though, and it is worth knowing which.
`shutter` has one method and one refusal table. `vision` is the only one with an external API dependency.
If the deploy runs short, the five that existed before the pivot are already built and card-stable; add `shutter` next, because it is small and it is the demo.

All seven support A2A. **MCP is deliberately not implemented**; it is a second adapter over the same handlers and it buys presentation rather than capability. Roadmap, not this weekend.
Each publishes an agent card, and the cards must be kept current. Public agents surface on GoDaddy's Trust Index, which the judge maintains, so a stale card is a visible defect on the most-inspected surface.

## The demo

Two of them, carrying different claims. See `media/CLAUDE.md` for the split.

**The video, recorded at home.** Real walls, a real person walking in, a real servo pulling a real shield off a real lens. The only honest venue for the physical claims.

**The live demo at judging.** This is the one the track is actually scored on, and most of it needs no hardware:
the agents are hosted and reachable, so ANS verification, the agent cards on the Trust Index, the `fraud.webmesh.ai` probes, the refusal, the ElevenLabs call, and the operator question fan-out all run from a laptop on any network.

**Bring the Pi, the servo and the camera to the table.**
This is where the pivot pays off hardest. Before, the physical demo was a hand waving near a router and a graph twitching.
Now it is an object that moves when a signature checks out and does not move when it does not, on the table, in front of the judge, repeatable on demand.

Motion sensing is also environment-independent, needing no baseline at all, which is exactly why it survives a hall we did not calibrate in. That is what makes the trigger live rather than replayed.

Full sequence:

1. **Someone walks in.** `presence` reports motion in the living room. No registered device is associated. `intruder` returns an unaccounted verdict
2. **`master` issues a shutter grant**, signed, bound to the nonce `shutter` just issued
3. **`shutter` verifies it and the shield rotates ninety degrees.** This is the beat. It is physical, it is audible, and the judge is watching an object move because a certificate checked out
4. **`vision` gets the attestation and opens its eyes.** Gemini Live starts narrating; the segment writer starts recording. The first description lands about three seconds after the person entered the room
5. **The watch buzzes** and it carries the camera's first sentence, not a generic motion alert. The resident is looking at a description of a person in their living room within seconds
6. **A human taps Start Incident on the watch.** This is the only thing that releases `caller` to dial, and saying so on stage is a feature, not an apology
7. **`caller` dials.** ElevenLabs voice to a human operator, reporting only verified claims, driven by what the camera is currently seeing rather than a static summary
8. **The operator asks a follow-up in plain English.** "What are they wearing? Are they still in the living room?" The question fans out as ANS-verified queries, live, and comes back as a spoken answer sourced from the current frame. This is the beat that shows ANS working during the call rather than before it
9. **The resident watches the transcript on their phone** while `caller` tells them what to do. One agent, both audiences, one picture of the incident. Then they tap TAKE OVER and the agent goes silent mid-sentence
10. **Near the end, `caller` asks the operator where to send the incident package**, reads the address back, and `replay` ships video, transcript, claim log and verifier via Resend as the call closes
11. **Then run it again with a compromised agent, and show the shield staying shut.**
    Build the attacker locally, in the thirteen shapes `fraud.webmesh.ai` uses. **His battery cannot be aimed at us** (no target parameter, hardwired to `supplier.webmesh.ai`, verified 2026-09-19), so we implement the probes rather than invoke them, and we say that plainly rather than implying we ran his suite.
    Stage `underpay_valid_sig` against the shutter: a genuinely valid signature that must still be refused. It demonstrates the difference between authentication and authorization to a room, and with a camera shield as the target it lands on a non-technical judge instantly
12. **Then the beat that is better than the refusal.** Point `agent.webmesh.ai verify_agent` at our seven hostnames, live, and let the judge's own verifier confirm our identity in front of him. It checks DNS, DNSSEC, TL proof, and our published cards, then sends a live A2A message. Preparation is entirely card work: `ans/CARD.md`

**Step 11 is the submission.** Steps 1 through 10 are the setup. Step 12 is the one a judge cannot argue with, because he wrote the verifier.
Step 3 is what a room remembers. Step 8 is what makes the architecture legible.

**Step 6 is not a gap in the demo, it is a claim.** Say it out loud: Hawk Eye does not call 911 by itself, a person does.
Every other agent demo this weekend argues its agent deserves more autonomy. Ours draws the line in the one place where drawing it is obviously correct, and a judge who has spent the weekend hearing about agent sandbox breakout will notice.

## Build order

**`agents/TODO.md` is the work queue** and `TASKS.md` at the repo root is the team board.
This is the summary, in dependency order rather than severity order.

**Done and unaffected by the pivot:** the wire between agents (pull-only A2A, server-issued challenge, claims verified against each producer's published trust card); both cards per agent as byte-stable artifacts; the verification order's authentication and authorization halves, with the thirteen battery shapes and three challenge probes passing.

1. **Deploy.** Agents reachable at public names. The hard track requirement,
   and nothing below it is cheap until it is done
2. **`shutter`, end to end**, with a stub GPIO backend and the full refusal
   table. It is small, it is the demo, and it has no hardware dependency until
   the last step
3. **Register the domain, then the agents.** DNSSEC on
4. **`vision` against a fixture video file**, no camera required. The claim
   shape, the shutter gate, and the segment writer are all testable on a laptop
5. **Real certificates.** `keys[].x5c` is not validated today, so we are Bronze.
   DANE for Silver, a stapled receipt for Gold
6. **Certificate drift detection.** The cheapest and most demonstrable use of
   ANS available to us
7. **Live Trust Index lookups**, plus a safety-dimension evidence producer.
   The pivot makes this stronger: corroborating an agent's claim now means
   comparing it against recorded footage a human can also check
8. **Master's API for the hub**, so the app has a path to the real mesh
9. **Wire the incident lifecycle.** `caller` to `master`, `replay` actually
   called, the police handoff
10. **The impostor, as a real process** rather than an in-process test, pointed
    at `shutter`
11. ElevenLabs voice, then the bridge
12. **Real hardware last.** Servo on GPIO, camera on USB, CSI thresholds tuned.
    **On purpose.** The agent layer must never block on the hardware

## Roadmap, not this weekend

Worth one line on the Devpost page because it shows the architecture has somewhere to go.

- **Per-person agents.** Each resident gets a dedicated agent holding their context: medical conditions, mobility, where they usually sleep. The current design is a step toward this, not away from it.
- Live PSAP-side ANS resolution, which closes the gap named above.
