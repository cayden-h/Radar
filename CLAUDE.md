# CLAUDE.md

Hawk Eye. This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

The idea is locked as of 2026-09-18; the agent roster and demo format were settled 2026-09-19.

Written as of 2026-09-19:

- **`app/ios/`** - the full iOS app. Generate with `cd app/ios && xcodegen generate`. Not yet built or run, because Xcode was not installed on the dev machine at the time of writing. Every file passes `swiftc -parse -swift-version 6`.
- **`app/backend/`** - the app-facing edge service.
- **`docs/hardware/`** - step-by-step guides for every hardware item and a bring-up checklist.
- **`docs/research/`**, `docs/fraud-13.md`, `docs/geo.md`, `docs/threat-landscape.md` - the three assigned research deliverables, plus the incident data.

Still outstanding, in rough order of risk:

1. **The CSI capture path.** No hardware has been brought up yet. This is the largest single risk in the project. `docs/hardware/bring-up-checklist.md` is the path; `sensor/CLAUDE.md` has the fallback ladder and the point at which to stop.
2. **The nine agents.** Contracts are written in `agents/CLAUDE.md`; the code is not.
3. **ANS registration and hosting.** The deployment is currently broken, and the agents must be internet-reachable rather than on localhost. That is a hard requirement of the primary track, not a nicety.
4. **Agent cards are not published.** The signing, drift and address-commitment code exists and is tested (`app/backend/hawkeye_backend/verification/card.py`); what is missing is real cards served at real hostnames. This is the surface the judge's own verifier inspects. `ans/CARD.md` is the spec and checklist.
5. ~~The thirteen probe shapes are not implemented.~~ **Done 2026-09-19.** All thirteen, plus both bonus structural checks, implemented and passing in `app/backend/tests/` against `hawkeye_backend/verification/`. Results table in `docs/fraud-13.md`. Still to move from the hub into `agents/master` once master exists.

Re-run `/init` once the agents land so this file can describe actual build and test commands for them.

## What we are building

**Hawk Eye.** A home that speaks to 911 for you, and proves to the other agents involved that it is not lying.

A Raspberry Pi connected to the home WiFi router reads Channel State Information and maps where people are inside the house, through walls and in darkness, with no camera and no microphone.
Nine always-running agents interpret that signal and act on it.
When a person decides to call, one of them places the phone call to a 911 operator and holds a conversation in plain English.
Another talks the resident through what to do while it happens.

Three incident types: **Burglary, Fire, Faint.** Each is raised by a human, from the iOS app.

**Hawk Eye never calls 911 on its own.** Settled 2026-09-19.
The sensing agents detect, classify and inform. They do not dial. A person decides that emergency services are needed, and only then does `agents/caller` place the call.

This is a deliberate limit, and it is the right one. An AI that autonomously summons armed responders to a physical address is a liability problem, a false-positive problem, and an ethics problem, and a false positive here costs a real dispatch that some other emergency needed.

What the agents do is make sure that **when a human does make that call, the dispatcher gets verified information nobody else could give them**: how many people are in the building, which rooms they are in, whether each of them is breathing, and how long since one of them went down.

That information is what the research is about.
**Half of older adults who lie on the floor more than an hour after a fall die within six months, even where the fall caused no injury.** 53% are still on the floor when the ambulance arrives.
In a house fire, toxic gases can render someone unconscious in under a minute, often before they know there is a fire.
28% of older adults live alone; among women over 75, 42%.

The fall is not what kills. **The time to discovery is, and so is arriving without knowing who is inside.** Figures and sources in `docs/research/incidents.md`.

### The two human boundaries

Hawk Eye talks to two people, and to neither of them over ANS.

- **The 911 operator**, by phone, in plain English, both directions.
- **The resident**, in the iOS app: a live transcript of the call, a "what is happening" box to add context mid-incident, and instructions pushed back as the operator says things.

Everything behind those two voices is agent to agent, and every hop of it is ANS-verified.
That asymmetry is the whole architecture. See `agents/CLAUDE.md`.

## Why ANS is load-bearing here

Every agent belongs to us, so the three-organizations argument does not apply.

The operator link is plain English over a phone call, in both directions.
That link cannot carry ANS and never will, because the other end is a person.
**So the operator cannot verify us, and we must not claim otherwise.**
A voice asserting "this call is cryptographically verified" is worth exactly what a voice asserting "there is a fire" is worth.

ANS governs every machine hop behind that voice, which is where it belongs.
What is actually true, and sufficient:

### The agent that speaks to 911 only repeats claims it can verify

This is the track owner's own model, client agent to server agent, applied where it matters.
`agents/caller` is the client. The five sensing agents are servers.

Before it says one word to a human being, the caller verifies the source of every claim it is about to repeat.
The same holds in reverse: when the operator asks a question, the caller answers it only from sources it just verified, live, rather than from cached state it cannot vouch for.
It is about to tell emergency services that a child is unresponsive in a back bedroom.
If the agent that produced that claim is not who it says it is, or is running code that changed since it registered, the caller is the last thing standing between a compromised sensor and an armed response to someone's address.

Version-bound certificates make code drift detectable.
Trust Index profiles decide what a claim is allowed to trigger.
Anything unverifiable is discarded, and the system says what it discarded.

Against the decision filter:

1. **The counterparty is not pre-trusted.** The caller agent has no basis to trust a sensing agent's claim beyond what it can verify, and the whole point of the design is that it must not extend trust it cannot check.
2. **No platform could just solve it.** Agents on the open web, registered independently, with no shared runtime to vouch for them.
3. **Identity determines whether something valuable moves.** What moves is an armed response to a physical address, sent on the strength of a claim. Getting it wrong is how people have been killed.

### And the call is attributable afterward

The incident seals into the SCITT transparency log as the call is placed: the caller's identity, the address it is anchored to, what each sensing agent claimed, what the operator was told.
Entries cannot be altered after the fact.

The operator cannot check this live. An investigator can check it afterward, and swatting investigations are entirely post-hoc.
This does not prevent a malicious call. It makes one attributable, which is more than tracing a spoofed number gets you today.

### What we do not solve

Name this before a judge does.
A malicious agent can still place a 911 call in a convincing synthesized voice and no operator can tell.
Closing that needs the PSAP side to participate, and no dispatch center runs software we can ship to.

It is also the right closing line: the moment a dispatch center can resolve an ANSName, live verification falls out of what is already built here.

## Architecture

```
        router ──► sensor/ (Pi 4B + nexmon_csi) ──► CSI      gas (simulated)
                                                    │               │
        ┌──────────┬──────────┬────────────┬────────┴───┬───────────┘
        ▼          ▼          ▼            ▼            ▼
   occupancy   intruder  biometrics    collapse    environment
   count +     unexpected heart rate,  faint,      CO, smoke
   location    presence   breathing    fall        (not CSI)
        └──────────┴──────────┴─────┬──────┴────────────┘
                                    │ ANS
                                    ▼
                            master (coordinator)
                     classifies Burglary / Fire / Faint
                       │            │            │
                   ANS │        ANS │        ANS │
                       ▼            ▼            ▼
                   caller       guidance      replay
                       │            │            │
        ElevenLabs     │            │ iOS app    │ sealed log
           voice       ▼            ▼            ▼
             911 operator       the user    post-incident review
```

**The boundary is the point.**
Human to agent is plain English, both directions, at both ends. There is no ANS there and there cannot be, because the far ends are people.
Agent to agent is ANS, every hop.

`caller` and `guidance` are the translators. Nothing crosses a human boundary that was not verified first.

Nine agents rather than one, for **context separation and speed, not redundancy.** A judge will ask; that is the answer.
All nine run continuously, which is what lets the system notice things nobody asked it to look for.

`master` is the trust boundary and `caller` is the only agent that acts on the outside world.
Between them they are the last thing standing between a compromised sensor and an armed response to someone's address.

The conversation is two-way and live.
An operator who asks "is the child still breathing?" causes a fan-out of ANS-verified queries to the sensing agents and gets an answer seconds later, in English.
That loop is where ANS is visibly doing work during the demo rather than in a setup phase nobody watches.

Nine agents, tiered by priority in `agents/CLAUDE.md`. Per-person agents are roadmap, not this weekend.

Note that `environment` is deliberately not a CSI consumer.
Two independent sensing modalities agreeing is real corroboration; two views of one CSI stream agreeing is not.

See `agents/CLAUDE.md` for the agent contracts and `sensor/CLAUDE.md` for the capture path.

### The human-facing surface

The app never talks to the nine agents directly.
It talks to one app-facing edge service, which talks to `master`.
That keeps the ANS-verified agent mesh on one side of a line and the human surface on the other, which is the same line the whole architecture is built on.

- **`app/ios/`** is the iOS app. SwiftUI, iOS 18, Swift 6, no third-party dependencies. There is no `.xcodeproj` in the repo; `app/ios/project.yml` is an XcodeGen spec. Two stages: a Connect screen listing Hawk Eye hubs found over Bonjour, then the main screen. It is not a WiFi picker and cannot be, because enumerating SSIDs needs the `NEHotspotHelper` entitlement. See `app/CLAUDE.md`.
- **`app/backend/`** is the edge service the app talks to. See `app/backend/README.md`.
  It also holds **`hawkeye_backend/verification/`**, the claim-envelope defence: the thirteen `fraud.webmesh.ai` shapes, agent-card signing and drift, and the dispatch-address commitment. Standalone package, no FastAPI imports, so it moves into `agents/master` as an import change. `cd app/backend && python -m pytest -q` is 37 security tests.

One flag, `app/ios/HawkEye/Config.swift`, runs the entire app with no hardware and no agents up.
**The demo must never depend on hardware being alive**, so the mock path is a first-class implementation rather than a branch inside a view.

## Upstream: RuView

The sensing layer is a spinoff and modification of https://github.com/ruvnet/ruview (MIT).

RuView does WiFi CSI human sensing: presence, breathing and heart rate, activity recognition, 17-keypoint pose, multi-person counting.
We are taking its capture and presence/localization path and dropping the parts we do not need.

Keep the line between upstream and our work explicit in code and on Devpost.
Judges reward a clearly-scoped modification and punish a fork presented as original work.
What is ours: the ANS identity layer, the agent mesh over the sensing output, the verified-caller path to a human 911 operator, and the compromised-sensor threat model.

## The event

VTHacks 14, Virginia Tech, September 18-20 2026.
Theme is "Code for the Cup" (soccer); the theme is not a requirement and we are not using it.
Submission deadline is Sunday September 20, 8:00 AM ET, which is also when judging starts.
Team of 4.

## Primary target: GoDaddy "Best Use of ANS"

Judged Sunday morning by Scott Courtney, GoDaddy VP Engineering and the architect of Agent Name Service.
Prizes are Meta Ray-Ban Gen 2, Beats Studio Pro, and a Cocopar portable monitor, one per team member by placement.

### What the track owner actually said

From the track briefing, in his framing rather than the spec's:

- The model is client agent to server agent. A shopper agent talking to a bank agent for microtransactions is his canonical example.
- ANS is the identifier layer for agents on the internet. `agent.webmesh.ai` is the example identifier format.
- **x509 certificates underpin agent identity.** He drew an explicit line against Cloudflare and DigiCert: certificates are GoDaddy's primary business, not a side offering. DNS protection on GoDaddy domains extends to agents.
- Agent cards must be kept updated. Public agents appear on the Trust Index inside GoDaddy. What counts as "public" is an open question he did not resolve.
- The framing he keeps returning to is the **strangers-can-trust problem**. RSA and VeriSign solved a version of this, but only ever proved one side of the connection.
- Agent sandbox breakout is the concern he hears from governments and industry.
- **Agents must be built and hosted on the internet, reachable.** Not localhost. This is a hard requirement, not a nicety.
- Agents get posted to an open agent store in the repo.

### Research he explicitly asked for

These are action items from the briefing, not optional background.

**All three were written 2026-09-19.** They live in `docs/`, not `docs/research/`, because they are deliverables rather than background.

1. `docs/fraud-13.md` - the 13 attacks at fraud.webmesh.ai, each translated into its Hawk Eye analogue. **The battery cannot be aimed at our agents** (no target parameter; hardwired to `supplier.webmesh.ai`, verified 2026-09-19), so we implement the shapes rather than invoke the suite. **All thirteen are implemented and passing** in `app/backend/tests/`; the results table is filled in.
2. `docs/geo.md` - GEO, and an opinion on the crawler tradeoff he raised without giving one.
3. `docs/threat-landscape.md` - current agent attacks, OSI coverage, OWASP ASI01-10, MAESTRO, sandbox breakout. The centerpiece of the three.

Three findings from that session changed how we build, not just what we say:

- **The ANS registry ships its own MAESTRO analysis** at `MAESTRO.md`. The track owner's project already mapped its architecture to the framework he asked us to research. Use his layer vocabulary; do not contradict it.
- **A spending mandate is to money what a verified sensing claim is to an armed response.** That substitution makes the entire fraud battery apply to a system that moves no money, and turns thirteen payment probes into a checklist for `master`. See `docs/fraud-13.md`.
- **The dispatch address is the binding that matters most.** An agent that can change where a response is sent is a swatting tool no matter how well the claims upstream verify. Bind it at registration and seal it; never carry it in a claim.

The OSI answer, in one line, because it is also the pitch line:
**ANS moves agent identity out of the application layer, where the application can lie about it, and anchors it in DNS and TLS, where it cannot.**

### ANS technical facts

ANS anchors agent identity to provable domain ownership.
Agents get version-bound certificates recording the specific code running at that moment.
Lifecycle events are sealed into an immutable SCITT transparency log where entries cannot be altered after the fact.
The spec is layered ANS-0 through ANS-6: proof-of-control, registration lifecycle, ANSName URIs and mTLS, DNS/DANE publication, transparency logging, integrity monitoring, and agent-to-agent auth via badges.

Verification is tiered: **Bronze** is PKI certificate validation, **Silver** adds DANE, **Gold** adds Transparency Log verification.
Three independent trust channels at Gold. Identity is graded Basic (DV), Verified (OV), Premium (EV).

The Trust Index scores agents across five dimensions: integrity, identity, solvency, behavior, safety.
**Only integrity and identity are implemented. Solvency, behavior, and safety are present in every response scored 0 until plug-in signals are registered.**
Eight built-in signals feed the two live dimensions: four raw observations (certificate type, DNSSEC status, agent age, version stability) and four drift verdicts (server cert fingerprint, identity cert fingerprint, DNS `_ans`, DNS `_ans-badge`).
The repo documents an explicit extension contract: implement the `port.Signal` interface (`Derived`, `Validate`, `Evaluate`), or write evidence producers in any language that POST to `/v1/internal/observations/import`.
There is no `port.Hydrator`; the interface **is** the HTTP boundary, and producers are treated as untrusted processes on the far side of it.

Shipping one of the three missing dimensions is the strongest available differentiator on this track.
Our sensing layer is a natural evidence producer for **safety**: a physical-world signal that an agent's claims match what is actually happening in the building. An agent that reported an unresponsive occupant to emergency services where no sensor corroborates one is behaving unsafely, and that is an observation worth posting.
See `ans/CLAUDE.md`.

Trust Index also returns a `recommendedProfile` policy hint: UNTRUSTED, READ_ONLY, TRANSACTIONAL, FIDUCIARY.
`agents/caller` uses these to decide what a sensing agent's claim is allowed to trigger.
An UNTRUSTED verdict is a **discovery-suppression** signal, not a revocation trigger; only the RA revokes certificates. Mirror that distinction in `master`.

Full threat mapping, and what each mechanism actually buys us per hour of work, is in `docs/threat-landscape.md`.

Repos:
- Specs and Trust Index: https://github.com/agentnameservice/ans-registry
- Reference implementation: https://github.com/agentnameservice/ans
- CLI/SDK (Go): https://github.com/agentnameservice/ans-sdk-go
- Trust Index reference implementation: https://github.com/agentnameservice/agent-trust-discovery

Free registration is available through GoDaddy.
Pull the reference codebase and run it locally first; it has an agent side and a skill side.

### Live agents at webmesh.ai

Use these rather than mocking counterparties.
All support A2A and MCP. Machine-readable index at `/.well-known/agents-index.json`.

- `agent.webmesh.ai` - verifies and discovers ANS-registered agents by FQDN
- `authority.webmesh.ai` - issues RFC 9421 spending mandates with cryptographic binding
- `auditor.webmesh.ai` - independently verifies transactions, produces signed reports
- `rogue-supplier.webmesh.ai` - adversarial test agent
- `fraud.webmesh.ai` - attack battery, 13 targeted security probes
- Also: `impact`, `dnsdoc`, `seo`, `traveler`, `supplier`

`fraud.webmesh.ai` is a **reference implementation of a threat model, not a scanner.**
Verified 2026-09-19 against its MCP endpoint: `run_battery` and all 13 attack tools take **no target parameter**, and the target is hardwired to `supplier.webmesh.ai`. It cannot be aimed at our agents.
Its value is the checklist, which is real. See `docs/fraud-13.md`.

**`agent.webmesh.ai` is the one that can be pointed at us**, and therefore the one to prepare for.
Its `verify_agent(agent_host, environment)` takes an arbitrary hostname and returns a `compatibility_verdict` built from DNS, DNSSEC, Transparency Log proof, and **the published agent card**, then sends a live A2A message and reports what credential we actually required.
That makes the agent card the surface under test. Hardening spec and checklist: `ans/CARD.md`.
It also unlocks a better demo beat than the refusal alone: point the judge's own verifier at our agents, live, and let his software confirm us in front of him.

## Hardware

**Step-by-step guides live in `docs/hardware/`.**
One guide per item, plus the hookup geometry and a linear bring-up checklist.
Start at `docs/hardware/README.md`; it carries the bill of materials, the order to do things in, and the one way each item fails quietly.
This section stays as the summary and the reasoning. The guides are the procedure.

Owned, and this is the final list:

- Raspberry Pi 4B kit: Pi, ethernet adapter, Cat5 cable, microSD, USB-C power
- **TP-Link Archer AX1450**, bought for this. Fixed channel, 80MHz, 802.11ac forced, band steering off. Config table in `sensor/CLAUDE.md`
- **The MacBook**, parked on the router's WiFi as the traffic generator. It is free at the house because Internet Sharing is only needed at a venue

**No further hardware is being purchased.** Plan around this rather than hoping.

The Pi 4B's BCM43455c0 is supported by `nexmon_csi`, so the CSI path needs nothing extra.
That path is still the project's largest single risk. See `sensor/CLAUDE.md` for kernel constraints and the fallback ladder.

Two things in `sensor/CLAUDE.md` are easy to miss and both fail quietly rather than loudly:

- **The Pi's network path is wired, always.** `nexmon_csi` holds the WiFi interface in monitor mode, so there is no station interface while capturing. The Cat5 cable is not a convenience.
- **CSI only updates when frames cross the monitored channel.** Without a traffic generator you get beacons at roughly 10 Hz, which barely resolves breathing and never resolves heart rate or a fall transient, with every component reporting healthy. `sudo ping -i 0.01 <gateway>` from the MacBook fixes it.
- **Geometry.** The Pi measures the channel between whoever transmitted and itself. Router and Pi go on **opposite sides** of the sensed space, with people in between. Side by side on one table produces a flat capture that looks exactly like a failed firmware patch.

`sensor/CLAUDE.md` carries the full topology for both the house shoot and the venue fallback, the router configuration table, and the power and subnet constraints.
`docs/hardware/assembly-and-placement.md` turns that into a wiring diagram and a placement procedure, and `docs/hardware/bring-up-checklist.md` turns it into a checklist with a verification command per step.

A registered domain is required regardless, because ANS is domain-anchored.
Register through GoDaddy Registry and the MLH "Best Domain Name" prize comes along for free.

### The honesty rule

**`docs/swapping-in-real-parts.md` is the switchboard**: every simulated or mocked thing, where its seam is, how to flip it, how to tell the flip worked, and which half-flipped states look like something else.
Read it before wiring anything real in.

Some capabilities are demonstrated rather than measured.
`agents/environment` is the clear case: no gas sensor exists, so the reading is simulated.
**The floor plan is the second case:** the system does not map walls and cannot, because walls are the static baseline it subtracts to see people. The room model is drawn once and room labels come from a one-time enrollment walk. See `sensor/CLAUDE.md`.

The rule for all of them:

1. **The agent, its ANS identity, its certificate, its card, and its contract are always real.** Those are what the track is judged on and they cost nothing extra.
2. **Simulated inputs are labeled in the data itself**, not just in a comment. `environment.source` carries `demo-trigger`. A simulated reading must not be presentable as measured by accident.
3. **Say it out loud on stage, before anyone asks.**

Framed this way it is a strength rather than an omission:

"Every agent here is registered, verified, and in the mesh. Some read live CSI off the router. One reads a simulated gas sensor because we did not buy one. Adding the real sensor is a driver behind an interface that already exists, and nothing above it changes."

That is a claim a judge can verify by reading the code, which is more than most demos can offer.
A fabricated measurement is the opposite: unverifiable, and fatal if caught.

Never claim a sensing capability the physics does not support.
CSI cannot measure gas composition; oxygen absorption is a ~60 GHz phenomenon and our radio is 2.4/5 GHz.
The one judge in the room most equipped to catch that is the one grading us.

## Other available tracks

MLH tracks are stackable and published: Gemini API, ElevenLabs, Solana, TigerData, Presage, Vultr, MongoDB Atlas, and Best Domain Name from GoDaddy Registry.

Plausible stacks given what we are already building:
- **Best Domain Name (GoDaddy Registry)** - free, required anyway.
- **ElevenLabs** - the 911 operator side is voice. A synthesized dispatcher reading interior state aloud is a strong demo beat and near-zero extra work.
- **Vultr** - the agents must be internet-reachable regardless, so host them there.
- **MongoDB Atlas / TigerData** - the event timeline has to persist somewhere.

VTHacks-branded tracks: 1st/2nd/3rd, Best First-Time Hack, Best Hack That Didn't Work, Best DEI Hack, Best UI/UX Hack, Best Ut Prosim Hack.
Ut Prosim is "That I May Serve," and a public safety project is squarely on theme.

Other sponsor tracks were TBD on Devpost and announce at opening: Impiricus, Peraton, Capital One (Nessie API), CoStar, Galois, Deloitte, Databricks, Procedura, Cloudforce.

## Ideas already rejected

Do not re-propose these.

- **Rotating savings circles (ROSCA, susu, tanda).** Costs ~45 seconds of audience education before the demo can start.
- **Restaurant bill splitting and grocery equivalents.** The merchant already splits checks at the POS.
- **Banking and personal finance generally.** Rejected by preference. A "trust gates capital" design was fully worked out and set aside.
- **Stock trading through a broker.** Brokers are a closed, regulated, already-verified set.
- **Flight recorder for unattended agents.** Was the live option before this pivot. Superseded, not disproven; the signed-action-graph idea may still be worth borrowing for the dispatch audit trail.

## Supporting research

### Incident data

Researched 2026-09-19, every figure sourced. See **`docs/research/`**:

- `incidents.md` - Fire, Burglary, Faint: annual figures, what actually kills people, and the synthesis for each
- `agent-briefs.md` - per-agent domain briefs and the thresholds each acts on
- `footage.md` - B-roll sourcing and licensing rules for the video

The headline is the **long lie**: the fall is not what kills, the time to discovery is, and that is the clinical outcome Hawk Eye moves.

### Agent-trust data

Verified during earlier sessions. Reusable for the pitch.

- DataDome, Jan-Feb 2026: 7.9B AI agent requests observed. Meta-ExternalAgent spoofed 16.4M times, ChatGPT-User 7.9M times. 2.4% of requests claiming to be PerplexityBot were fraudulent.
- Every major agentic payment protocol (Google AP2, Mastercard Agent Pay, Visa Trusted Agent Protocol, Anthropic MCP) defers trusted identity issuance to an entity not named in the specification. This is the core argument for why ANS exists.
- Thailand Ministry of Finance: threat actor ran the open-source Hermes agent in unattended "YOLO mode" for reconnaissance and credential theft. Discovered only because 585 files were left on an exposed server in Hong Kong. No audit trail, by design.
- Intruder.io scanned 3.5M live hosts, found 28,000 exposed `.git` repos leaking 400+ AWS keys, 107 Stripe keys, 123 OpenAI keys, 80 Telegram tokens, 17 GitHub PATs, many still active.
- postmark-mcp (Sept 2025): first in-the-wild malicious MCP server, ~300 orgs affected. Shai-Hulud 2.0 (Nov 2025): npm worm hitting 796 packages, specifically targeting MCP server packages.
- WEF projects 1 in 4 data breaches will result from AI agent exploitation by 2028.
- FBI IC3 2025: $893,346,472 in losses across 22,364 AI-referencing complaints. FTC imposter scams: $3.5B in 2025.
- Key paper: "The End of Trust: How Agentic AI Breaks Security Assumptions" (Zafar et al., 2026) introduces the **Infinite Impostor**, an agent that interposes itself between two parties who already trust each other. Argues detection-based defenses are finished because they assume synthetic output stays distinguishable.

The Infinite Impostor is our threat model stated precisely.
An impostor caller agent between a real household and a real PSAP is exactly that shape, and so is a compromised sensing agent between a real house and a real caller agent.

## 3D and Blender

Blender work is Claude-driven via headless `bpy` scripts, with a human directing the look.
Procedural and geometric scenes are the strength. Hand-sculpted organic assets are not.

Split:
- **Live app: pure Three.js / react-three-fiber**, procedural, driven by live CSI data. Do not round-trip simple dynamic primitives through Blender.
- **Blender: the cinematic layer.** Cycles-rendered hero loop for the Devpost page, pitch deck opener, and thumbnail.

The interior occupancy view is the natural 3D subject: a volumetric room with human presences resolving out of RF noise.

Use Eevee Next while iterating, Cycles for the final pass.
Keep hero loops to 4-6 seconds at 1080p with denoising.
Consider rendering the final Cycles pass on a Vultr GPU instance, which is a more defensible Vultr claim than merely hosting a web server there.

See `media/CLAUDE.md`.

## Verified local environment

- Blender 5.2.1 LTS at `/opt/homebrew/bin/blender` and `/Applications/Blender.app`
- Node v26.8.1
- Python 3.13.2
- Apple M2 Pro, Metal 4

Headless invocation: `blender --background --python script.py`

## Working agreements

- This is a 36-hour build. Prefer the boring, working path over the elegant, unproven one.
- Anything that must be demoed live needs a recorded fallback by Saturday night.
- The refusal path matters more than the happy path. A dispatch demo that works is unremarkable; a dispatch demo that correctly refuses an impostor is the submission.
