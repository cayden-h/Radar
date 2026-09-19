# docs/

Research, the pitch, the agent roster, and the Devpost writeup.

## Layout

| | |
|---|---|
| `swapping-in-real-parts.md` | **Written 2026-09-19.** The switchboard. Every mock and simulated part, its seam, the flip, and the half-flipped states that waste an evening. |
| `hardware/` | **Written 2026-09-19.** Step-by-step guides for every hardware item, the hookup geometry, and a bring-up checklist. `hardware/README.md` is the index. |
| `notion-backup/` | Pre-write snapshots of the shared Notion page, taken before anything is appended to it. |
| `research/` | **Verified background, written 2026-09-19.** Incident statistics, per-agent domain briefs, footage licensing. Every figure sourced. Start there. |
| `fraud-13.md` | **Written 2026-09-19.** The 13 attacks at fraud.webmesh.ai, each mapped to its Hawk Eye analogue. Results column fills in once the agents are reachable. |
| `geo.md` | **Written 2026-09-19.** Generative Engine Optimization, plus an opinion on the crawler tradeoff. |
| `threat-landscape.md` | **Written 2026-09-19.** Agent attacks, OSI, OWASP ASI01-10, MAESTRO, sandbox breakout. The centerpiece of the three. |
| `pitch.md` | Not written. |

**The pitch deck lives in Notion**, not in this repo: [VT Hacks 2026](https://www.notion.so/3de46cd8aa248057a932d60d99ae80b3).
Slide-by-slide copy was appended 2026-09-19, following the LARP City deck format (Cayden's prior deck: title, founders, hook, turn, what-it-is, feature grid, **why-it's-useful numbers slide**, how-it-works, tech stack, thank you).

The numbers slide is the one that matters. Its six cards are drawn from `research/incidents.md` and every one is sourced.
A second optional numbers slide covers the ANS track for judging with Scott Courtney.

Notion note: the MCP connector returns 404 on that page (guest workspace). It is edited through the internal web API from a logged-in Chrome tab.
Teammates' existing blocks are left untouched; everything is appended.
Back the page up before every write. Backups live in `docs/notion-backup/`, not in the session scratchpad, so they survive the session.

Appended 2026-09-19, after the slide copy:

- **Architecture - Flowcharts.** Five Mermaid diagrams: system architecture and the two human boundaries, the faint path as a sequence (detection, alert, human tap, call), the refusal path, the iOS app flow, and the hardware topology.
- **The trust layer - how verification actually works.** Four more Mermaid diagrams, added 2026-09-19: the anatomy of a claim, the two-stage pipeline, the authentication-versus-authorization punchline, and where each of the thirteen attacks dies. This is the section to send someone who is lost in the security material.

**Mermaid diagrams are now version-controlled in the repo**, which they were not before:

| File | What it holds |
|---|---|
| `architecture-diagrams.md` | The five architecture diagrams. Source of truth; change here, then push to Notion. **Updated 2026-09-19 for the five-agent roster; the copies in Notion are stale until pushed.** |
| `trust-layer-explained.md` | The trust layer, four diagrams plus the prose that makes them land. |

**Flowchart 2 was wrong until 2026-09-19** and is worth knowing about, because the same error is easy to reintroduce in the deck and the video. It showed `master` releasing `caller` to dial with no human in between, which contradicts the settled decision and the shipped `assert_human_released()` guard. Detection is autonomous; the call is not.
- **Tech Stack.** Every layer with what it is actually doing, as callouts carrying live company logos. This expands Slide 9 rather than replacing it, and it ends with the honesty rule.

`research/CLAUDE.md` is the index. The three findings that carry the pitch are at the top of it.

**Open action item: write up the full agent list and responsibilities.** `agents/CLAUDE.md` is the working version; `docs/` gets the reader-facing one for the submission.
**The roster changed on 2026-09-19**, from nine agents to five, and anything written before that date describes the old one. The merge and its rationale are in `agents/CLAUDE.md` under "Why five and not nine"; the short version is that `biometrics`, `occupancy` and `collapse` became `people`, `environment` became an input to `master`, and `guidance` became the resident-facing half of `caller`. **Pushing the corrected Mermaid diagrams to Notion is part of this action item**, because the copies there still show nine.

This folder is not filler.
The track owner named three research items as action items in his own briefing, and the team that shows up Sunday having actually done them is a different team from the one that shows up with only code.

Read the root `CLAUDE.md` first.

## Assigned research

These came directly from the GoDaddy track briefing.
**All three were written 2026-09-19.** What follows is what each one landed on, and the one piece of work still outstanding.

### 1. The 13 attacks at fraud.webmesh.ai

`docs/fraud-13.md`. All thirteen documented, plus the two bonus structural checks.

The battery is built entirely around agentic payments: RFC 9421 mandates, DPoP, quote binding, EVM settlement.
A naive reading says none of it applies to a system that moves no money. That reading is wrong, and the correction is the most useful idea in the file:

**A spending mandate is to money what a verified sensing claim is to an armed response.**

Both are a scoped, signed, audience-bound, time-bound authorization that permits an irreversible act.
Once you make that substitution, thirteen payment probes become a checklist for `master`'s verification logic, and they are the source of the verification order now written into `agents/CLAUDE.md`.

The battery is thirteen ways of asking one question: **does this implementation treat a valid signature as authorization?** Ten of the thirteen pass only if the answer is no.

**Resolved 2026-09-19.** The battery cannot be aimed at us: verified against its MCP endpoint, `run_battery` and all thirteen attack tools take no target parameter and the target is hardwired to `supplier.webmesh.ai`. It is a reference implementation of a threat model, not a scanner.
So we implemented all thirteen shapes ourselves against `app/backend/hawkeye_backend/verification/`, and they pass. Writing them found two real bugs, both recorded in `docs/fraud-13.md` rather than quietly cleaned up.
The line for stage: "His battery only attacks his own supplier, so we implemented all thirteen against ours. Here they are, and here are the two bugs they found."
Run it Saturday, record all thirteen verdicts verbatim including failures, and fill the column in.
"We ran your attack suite, here are the thirteen results" is the strongest single sentence available to us on Sunday morning, and it is only available if we actually ran it.

### 2. GEO, Generative Engine Optimization

`docs/geo.md`. The weakest of the three ties to Hawk Eye, written because it was assigned, and the connection that does exist is not the obvious one.

GEO is usually filed as a marketing problem. Filed correctly it is an **identity and provenance problem**: retrieval works on textual features alone because a retrieved document carries no verifiable statement of who wrote it or whether it has changed since. That is the same unbacked application-layer claim as a self-asserted `User-Agent` header.

**GEO is what happens to retrieval when sources have no identity layer. It is the same gap ANS closes for agents, showing up one layer over.**

On the crawler tradeoff he raised without a recommendation, the file takes a position: block training crawlers, allow answering crawlers, never by category, and never treat `robots.txt` as access control. The closing point is the one worth saying to him, because it answers the question rather than picking a side: **the tradeoff only exists because crawler identity is unverifiable.**

### 3. The current agent attack landscape

`docs/threat-landscape.md`. The centerpiece of the three, and the one to read if only one gets read.

Covers OWASP ASI01-ASI10 each mapped to a concrete Hawk Eye defense, MAESTRO's seven layers, OSI coverage, the 2026 sandbox-breakout incidents, and a ranked defense stack ordered by value per hour of work rather than architectural elegance.

Three things in it change how we build:

- **The ANS registry ships its own MAESTRO analysis.** The track owner's project already mapped its architecture to the framework he asked us to research. Two mechanisms in it are worth borrowing: **Status Tokens** (OCSP-style stapled proof that an agent is still ACTIVE, which matters because a SCITT receipt proves "was registered" and never expires) and **suppression before revocation**.
- **The OSI answer is also the pitch line.** ANS moves agent identity out of the application layer, where the application can lie about it, and anchors it in DNS and TLS, where it cannot.
- **ASI09, human-agent trust exploitation, is where this project differs from everything else on the track.** Elsewhere it costs money. Here it costs someone a police response to their front door.

It also states our own exposure plainly: the CSI parser handles untrusted binary input, and we have no TEE attestation. Both are named in the file rather than left to be found.

## The pitch

Deliverable: `docs/pitch.md`.

The argument, in order:

1. Agents are meeting strangers on the open web, at scale, right now. RSA and VeriSign solved a version of this, but only ever proved one side of the connection.
2. Every major agentic payment protocol defers trusted identity issuance to an entity not named in its own specification. That gap is what ANS fills.
3. Identity failures today cost money. Ours costs an armed response sent to a real address on fabricated evidence.
4. So the agent that speaks to 911 repeats only what it can cryptographically verify, and says what it discarded. When the operator asks a follow-up, the answer comes from a fresh verified query, not from memory.
5. Here is a compromised sensing agent being discarded, driven by your own attack battery.

If a judge asks what the radio can actually do, the honest short answer is the strongest one: motion and breathing need no calibration at all, counting and localization need a baseline, and breathing is what tells a person from a curtain.

Then name the gap: the operator still cannot verify us live, because no dispatch center runs software we can ship to. That is the next step, not a flaw we hid.

### The ANS numbers

The Notion deck has a **Slide 6b, an optional second numbers slide for the ANS / GoDaddy track**, to be used when judging with Scott Courtney.
Slide 6 carries the incident figures. These are the six for 6b, same card format, all sourced in `docs/threat-landscape.md`:

| Number | Claim |
|---|---|
| **7.9B** | AI agent requests observed by DataDome in Jan-Feb 2026. |
| **16.4M** | Times Meta-ExternalAgent was spoofed in that window. ChatGPT-User, 7.9M. |
| **2.4%** | Of requests claiming to be PerplexityBot were fraudulent. Agent identity today is a self-asserted string. |
| **4 of 4** | Major agentic payment protocols (Google AP2, Mastercard Agent Pay, Visa TAP, Anthropic MCP) defer trusted identity issuance to an entity not named in their own spec. |
| **3 labs, 0 caught live** | OpenAI, Anthropic, and Moonshot AI all had agents escape sandboxes in 2026. None was detected in real time. |
| **1 in 4** | Data breaches WEF projects will result from AI agent exploitation by 2028. |

The line that ties them together, matching Slide 6's format:
**Agent identity today is a string the agent chose for itself. Everything above is what happens when nothing checks it.**

Then the turn, which is the whole reason this project is on this track: those failures cost money. Ours costs an armed response sent to a real address.

Open on the fall, then the tap. Hawk Eye does not call 911 by itself and the pitch should say so early, before a judge wonders.

Keep the education budget near zero.
Everyone in the room already understands what a 911 call is, and everyone has heard of swatting.
Be careful with swatting specifically: it motivates the problem, but we do not prevent it. We make a call attributable after the fact. State it that narrowly.
That was the fatal flaw in the rejected ROSCA idea, and this project's main advantage over it.

## Supporting evidence

### The incident data

**In `research/incidents.md`, with sources.** The three that carry the pitch:

- **The long lie.** Half of older adults who lie on the floor over an hour after a fall die within six months, even absent injury from the fall. 53% are still there when the ambulance arrives. The fall is not what kills; discovery time is.
- **Unconscious before aware.** House fire toxic gases can render someone unconscious in under a minute, often before they know there is a fire. A modern room is unsurvivable in under three.
- **28% of older adults live alone**, 42% of women over 75.

Together: **by the time a human calls, the information that decides the outcome is already lost to them.** How long they have been down. Which room. Whether they are breathing.

That is the argument for Hawk Eye, and it is stronger than anything in the ANS material because a judge feels it immediately.

**It is not an argument for autonomy, and we did not build autonomy.** Settled 2026-09-19: a person taps, and only then does the system call. Say that out loud early. Every other agent demo this weekend argues its agent deserves more trust; drawing the line here, in front of a judge who has spent the weekend hearing about sandbox breakout, is a stronger position than the one we gave up.

Be careful with burglary. The trend is strongly downward, 69% since 2005, and a judge may know that. Pitch it as a capability demonstration, not a crisis.

### The agent-trust data

Gathered in earlier sessions. Full list in the root `CLAUDE.md` under "Supporting research."
The three that carry the most weight:

- **DataDome, Jan-Feb 2026.** 7.9B AI agent requests observed. Meta-ExternalAgent spoofed 16.4M times, ChatGPT-User 7.9M times. 2.4% of requests claiming to be PerplexityBot were fraudulent. Agent impersonation is not hypothetical and the numbers are enormous.
- **Zafar et al., 2026, "The End of Trust."** The Infinite Impostor: an agent that interposes itself between two parties who already trust each other. This is our threat model exactly. The paper argues detection-based defenses are finished because they assume synthetic output stays distinguishable.
- **Thailand Ministry of Finance.** An agent run unattended for reconnaissance and credential theft, discovered only by accident, with no audit trail by design. Justifies the SCITT transparency log.

## Devpost

Deliverable: the submission itself, drafted here first.

Hard deadline **Sunday September 20, 8:00 AM ET**, which is also when judging begins.
Draft Saturday. Do not write it Sunday morning.

Must include:
- The demo video. It is the submission's centerpiece, not an attachment.
- The agent roster and what each one is responsible for. Five agents, as of 2026-09-19.
- A clear statement of what is ours versus what came from RuView (MIT). See the root file's upstream hygiene note.
- The hero loop from `media/`.
- **The three assigned research deliverables**, linked: `fraud-13.md`, `geo.md`, `threat-landscape.md`. The track owner named them as action items in his own briefing. A submission that links them is a different submission from one that only links code.
- Honest scoping, stated rather than buried. See the honesty rule in the root `CLAUDE.md`. Name each of these explicitly:
  - `agents/master` reads a simulated gas sensor. No hardware was bought. The interface is real and a sensor drops in behind it.
  - We do not do person re-identification. RuView flags it experimental and data-gated.
  - We do not detect fire. We detect who is inside and whether they are breathing.
  - We do not identify specific people. `agents/intruder` infers that a presence is unexpected from context, not from recognizing anyone. Be ready for "how do you tell a burglar from a roommate."
  - Body-type classification comes from **respiration rate**, and adult/child/pet ranges overlap. Say "adult versus small and fast-breathing," not "we identify pets."
  - Heart rate is reported but respiration carries every decision. Chest displacement from a heartbeat is an order of magnitude smaller and mostly buried under breathing harmonics.
  - Counting and localization need a baseline and therefore stay in the recorded video. Only motion sensing is environment-independent enough for a judging hall.
  - First-aid guidance stays inside established public protocols and always defers to the dispatcher.
  - We do not give the 911 operator live verification. The operator talks to the agent in plain English, both ways, and a person cannot check a certificate. What we secure is every machine hop behind that voice, plus after-the-fact attribution.
  - We do not prevent swatting. We make a call attributable after the fact. State it that narrowly.
  - We have no TEE attestation of the sensing runtime, so we score zero on the Trust Index `enclaveAttestation` signal. That is the correct score and we say why.
  - The CSI ingest path parses untrusted binary from a patched firmware blob. Containment comes from the wired-only network path and from credential separation, not from the parser being good.
  - We did not run his battery against our agents, because it cannot be aimed at anything but `supplier.webmesh.ai`. We reimplemented all thirteen shapes. Say it that way; implying we ran his suite is the kind of claim that dies to one question from the person who wrote it.

  Overclaiming any of these is how a good project loses to a single question.

## Writing conventions

One full sentence per line in long Markdown files.
No blockquotes. No em dashes.
