# agents/

The ANS-registered agents behind Hawk Eye. All of them live on the user side, inside the home.
This is the GoDaddy track submission. Everything else supports it.

Read the root `CLAUDE.md` first.

## Why many agents instead of one

A judge will ask this. The answer is **context separation and speed, not redundancy.**

Each agent holds one narrow context and answers one kind of question, so none of them carries a prompt describing the whole system.
Narrow context is faster, cheaper, and less likely to hallucinate across concerns.
They run in parallel, so an operator's question fans out and returns at the speed of the slowest single answer rather than the sum of them.

It is also what makes the ANS story real rather than decorative.
One agent verifying itself is theater. Nine independently registered agents that must verify each other before anything reaches a dispatcher is the track's actual model.

## Always running

**Every agent runs continuously.** Nothing spawns on incident.

This is a requirement, not an optimization. It is what allows the system to notice things nobody asked it to look for:
an unidentified person in the house at 3am, a resident who went down and has not gotten up, CO climbing while everyone sleeps.

An architecture that only wakes on a button press cannot do the thing that makes this project worth building.

## Topology

```
              router ──► sensor/ ──► CSI              gas sensor (simulated)
                                      │                        │
        ┌──────────┬──────────┬───────┴────┬───────────────────┤
        ▼          ▼          ▼            ▼                   ▼
   occupancy   intruder  biometrics    collapse           environment
   count +     unexpected heart rate,  faint, fall,       CO, smoke
   location    presence   breathing    no-movement        (not CSI)
        └──────────┴──────────┴───────┬────┴───────────────────┘
                                      │ ANS
                                      ▼
                              master (coordinator)
                      classifies incident, aggregates, routes
                          │              │              │
                     ANS  │         ANS  │         ANS  │
                          ▼              ▼              ▼
                      caller         guidance        replay
                          │              │              │
           ElevenLabs     │              │ iOS app      │ sealed log
              voice       ▼              ▼              ▼
                911 operator          the user     post-incident review
```

**The boundary is the point.**
Human to agent is plain English, in both directions, on both ends. There is no ANS there and there cannot be, because the far ends are people.
Agent to agent is ANS, every hop.

`caller` and `guidance` are the translators.
Nothing crosses a human boundary that was not verified first.

## The cast

Nine agents. Priority tiers are marked; build in tier order when time is short.

**Domain research for every agent is in `docs/research/agent-briefs.md`**: the thresholds each one acts on, the statistics behind it, and what it must not claim.
Read your agent's brief before writing it. The "must not claim" lines are the ones that lose the judging conversation.

### Sensing tier

#### agents/occupancy **[tier 1]**

How many people are in the building, where each one is, and coarsely what each one is.

This merges people-count, location, and body type. They are one question asked three ways, they share a baseline, and splitting them buys nothing but three deployments.

Coarse, room-level zones. Not coordinates.
Presence IDs are stable within a session only; we do not do person re-identification and must not claim to.

**The class split is grounded in respiration rate, supplied by `agents/biometrics`**, not in signal amplitude. Resting rates: adult 12-20, child 20-30, infant 30-60, dog and cat 15-30+.
That is physically defensible where "mass perturbs the signal differently" was not, and an RF-literate judge will press on the difference.
It does **not** cleanly separate a dog from a child. State the overlap rather than hiding it; the honest resolution is "adult versus small and fast-breathing."

#### What counting can actually deliver on this hardware

Settled 2026-09-19. **Presence: reliable. An exact count: not reliable.**

The BCM43455c0 is **1x1**. One antenna means frequency diversity across subcarriers and no spatial diversity at all. Most CSI counting in the literature uses Intel 5300 or Atheros NICs with two or three antennas, because antenna diversity is where spatial resolution comes from.
RuView says the same in its own terms: single-node deployments have limited spatial resolution and 2+ nodes are recommended. Its "3-5 people per AP" figure assumes the multi-node mesh, not one link.

| Scenario | Realistic outcome |
|---|---|
| Two people apart, at least one moving | Detectable as "more than one", moderate confidence |
| **Two people within ~1m** | **Reads as one.** Occlusion plus overlapping Fresnel geometry |
| One moving, one still | The mover dominates; the still one is near-invisible to motion |

That last row is our actual scenario, which is why `biometrics` rather than motion is what finds the person on the floor.

**Respiration is a better route to a count than motion is.** Two people breathing at different rates give two spectral peaks in the 0.1-0.5 Hz band, and two resolvable peaks is real evidence of two bodies. Two people breathing at similar rates, say both near 15 BPM, produce overlapping peaks a single link cannot separate, and it only works while they are still.

A small room cuts both ways: a 3m router-to-Pi span is in the sweet spot and SNR is strong, but two people in 100 square feet are necessarily close together, which is the case that merges, and nearby walls produce dense multipath that makes the channel harder to read rather than easier.

**Therefore: take the count from the roster, not the radio.** Device association tells us two residents are home with certainty, because it comes from the network. See `docs/research/identity.md`. The radio then only has to answer *which room* and *is this one breathing*, which it can.
Where a sensed count is reported at all, it carries a confidence and is phrased as "at least", never as an exact figure.

**This is the agent that genuinely needs a baseline**, and the only tier 1 one that does. Counting and localization are the capabilities that require knowing what empty looks like.
See the calibration section in `sensor/CLAUDE.md`: build a rolling percentile baseline with slow adaptation, not a calibration step. The adaptation constant decides whether a motionless person stays visible.

The load-bearing agent. If only one sensing agent works, make it this one.

#### agents/intruder **[tier 1]**

Detects and tracks a presence that should not be there.

Distinct from `occupancy` in the question it asks. Occupancy says how many and where; intruder says **which of them is not supposed to be here**, and keeps a continuous track once it decides.

It consumes the personhood verdict from `agents/biometrics`. A perturbation without a respiration signature is not an intruder, it is a curtain, and calling police on a curtain is the failure mode to design against.

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
**Name the holes rather than pretending there are none:** a resident who left their phone in the car, a guest, a burglar carrying a phone that never associates. Every real security product has these gaps.

We do **not** recognise individuals. Gait-based WiFi identification needs per-person enrollment, the same room it was trained in, and a subject who is walking - which our headline victim, motionless on a floor, is not.

For the burglary incident type this is the agent that matters: **where the intruder is and where the resident is, tracked separately.**

#### agents/biometrics **[tier 1]**

Respiration and heart rate from CSI, and **the arbiter of what counts as a person.**

Promoted from tier 2 on 2026-09-19. It is not a reporting channel; it is the component that decides a presence is human.

A perturbation showing quasi-periodic modulation in a physiological band is a living body. A fan, a curtain, a rolling cart, a swinging door: none of them produce that signature.
Three properties make this load-bearing:

1. **Calibration-free.** Periodicity does not depend on knowing what an empty room looks like.
2. **It discriminates human from non-human motion**, which nothing else in the stack can do.
3. **It works on someone who is not moving**, which is exactly where motion detection fails and exactly the case that matters.

**Use respiration for the personhood decision, never heart rate.**
Breathing moves the chest wall roughly 5-12mm; a heartbeat moves it a few tenths of a millimeter, usually buried under respiration harmonics.
RuView lists heart rate at 40-120 BPM. Treat it as a stretch goal and as a good number to say on the 911 call. Respiration at 0.1-0.5 Hz carries the verdict.

It also separates three states an occupancy counter cannot tell apart: moving, still but breathing, and neither.
"Unresponsive occupant in the main bedroom" is the most valuable sentence this system can say to a dispatcher, and it comes from here.

**Do not treat absence of respiration as absence of a person.** Shallow breathing, breath-holding, and range limits all degrade toward invisible.
Cross-check `collapse` before concluding anything, and escalate uncertainty rather than resolving it silently.

See `sensor/CLAUDE.md` for the signal-level detail and the stated limits.

#### agents/collapse **[tier 1]**

Someone was upright, is now down, and has not gotten up.

Upstream supports this directly. RuView ships fall detection at sub-200ms and exposes `fall-risk`, `no-movement`, and `bed-exit`.

It backs the Faint incident type as an **information source, not a trigger.**

It also owns the project's strongest statistics. A **long lie** is clinically defined as being unable to get up for over an hour; **53% of older fall patients are still on the floor when the ambulance arrives**, and **half of those down over an hour die within six months even absent injury from the fall.**
That makes `still_down_s` the clinical variable, not a diagnostic detail. Surface it, escalate on it, say it on the call. See `docs/research/agent-briefs.md`.
`collapse` does not raise a 911 call. It surfaces the detection in the app and stamps `still_down_s` onto the incident record, so that when a human does call, the dispatcher learns the fall happened four minutes ago rather than being told "I found her like this."

That timestamp is the clinical variable. See `docs/research/agent-briefs.md`.

The critical detail is debounce. Sitting down fast, lying down to sleep, and a child playing all look like a fall for an instant.
The signature is collapse **followed by** absence of normal movement, cross-checked against `biometrics`.
A system that calls 911 when someone flops onto a couch is worse than no system.

Notify `master` on detection. Do not wait to be polled. `master` records it and surfaces it; it does not escalate to a call on its own.

#### agents/environment **[tier 3]**

Air quality. Carbon monoxide, not oxygen, and **not from CSI**.

**No gas sensor is being purchased.** The reading is simulated, and that is disclosed rather than hidden.

Real here: the agent, its ANS registration, its certificate, its card, its place in the mesh, and the driver interface.
Simulated: the number. `environment.source` carries the literal string `demo-trigger` so a simulated reading cannot be presented as measured by accident.

The claim is about extensibility, and it is checkable by reading the code: swapping in a real MQ-7 on the Pi's GPIO is a driver behind an interface that already exists, and nothing above it changes.

**Say it precisely: this is possible with the right hardware.** Never "CSI can detect gas." CSI cannot, at any price, on a 2.4/5 GHz radio. The claim is about the architecture, not the radio, and that distinction is what makes it survive a question.

Why CO and not oxygen: **CSI cannot sense gas composition.** Oxygen absorption is a ~60 GHz phenomenon, which is why 802.11ad lives there; the BCM43455c0 is a 2.4/5 GHz radio. See `sensor/CLAUDE.md`.

CO is the better signal anyway. It is what incapacitates people in structure fires before flame reaches them, and it is the likeliest reason someone faints in a house that is not visibly burning.
`collapse` says someone went down. `environment` proposes why. Different modalities agreeing is real corroboration; two views of one CSI stream agreeing is not.

### Coordination tier

#### agents/master **[tier 1]**

The incident coordinator. Classifies what is happening, aggregates what the sensing agents report, and routes to `caller`, `guidance`, and `replay`.

Incident types: **Burglary, Fire, Faint.** **All three are user-triggered from the iOS app.**

`master` never initiates a 911 call. Sensing agents inform it continuously; it classifies and holds state; a human tap is what releases `caller` to dial.
`collapse` and `environment` detections surface as alerts in the app so a person can act on them, which is the whole point of detecting them. They do not dial.
Classification table and the reasoning behind each combination: `docs/research/agent-briefs.md`.

This agent holds the only full picture, which makes it the place where verification must be strictest.
Every claim it accepts carries the identity of the agent that made it, that agent's Trust Index score at that instant, and a verification result. Anything unverifiable is discarded and logged as discarded.

### Verification order

Derived from the `fraud.webmesh.ai` battery, which is thirteen ways of asking one question: **does this implementation treat a valid signature as authorization?**
Ten of the thirteen pass only if the answer is no. Full mapping in `docs/fraud-13.md`.

**This is implemented**, in `app/backend/hawkeye_backend/verification/`, with all thirteen shapes as passing tests.
It lives in the hub for now only because `master` does not exist yet; it is a standalone package with no FastAPI or hub imports, so moving it is an import change.
Do not write a second verifier. Import that one.

1. **Verify the envelope.** mTLS handshake, then JWS signature over the canonical payload. **Nothing downstream ever sees an unverified field.** Verify first, parse second, never the reverse.
2. **Check bindings.** Audience (this `master`, not any coordinator that will listen), zone scope, incident ID, nonce.
3. **Check schema version.** Reject an under-specified claim rather than interpreting it charitably. This will bite us for ordinary reasons: nine agents at different build stages all weekend.
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
A fall plus elevated CO is a fire incident with a casualty, not a faint.
An unexpected presence plus a resident in a different room is a burglary, not a visitor.
Show that reasoning; it is what makes the system look like it is thinking rather than switching.

### Human-boundary tier

#### agents/caller **[tier 1]**

Talks to the 911 operator by phone, through ElevenLabs. The only agent that acts on the outside world.

**Outbound.** Reports the incident in plain English. Every claim it speaks has a verified source or it does not get spoken.

**Inbound.** The operator talks back, mid-call, in English.
"Is the child still breathing?" "Anyone outside the front door?" "How long since they went down?"
`caller` parses each question, fans it out through `master` as ANS-verified queries, and speaks the result.

Rules for the inbound path:

- **Answer from a live verified query, not cached state.** The operator asks now because the answer may have changed, and an agent trusted ninety seconds ago may not be trusted now.
- **"I don't know" must be available and must be used.** An agent that invents an answer for a dispatcher is worse than one that admits a gap.
- **An operator question must never widen what the agent will trust.** Pressure from an authority figure is a social-engineering vector, and an agent that relaxes verification because someone official-sounding asked is exactly the failure this project exists to prevent. The bar does not move.
- Keep answers short. This is a dispatcher on a live call, not a chat window.

Operator speech also drives the user's phone. Keywords like "I've dispatched units" or "they're two minutes out" fire notifications to the resident through `guidance`.
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
| **Full voice** | open | on | Faint, Fire, or Burglary once safe |

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

After takeover the agent stops speaking **on the call** but keeps feeding the app: CO reading, room, respiration, `still_down_s`. **The resident becomes the voice and the agent becomes the teleprompter.** That is better than the agent guessing what a frightened person wants said.

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

#### agents/guidance **[tier 2]**

Talks to the **user**, while the incident is happening, in the iOS app.

Two jobs, merged because they are the same job: telling a frightened person what to do next.

1. **Relay.** What the operator and responders have said, translated into what it means for the user. "Units are two minutes out. Stay where you are, unlock the front door if you can do it safely."
2. **First aid.** Instructions for the situation at hand. CPR, recovery position, cover your nose and stay low, do not move someone who fell.

Handle this carefully. First-aid instructions delivered badly are a real-world harm, not a demo bug.

- Stay inside well-established public guidance. Hands-only CPR, recovery position, stop-the-bleed. Do not improvise medical advice.
- Always defer to the operator. If the dispatcher is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained for exactly this and the agent is not.
- Never tell a user to do something that could hurt them or the patient. Moving a fall victim is the classic example.
- Say "wait for responders" when that is the right answer, which is often.

Marked tier 2 because the relay half is straightforward and high-value; the first-aid half is the one to cut if time runs out.

#### agents/replay **[tier 3]**

The incident recorder. Logs what happened, in order, with who said it and whether it verified.

Movement through the house, sensing claims, verification results, what the caller told the operator, what the operator said back, what guidance the user received.
Sealed into the SCITT transparency log, where entries cannot be altered after the fact.

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

`master` is the client. The sensing agents are servers. `caller`, `guidance`, and `replay` are clients of `master` in turn.

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

Host them before they are finished. Nine empty agents reachable tonight beats nine complete agents on a laptop Sunday morning, because the deploy path is where the hours disappear.

All nine support A2A and MCP, consistent with the live agents at webmesh.ai.
Each publishes an agent card, and the cards must be kept current. Public agents surface on GoDaddy's Trust Index, which the judge maintains, so a stale card is a visible defect on the most-inspected surface.

## The demo

Two of them, carrying different claims. See `media/CLAUDE.md` for the split.

**The video, recorded at home.** Live CSI, real walls, a real fall. The only honest venue for the physical claims.

**The live demo at judging.** This is the one the track is actually scored on, and it needs no hardware:
the agents are hosted and reachable, so ANS verification, the agent cards on the Trust Index, the `fraud.webmesh.ai` probes, the refusal, the ElevenLabs call, and the operator question fan-out all run from a laptop on any network.
Sensing input comes from replayed CSI captured at the house. Downstream agents cannot tell the difference.

**Bring the Pi and router to the table anyway.** Not for the full pipeline, which the environment cannot support, but for one scoped live bit that does work in a crowded hall: movement.
No calibration, no baseline, no walls. Someone waves a hand near the router and the signal visibly responds. A judge can try it themselves.

This is not a consolation prize, and there is a principled reason it works: **motion sensing is environment-independent.** It needs no baseline at all, which is exactly why it survives a room we did not calibrate in.
Counting and localization are the capabilities that need a reference, and they are the ones that stay in the video.

Worth knowing if a judge asks why you are not demoing the rest: a baseline captured in a hall decays as the hall fills, because bodies are reflectors and the static multipath structure you calibrated against stops existing. Occupancy also assumes a bounded space, and an open hall has no wall defining who is inside.

Full sequence, as filmed:

1. `collapse` fires. Someone went down in the main bedroom and has not moved. The app raises an alert; **no call is placed.**
2. The other sensing agents corroborate. **Keep the sensed claim to one resolved presence**, and take the headcount from the roster rather than the radio: two residents registered, both phones associated, and an occupant in the west bedroom breathing at 6 a minute. An exact sensed count of two or three is beyond a 1x1 link; see the counting limits under `agents/occupancy`.
3. **A human taps Faint.** This is the only thing that releases `caller` to dial, and saying so on stage is a feature, not an apology.
4. `master` classifies, verifies every source, discards what it cannot verify, and routes.
5. `caller` dials. ElevenLabs voice to a human operator, reporting only verified claims - including the forty seconds that elapsed before anyone tapped.
   The line that wins the demo is about **one** person: "an occupant in the west bedroom, down four minutes, breathing at six a minute." That needs exactly one resolved presence, which is what the hardware can give.
6. The resident watches a live transcript on their phone while `guidance` tells them what to do.
7. **The operator asks a follow-up in plain English.** "Is the child still breathing?" The question fans out as ANS-verified queries, live, and comes back as a spoken answer. This is the beat that shows ANS working during the call rather than before it.
   Then **the resident taps TAKE OVER and the agent goes silent mid-sentence.** Five seconds of footage that answers the room's biggest doubt about this entire project: what if the AI says something wrong. A human starts the call, a human can take it, a human can end it. The agent only ever holds the microphone on loan.
8. **Then run it again with a compromised sensing agent** and show the system refusing to escalate on its claims.
   Build the attacker locally, in the thirteen shapes `fraud.webmesh.ai` uses. **His battery cannot be aimed at us** (no target parameter, hardwired to `supplier.webmesh.ai`, verified 2026-09-19), so we implement the probes rather than invoke them, and we say that plainly rather than implying we ran his suite.
   Stage `underpay_valid_sig`: a genuinely valid signature that must still be refused. It demonstrates the difference between authentication and authorization to a room, and its Hawk Eye analogue lands on a non-technical judge immediately. Per-probe translations in `docs/fraud-13.md`.
9. **Then the beat that is better than the refusal.** Point `agent.webmesh.ai verify_agent` at our nine hostnames, live, and let the judge's own verifier confirm our identity in front of him. It checks DNS, DNSSEC, TL proof, and our published cards, then sends a live A2A message. Preparation is entirely card work: `ans/CARD.md`.

Step 8 is the submission. Steps 1 through 7 are the setup. Step 9 is the one a judge cannot argue with, because he wrote the verifier.
Step 7 is what makes the architecture legible.

**Step 3 is not a gap in the demo, it is a claim.** Say it out loud: Hawk Eye does not call 911 by itself, a person does.
Every other agent demo this weekend argues its agent deserves more autonomy. Ours draws the line in the one place where drawing it is obviously correct, and a judge who has spent the weekend hearing about agent sandbox breakout will notice.

**Steps 4 through 9 are the live venue demo**, driven by replayed CSI. Steps 1 to 3 are the video's job, because they are the ones that need a real house.

## Build order

1. **Fix the deployment.** Nine agents reachable with correct cards. Nothing else until this is done.
2. `master` verification and discard logic, against fake sensing output.
3. **Cards correct and `verify_agent` clean**, all nine. The surface the judge's own verifier inspects, and cheaper than everything below it. Checklist in `ans/CARD.md`.
4. The refusal demo. Implement the thirteen probe shapes locally against `master` and record the verdicts, failures included, in `docs/fraud-13.md`. A documented failure with a stated reason is worth more than a claimed pass; these shapes were written to be failed by naive implementations.
5. `caller` outbound, then the inbound question path.
6. `biometrics` first among the sensing agents, because it is calibration-free and everything else consumes its personhood verdict. Then `collapse`, also calibration-free. Then `occupancy` and `intruder`, which need the rolling baseline.
7. ElevenLabs voice.
8. `guidance`, `replay`, `environment`.
9. Real CSI wired in. **Last on purpose.** The agent layer must never block on the hardware.

## Roadmap, not this weekend

Worth one line on the Devpost page because it shows the architecture has somewhere to go.

- **Per-person agents.** Each resident gets a dedicated agent holding their context: medical conditions, mobility, where they usually sleep. The current design is a step toward this, not away from it.
- Live PSAP-side ANS resolution, which closes the gap named above.
