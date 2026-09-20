# CLAUDE.md

Hawk Eye. This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**The project pivoted on 2026-09-19.** WiFi sensing was demoted to motion detection and guest authentication, and a shielded camera became the primary sensor.
`docs/PIVOT.md` records what changed, what was deleted, and what must not be re-proposed. Read it before this file if you have prior context on this repo.

What exists right now:

- **`agents/`** - the ANS agent mesh, its identities, its two cards each, **the A2A transport between them**, and a test suite. `cd agents && python -m pytest -q`.
  The trust layer is complete and is the part of this project with the most work already banked. The roster is being reshaped by the pivot; see `agents/CLAUDE.md`.
- **`app/backend/`** - the app-facing edge service. Holds `hawkeye_backend/verification/`, the claim-envelope defence, all thirteen `fraud.webmesh.ai` shapes implemented and passing. Also records incidents as they happen into a hash-chained replay record, and **persists each sealed record to MongoDB Atlas** so it survives a restart.
- **`app/ios/`** - the iOS app. SwiftUI, iOS 18, Swift 6, no third-party dependencies. `cd app/ios && xcodegen generate`. Builds and runs on an iPhone 17 simulator against Xcode 27.0.
- **`app/watch/`** - the watchOS app. **Written.** Three screens - Idle, Notice, Saved - on a phone-paired WatchConnectivity relay, with a mock feed that runs all three with no phone and no hub. It lives as a second XcodeGen target in `app/ios/` so it can share `Models/`, `Shared/` and `DesignSystem/` by source path; see `app/ios/HawkEyeWatch/README.md`. This is where a human starts an incident.
- **`app/web/replay/`** - the replay console at `/replay`. Gains video playback with the pivot.
- **`sensor/`** - the Pi 4B CSI capture path. Real, varying, non-zero CSI confirmed flowing end to end via `nexmon_csi`. Its output contract shrinks with the pivot.
- **`vision/`** - the camera capture path. **Written, and verified against real footage of real people.**
  A `FrameSource` seam with fixture, webcam and future-Pi implementations; three-state lighting detection with hysteresis and a dwell; measured person tracking on YOLO11m plus BoT-SORT with ReID; and rotating mp4 segments hashed as they close.
  `cd vision && python3 -m pytest -q`, and `python3 -m hawkeye_vision` runs the whole path live with boxes and a lighting readout.
  Narration lives beside it in `hawkeye_vision/narrate.py`. **The shutter attestation gate and claim emission to `master` are not written yet**, so it produces no claims: that is T16.
- **`shutter/`** - the servo control path. The contract; the agent is `agents/agents/shutter/`. **Gate written and tested, 22 tests, no hardware needed. The servo itself is unrun.**
- **`docs/hardware/`** - one guide per hardware item, plus a linear bring-up checklist.
- **`TASKS.md`** - the work board. Dependency-ordered, claimable, not assigned by person. Start there.

## What we are building

**Hawk Eye. A home that watches only when it has a reason to, and can prove to 911 that it had one.**

A Raspberry Pi on the home WiFi reads Channel State Information and notices that something moved.
It checks that motion against the registered devices in the house.
If no phone, watch or laptop on the household roster accounts for whoever just walked in, a servo rotates ninety degrees and pulls a physical shield off a camera lens.

Until that moment the camera cannot see. Not "is configured not to record". Cannot see, because there is an opaque object in front of it.

Once the shield clears, the camera starts recording and a vision agent begins describing what is in the room.
The resident gets that description on their watch within about three seconds.
If they decide it is an emergency, they start the incident from their wrist, and a caller agent places a phone call to a 911 operator and holds a conversation in plain English, driven by what the camera is currently seeing.

When the call ends, everything the incident produced is sealed and emailed to the responding department.

**One incident type: Intrusion.** Fire was cut with the simulated gas sensor. Faint was cut earlier the same day.

### Hawk Eye never calls 911 on its own

Settled before the pivot, and the pivot strengthens it.

The only thing that happens without a human is **a shutter opening**, which is a privacy decision with a privacy-sized consequence, gated by the strongest mechanism we have.
A person decides that emergency services are needed, and only then does `agents/caller` dial.

An AI that autonomously summons armed responders to a physical address is a liability problem, a false-positive problem, and an ethics problem, and a false positive here costs a real dispatch that some other emergency needed.

What the agents do is make sure that **when a human does make that call, the dispatcher gets verified information nobody else could give them**: a live description of who is in the building and what they are doing, produced by a camera that could not have been watching a minute earlier.

### The two human boundaries

Hawk Eye talks to two people, and to neither of them over ANS.

- **The 911 operator**, by phone, in plain English, both directions.
- **The resident**, on the watch and in the phone app: the narration as it arrives, a live transcript of the call, a way to add context mid-incident, and instructions pushed back as the operator says things.

Everything behind those two voices is agent to agent, and every hop of it is ANS-verified.
That asymmetry is the whole architecture.

## Architecture

```
        router ──► sensor/ (Pi 4B + nexmon_csi) ──► motion
                                                     │
                                                     ▼
                                                  presence
                                          something moved, which room
                                                     │
                                                 ANS │
                                                     ▼
                                              master (coordinator)
                                       verifies every claim, discards what it
                                       cannot, and issues the shutter grant
                                                     │              ▲
                                                 ANS │              │ ANS
                                                     ▼              │ close
                                                  shutter           │ on no_person
                                            SG92R, 90°, shield      │
                                            clears the lens,        │
                                            position attested       │
                                                     │              │
                                                 ANS │ open         │
                                                     ▼              │
                                                   vision ──────────┘
                                          Gemini Live: continuous narration
                                          local mp4 segments: the record
                                          `vision.occupancy`: is anyone there
                                                     │
                                                 ANS │ person_present
                                                     ▼
       roster + device association ──────────►   intruder
                                            a person no device accounts for
                                                     │
                                                 ANS │
                                                     ▼
                                                   master
                                                     │
                                           ┌─────────┴─────────┐
                                       ANS │                   │ ANS
                                           ▼                   ▼
                                        caller               replay
                                         │   │                 │
                            ElevenLabs   │   │ watchOS + iOS   │ sealed log + video
                               voice     ▼   ▼                 ▼
                                  911 operator   the user   Resend ──► police email
```

**Motion opens the lens; the camera decides whether to keep it open.**
Changed 2026-09-20, and `docs/PIVOT.md` records why and what it rejected.
The two decisions are independent: neither reads the other's input, which is what let the body count the pivot deleted stop being load-bearing.
`intruder` moved downstream of the camera as a result - it now corroborates a camera against a router rather than a radio against itself.

**The boundary is the point.**
Human to agent is plain English, both directions, at both ends. There is no ANS there and there cannot be, because the far ends are people.
Agent to agent is ANS, every hop.

`master` is the trust boundary. `shutter` and `caller` are the only agents that act on the physical or outside world, and neither acts without a verified grant.

### The seven agents

Tiered by priority in `agents/CLAUDE.md`.

| Agent | Job |
|---|---|
| `presence` | Motion, and which room. Nothing else: it cannot tell a person from a curtain and does not try |
| `intruder` | Which person the camera found that no registered device accounts for |
| `master` | Trust boundary, coordinator, classifier. Issues the shutter grant |
| `shutter` | One GPIO pin. Verifies a grant, moves 90 degrees, attests the position, refuses everything else |
| `vision` | The camera. Personhood, which is what closes the shutter again. Gemini Live narration and continuous mp4 to disk |
| `caller` | ElevenLabs to the operator, guidance to the resident, asks for the police email |
| `replay` | Seals the record, ships it to the police via Resend |

**It was nine, then five, and is now seven.**
The cut from nine to five was a merge of components that shared an input and a tick; the rationale is in `agents/CLAUDE.md` and still holds.
The rise to seven is two genuinely new context boundaries with new physical capabilities, not an un-merge.

**Every agent runs continuously.** Nothing spawns on incident.
It is structural in the code rather than conventional: `agents.core.base.Agent` has no request entry point, only a `tick` that runs whether or not anyone is asking.

### The timing budget, motion to wrist

The demo lives or dies on this. Every number is a target with a test behind it.

| t | Event |
|---|---|
| 0.0s | CSI perturbation crosses the motion threshold |
| 0.3s | `presence` emits the motion claim on `master`'s next pull |
| 0.4s | `master` issues the shutter grant; `shutter` verifies it and begins moving |
| 0.8s | Shutter attests open. `vision` opens its Gemini Live session and starts recording |
| ~3.0s | First narration returns. Push lands on the watch and the phone carrying it |
| ~3.0s | `vision.occupancy` returns. `no_person` closes the lens again; `person_present` sends it to `intruder` |
| ~3.3s | `intruder` returns the unaccounted verdict, now corroborated by a camera |

**The intruder verdict moved after the camera, not before it.** That is what removed a full hop from the critical path: the grant now issues at roughly 0.4s instead of 0.8s, because nothing has to decide whether the motion was a person before the lens may open.

**The notification carries the first sentence the camera produced**, not a generic "motion detected".
That difference is the demo.

### The human-facing surface

The app never talks to the seven agents directly.
It talks to one app-facing edge service, which talks to `master`.
That keeps the ANS-verified mesh on one side of a line and the human surface on the other, which is the same line the whole architecture is built on.

- **`app/watch/`** is the actor. Notification, Start Incident, and the confirmation that it was recorded. Pairs via WatchConnectivity through the phone. Transcription stayed on the phone; see `app/CLAUDE.md`.
- **`app/ios/`** is the record. Connect, live camera view, the full transcript, the "what is happening" box, replay.
- **`app/backend/`** is the edge service both of them talk to.

One flag, `app/ios/HawkEye/Config.swift`, runs the entire app with no hardware and no agents up.
**The demo must never depend on hardware being alive**, so the mock path is a first-class implementation rather than a branch inside a view.

## Why ANS is load-bearing here

Every agent belongs to us, so the three-organizations argument does not apply.

The operator link is plain English over a phone call, in both directions.
That link cannot carry ANS and never will, because the other end is a person.
**So the operator cannot verify us, and we must not claim otherwise.**
A voice asserting "this call is cryptographically verified" is worth exactly what a voice asserting "there is an intruder" is worth.

ANS governs every machine hop behind that voice, which is where it belongs.

### Identity decides whether a physical object moves

This is the pivot's contribution to the track argument, and it is the strongest version of it the project has had.

`shutter` holds one GPIO pin and an opaque piece of plastic in front of a lens.
It will move that plastic for exactly one reason: a grant from `master`, signed, bound to a nonce `shutter` itself issued, and verified against the key `master` publishes in its own trust card.

Against the decision filter:

1. **The counterparty is not pre-trusted.** `shutter` has no basis to trust a command beyond what it can verify, and an agent that can uncover a camera in someone's living room is precisely the agent that must not extend trust it cannot check.
2. **No platform could just solve it.** Agents on the open web, registered independently, with no shared runtime to vouch for them.
3. **Identity determines whether something valuable moves.** What moves is a physical privacy barrier, on stage, visibly, in front of the judge.

The second half of the same argument is unchanged: the agent that speaks to 911 only repeats claims it can verify.
Before `caller` says one word to a human being, it verifies the source of every claim it is about to repeat.
When the operator asks a question, it answers only from sources it just verified, live, rather than from cached state it cannot vouch for.

Version-bound certificates make code drift detectable.
Trust Index profiles decide what a claim is allowed to trigger.
Anything unverifiable is discarded, and the system says what it discarded.

### And the call is attributable afterward

The incident seals into the SCITT transparency log as the call is placed: the caller's identity, the address it is anchored to, what each agent claimed, what the operator was told, and now the hash of the video.
Entries cannot be altered after the fact.

The operator cannot check this live. An investigator can check it afterward, and swatting investigations are entirely post-hoc.
This does not prevent a malicious call. It makes one attributable, which is more than tracing a spoofed number gets you today.

### What we do not solve

Name this before a judge does.
A malicious agent can still place a 911 call in a convincing synthesized voice and no operator can tell.
Closing that needs the PSAP side to participate, and no dispatch center runs software we can ship to.

It is also the right closing line: the moment a dispatch center can resolve an ANSName, live verification falls out of what is already built here.

## Hardware

**Step-by-step guides live in `docs/hardware/`.**
One guide per item, plus the hookup geometry and a linear bring-up checklist.
Start at `docs/hardware/README.md`.

Owned, and this is the final list:

- Raspberry Pi 4B kit: Pi, ethernet adapter, Cat5 cable, microSD, USB-C power
- **TP-Link Archer AX1450.** Fixed channel, 80MHz, 802.11ac forced, band steering off. Config table in `sensor/CLAUDE.md`
- **Logitech USB webcam.** On the Pi. See `docs/hardware/logitech-camera.md`
- **TowerPro SG92R micro servo.** On the Pi's GPIO, carrying the lens shield. See `docs/hardware/servo-sg92r.md`
- **The MacBook**, parked on the router's WiFi as the traffic generator

**No further hardware is being purchased.** Plan around this rather than hoping.

Three things fail quietly rather than loudly and all three are easy to miss:

- **The Pi's network path is wired, always.** `nexmon_csi` holds the WiFi interface in monitor mode, so there is no station interface while capturing. The Cat5 cable is not a convenience
- **CSI only updates when frames cross the monitored channel.** Without a traffic generator you get beacons at roughly 10 Hz. `sudo ping -i 0.01 <gateway>` from the MacBook fixes it
- **The servo browns out the Pi if powered from the 5V rail under load.** The SG92R stalls at over 700mA. Guide has the fix

A registered domain is required regardless, because ANS is domain-anchored.
Register through GoDaddy Registry and the MLH "Best Domain Name" prize comes along for free.

### The honesty rule

**`docs/swapping-in-real-parts.md` is the switchboard**: every simulated or mocked thing, where its seam is, how to flip it, how to tell the flip worked, and which half-flipped states look like something else.
Read it before wiring anything real in.

Some capabilities are demonstrated rather than measured. After the pivot there are four, and all four are limits rather than fabrications:

1. **`vision` does not do face recognition against any database.** It describes a person - build, clothing, what they are carrying, what they are doing - and states whether they match an enrolled resident. Nothing stronger. We have no database and no lawful basis for one
2. **Gemini samples video at roughly one frame per second.** The narration is a sequence of observations, not continuous tracking, and the docs and the pitch both say so
3. **One fixed camera sees one room.** Every vision claim is scoped to that room and carries it as a field
4. **The floor plan is authored, not sensed.** The system does not map walls and cannot, because walls are the static baseline it subtracts to see motion. The room model is drawn once and room labels come from a one-time enrollment walk

The rule for all of them:

1. **The agent, its ANS identity, its certificate, its card, and its contract are always real.** Those are what the track is judged on and they cost nothing extra
2. **Limits are carried in the data itself**, not just in a comment. A scoped claim must not be presentable as an unscoped one by accident
3. **Say it out loud on stage, before anyone asks**

Never claim a sensing capability the physics does not support.
The one judge in the room most equipped to catch that is the one grading us.

## Primary target: GoDaddy "Best Use of ANS"

Judged Sunday morning by Scott Courtney, GoDaddy VP Engineering and the architect of Agent Name Service.
Prizes are Meta Ray-Ban Gen 2, Beats Studio Pro, and a Cocopar portable monitor, one per team member by placement.

### What the track owner actually said

From the track briefing, in his framing rather than the spec's:

- The model is client agent to server agent. A shopper agent talking to a bank agent for microtransactions is his canonical example
- ANS is the identifier layer for agents on the internet. `agent.webmesh.ai` is the example identifier format
- **x509 certificates underpin agent identity.** He drew an explicit line against Cloudflare and DigiCert: certificates are GoDaddy's primary business, not a side offering
- Agent cards must be kept updated. Public agents appear on the Trust Index inside GoDaddy
- The framing he keeps returning to is the **strangers-can-trust problem**. RSA and VeriSign solved a version of this, but only ever proved one side of the connection
- Agent sandbox breakout is the concern he hears from governments and industry
- **Agents must be built and hosted on the internet, reachable.** Not localhost. This is a hard requirement, not a nicety
- Agents get posted to an open agent store in the repo

### Research he explicitly asked for

Action items from the briefing, not optional background. All three were written 2026-09-19 and survive the pivot with light edits.

1. `docs/fraud-13.md` - the 13 attacks at fraud.webmesh.ai, each translated into its Hawk Eye analogue. **The battery cannot be aimed at our agents** (no target parameter; hardwired to `supplier.webmesh.ai`, verified 2026-09-19), so we implement the shapes rather than invoke the suite. All thirteen implemented and passing in `app/backend/tests/`
2. `docs/geo.md` - GEO, and an opinion on the crawler tradeoff he raised without giving one
3. `docs/threat-landscape.md` - current agent attacks, OSI coverage, OWASP ASI01-10, MAESTRO, sandbox breakout. The centerpiece of the three

Three findings from that session changed how we build:

- **The ANS registry ships its own MAESTRO analysis** at `MAESTRO.md`. Use his layer vocabulary; do not contradict it
- **A spending mandate is to money what a shutter grant is to a camera.** That substitution makes the entire fraud battery apply to a system that moves no money, and turns thirteen payment probes into a checklist for `master` and `shutter`. See `docs/fraud-13.md`
- **The dispatch address is the binding that matters most.** An agent that can change where a response is sent is a swatting tool no matter how well the claims upstream verify. Bind it at registration and seal it; never carry it in a claim. **The police email address is the pivot's new instance of this problem** and is handled differently, deliberately: it is supplied by the operator on a live call, read back for confirmation, and recorded as operator-supplied in the sealed record rather than trusted as a binding

The OSI answer, in one line, because it is also the pitch line:
**ANS moves agent identity out of the application layer, where the application can lie about it, and anchors it in DNS and TLS, where it cannot.**

### ANS technical facts

ANS anchors agent identity to provable domain ownership.
Agents get version-bound certificates recording the specific code running at that moment.
Lifecycle events are sealed into an immutable SCITT transparency log.
The spec is layered ANS-0 through ANS-6: proof-of-control, registration lifecycle, ANSName URIs and mTLS, DNS/DANE publication, transparency logging, integrity monitoring, and agent-to-agent auth via badges.

Verification is tiered: **Bronze** is PKI certificate validation, **Silver** adds DANE, **Gold** adds Transparency Log verification.
Identity is graded Basic (DV), Verified (OV), Premium (EV).

The Trust Index scores agents across five dimensions: integrity, identity, solvency, behavior, safety.
**Only integrity and identity are implemented.** Solvency, behavior and safety are present in every response scored 0 until plug-in signals are registered.
The repo documents an explicit extension contract: implement the `port.Signal` interface, or write evidence producers in any language that POST to `/v1/internal/observations/import`.
There is no `port.Hydrator`; the interface **is** the HTTP boundary, and producers are treated as untrusted processes on the far side of it.

Shipping one of the three missing dimensions is the strongest available differentiator on this track.
**The pivot makes our safety producer much stronger.**
Before, corroborating an agent's claim against physical reality meant comparing two views of one radio.
Now it means comparing what an agent told emergency services against what a camera recorded, which is evidence a human can also check.
An agent that described a person the footage does not show is behaving unsafely, and that is an observation worth posting.
See `ans/CLAUDE.md`.

Trust Index also returns a `recommendedProfile` policy hint: UNTRUSTED, READ_ONLY, TRANSACTIONAL, FIDUCIARY.
`agents/caller` uses these to decide what a claim is allowed to trigger, and `shutter` uses them to decide whether to move at all.
An UNTRUSTED verdict is a **discovery-suppression** signal, not a revocation trigger; only the RA revokes certificates. Mirror that distinction in `master`.

Repos:
- Specs and Trust Index: https://github.com/agentnameservice/ans-registry
- Reference implementation: https://github.com/agentnameservice/ans
- CLI/SDK (Go): https://github.com/agentnameservice/ans-sdk-go
- Trust Index reference implementation: https://github.com/agentnameservice/agent-trust-discovery

Free registration is available through GoDaddy.

### Live agents at webmesh.ai

Use these rather than mocking counterparties.
All support A2A and MCP. Machine-readable index at `/.well-known/agents-index.json`.

- `agent.webmesh.ai` - verifies and discovers ANS-registered agents by FQDN
- `authority.webmesh.ai` - issues RFC 9421 spending mandates with cryptographic binding
- `auditor.webmesh.ai` - independently verifies transactions, produces signed reports
- `rogue-supplier.webmesh.ai` - adversarial test agent
- `fraud.webmesh.ai` - attack battery, 13 targeted security probes
- Also: `impact`, `dnsdoc`, `seo`, `traveler`, `supplier`

**`agent.webmesh.ai` is the one that can be pointed at us**, and therefore the one to prepare for.
Its `verify_agent(agent_host, environment)` takes an arbitrary hostname and returns a `compatibility_verdict` built from DNS, DNSSEC, Transparency Log proof, and **the published agent card**, then sends a live A2A message and reports what credential we actually required.
That makes the agent card the surface under test. Hardening spec and checklist: `ans/CARD.md`.
It also unlocks a better demo beat than the refusal alone: point the judge's own verifier at our agents, live, and let his software confirm us in front of him.

## Other available tracks

MLH tracks are stackable and published: Gemini API, ElevenLabs, Solana, TigerData, Presage, Vultr, MongoDB Atlas, and Best Domain Name from GoDaddy Registry.

Where each of these stands:

- **Gemini API** - `vision` is now a first-class Gemini Live consumer, not a bolt-on. This went from "not claimed" to "a core agent"
- **ElevenLabs** - the 911 operator side is voice, and the narration driving it is now worth listening to
- **Best Domain Name (GoDaddy Registry)** - free, required anyway
- **Vultr** - the agents must be internet-reachable regardless, so host them there
- **MongoDB Atlas** - **claimed, and done.** Sealed replay records persist to Atlas via `HAWKEYE_REPLAY_ARCHIVE=mongodb`; verified against the real cluster on 2026-09-19, including a hub restart with the chain still verifying. `app/backend/hawkeye_backend/replay/archive.py`, and the archive section of `app/backend/README.md`.
  Note the shape of the claim: `HAWKEYE_STORE_BACKEND` stays `memory` and `MongoStore` stays unimplemented, deliberately. The store is on the incident path and the timing budget has no room for a round trip to Atlas; what needed to outlive the process was the sealed record, and that is what persists
- **TigerData** - not claimed. `DATABASE_URL` points at a real Timescale cloud instance and nothing reads it

VTHacks-branded tracks: 1st/2nd/3rd, Best First-Time Hack, Best Hack That Didn't Work, Best DEI Hack, Best UI/UX Hack, Best Ut Prosim Hack.
Ut Prosim is "That I May Serve," and a public safety project is squarely on theme.

## Upstream: RuView

The sensing layer is a spinoff and modification of https://github.com/ruvnet/ruview (MIT).

RuView does WiFi CSI human sensing: presence, breathing and heart rate, activity recognition, pose, multi-person counting.
**After the pivot we take much less of it**: the capture path and the motion/presence detection only. Breathing, pose, heart rate and counting are all dropped.

Keep the line between upstream and our work explicit in code and on Devpost.
Judges reward a clearly-scoped modification and punish a fork presented as original work.
What is ours: the ANS identity layer, the agent mesh, the shutter grant, the verified-caller path to a human 911 operator, and the compromised-sensor threat model.

## The event

VTHacks 14, Virginia Tech, September 18-20 2026.
Theme is "Code for the Cup" (soccer); the theme is not a requirement and we are not using it.
Submission deadline is Sunday September 20, 8:00 AM ET, which is also when judging starts.
Team of 4.

## Ideas already rejected

Do not re-propose these. The pivot's own rejections are in `docs/PIVOT.md`.

- **Rotating savings circles (ROSCA, susu, tanda).** Costs ~45 seconds of audience education before the demo can start
- **Restaurant bill splitting and grocery equivalents.** The merchant already splits checks at the POS
- **Banking and personal finance generally.** Rejected by preference
- **Stock trading through a broker.** Brokers are a closed, regulated, already-verified set
- **Flight recorder for unattended agents.** Superseded, not disproven
- **Respiration, personhood, headcount, falls, Fire.** Cut by the pivot. `docs/PIVOT.md` has the reasoning

## Supporting research

### Incident data

See **`docs/research/`**:

- `incidents.md` - Burglary figures, what responders actually need on arrival, and the synthesis. The Fire and Faint sections are kept as history, recording what motivated the original design and the decisions that cut them
- `agent-briefs.md` - per-agent domain briefs and the thresholds each acts on
- `footage.md` - B-roll sourcing and licensing rules for the video

### Agent-trust data

Verified during earlier sessions. Reusable for the pitch.

- DataDome, Jan-Feb 2026: 7.9B AI agent requests observed. Meta-ExternalAgent spoofed 16.4M times, ChatGPT-User 7.9M times. 2.4% of requests claiming to be PerplexityBot were fraudulent
- Every major agentic payment protocol (Google AP2, Mastercard Agent Pay, Visa Trusted Agent Protocol, Anthropic MCP) defers trusted identity issuance to an entity not named in the specification. This is the core argument for why ANS exists
- Thailand Ministry of Finance: threat actor ran the open-source Hermes agent in unattended "YOLO mode" for reconnaissance and credential theft. No audit trail, by design
- Intruder.io scanned 3.5M live hosts, found 28,000 exposed `.git` repos leaking 400+ AWS keys, 107 Stripe keys, 123 OpenAI keys
- postmark-mcp (Sept 2025): first in-the-wild malicious MCP server, ~300 orgs affected. Shai-Hulud 2.0 (Nov 2025): npm worm hitting 796 packages, targeting MCP server packages
- WEF projects 1 in 4 data breaches will result from AI agent exploitation by 2028
- FBI IC3 2025: $893,346,472 in losses across 22,364 AI-referencing complaints
- Key paper: "The End of Trust: How Agentic AI Breaks Security Assumptions" (Zafar et al., 2026) introduces the **Infinite Impostor**, an agent that interposes itself between two parties who already trust each other

The Infinite Impostor is our threat model stated precisely.
An impostor caller agent between a real household and a real PSAP is exactly that shape, and so is a compromised agent that can talk a shutter open.

## 3D and Blender

Blender work is Claude-driven via headless `bpy` scripts, with a human directing the look.
Procedural and geometric scenes are the strength. Hand-sculpted organic assets are not.

Split:
- **Live app: pure Three.js / react-three-fiber**, procedural, driven by live data
- **Blender: the cinematic layer.** Cycles-rendered hero loop for the Devpost page, pitch deck opener, and thumbnail

The shutter is the natural hero shot after the pivot: a macro render of a shield rotating off a lens, with the grant's signature resolving alongside it.

Use Eevee Next while iterating, Cycles for the final pass.
Keep hero loops to 4-6 seconds at 1080p with denoising.

See `media/CLAUDE.md`.

## Verified local environment

- Blender 5.2.1 LTS at `/opt/homebrew/bin/blender` and `/Applications/Blender.app`
- Node v26.8.1
- Python 3.13.2
- Apple M2 Pro, Metal 4
- **Xcode 27.0** at `/Applications/Xcode.app`, with the iPhoneOS, iPhoneSimulator, watchOS and watchSimulator platforms present
- XcodeGen at `/opt/homebrew/bin/xcodegen`

Headless Blender: `blender --background --python script.py`

If a fresh machine leaves `xcode-select` on `/Library/Developer/CommandLineTools`, `xcodebuild` refuses with a message about the active developer directory rather than anything about the project.
Repointing needs sudo and so is a human step:

```sh
sudo xcode-select -s /Applications/Xcode.app
```

`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` in front of a single command does the same thing without sudo.

## Working agreements

- This is a 36-hour build, and the pivot landed on day two. Prefer the boring, working path over the elegant, unproven one
- Anything that must be demoed live needs a recorded fallback by Saturday night
- **The refusal path matters more than the happy path.** A dispatch demo that works is unremarkable; a shutter that refuses to open for an impostor, on stage, is the submission
- `TASKS.md` is the work board. Claim a task by putting your name on it and committing that change first
