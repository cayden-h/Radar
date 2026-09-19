# Per-agent domain research

Researched 2026-09-19. One brief per agent: what it needs to know, what thresholds it acts on, and what it must not claim.

**Restructured 2026-09-19** when the roster was cut from nine agents to five.
Nothing was deleted; the briefs for `biometrics`, `occupancy` and `collapse` are now sections of `agents/people`, `environment` is a section of `agents/master`, and `guidance` is a section of `agents/caller`.
The merge rationale is in `agents/CLAUDE.md`; the domain facts below are unchanged, because the physics did not move.

Architecture and trust rules live in `agents/CLAUDE.md`. Signal-level detail lives in `sensor/CLAUDE.md`.
This file is the domain knowledge underneath both.

**Every "must not claim" line below is also published on the agent's own card** under `x-hawkeye.mustNotClaim`, and each one has a test in `agents/tests/`.
A limit that only exists in prose is a limit nobody checks.

Priority tiers match `agents/CLAUDE.md`.

---

## agents/people [tier 1]

**Question:** how many people, where, in what state, and is anyone down?

The load-bearing agent, and the only consumer of the CSI stream.
Three readers in a fixed order each tick: respiration, then presence, then collapse. Each depends on the one before.

### Personhood, respiration and heart rate

**The arbiter of personhood.** Everything downstream consumes this verdict.

- RuView ranges: respiration 6-30 BPM, heart rate 40-120 BPM.
- Normal resting adult respiration is 12-20 BPM. **Note the two ranges are different questions**: 6-30 is what we can measure, 12-20 is what is normal, and conflating them makes every infant an emergency.
- **Respiration carries every decision.** Chest wall displacement is 5-12mm for breathing versus a few tenths of a millimetre for a heartbeat, and the cardiac component sits under respiration harmonics.
- Heart rate is a stretch goal and a good number to say on the call. It is not a decision input.
- Heart rate is refused outright while the zone is moving. Movement is broadband and puts energy across the whole spectrum including that band; a peak found under those conditions is a peak in the movement, not in anybody's chest.

**Escalation-relevant:** respiration outside the normal band, or absent where a presence was previously breathing, is the signal that turns an occupancy report into a medical emergency.
"Unresponsive occupant in the main bedroom" originates here.

**Must not claim:** that absence of respiration proves absence of a person. Shallow breathing, breath-holding, and range limits all degrade toward invisible.
Cross-check the collapse reader and escalate uncertainty rather than resolving it silently. Reporting nothing is safer than reporting a number outside the supported range.

**Must not claim:** that heart rate is the personhood test. It is not, at any confidence.

### Location, count and class

- Zones are room-level. The literature on CSI localization does not support coordinates at this hardware tier, and claiming them invites a question we lose.
- Class comes from respiration rate, not amplitude. Resting rates: adult 12-20, child 20-30, infant 30-60, dog/cat 15-30+.
- The adult/child/pet boundaries **overlap**. Honest resolution is "adult versus small and fast-breathing."

**Needs a baseline.** The only part of the system that does. Rolling percentile, slow adaptation. See `sensor/CLAUDE.md`.
The baseline is over the *disturbance level*, not raw amplitude: a baseline over raw amplitude tracks the static multipath structure, which is not the thing a person changes.

**Counting is the weak capability and must not be overclaimed.** The BCM43455c0 is 1x1, so there is frequency diversity across subcarriers and no spatial diversity. Counting research generally uses 2-3 antenna NICs; RuView's 3-5 people per AP assumes its multi-node mesh.
Two people within roughly a metre merge into one. A still person beside a moving one is near-invisible to motion. Two people breathing at similar rates cannot be separated on one link.
**Source the headcount from device association against the roster** (`identity.md`) and let the radio answer which room and whether that presence is breathing.

The roster answer is produced whether or not the radio works. If CSI is dead and two phones are associated, "two residents are home" is still true and still the most useful thing a dispatcher can be told.

**Must not claim:** person re-identification. RuView flags it experimental and data-gated.
**Must not claim:** an exact sensed count, or coordinates.

### Falls, and the clinical variable

**This is where the strongest statistics belong.** See the faint/fall section of `incidents.md`.

- 43,020 deaths from preventable falls among adults 65+ in 2024. Fall deaths up 51% in ten years.
- **A "long lie" is clinically defined as being unable to get up for more than one hour.** Use that definition; it is not ours, it is the literature's.
- **53% of older fall patients were still on the floor when the ambulance arrived.**
- **Half of those who lay more than an hour died within six months, even absent injury from the fall itself.**
- 28% of community-dwelling older adults live alone; 42% of women 75+.

**The design consequence:** `still_down_s` is not a diagnostic detail, it is the clinical variable.
The literature's threshold is 60 minutes, and every minute below that is outcome we are buying back. Surface it, escalate on it, and say it aloud on the 911 call.
**Stamp it from the transient, not from the moment the agent became confident.** "She went down four minutes ago" is the sentence a dispatcher needs; "we decided twenty seconds ago" is not.

**Debounce is the whole engineering problem.** Sitting down fast, lying down to sleep, and a child playing all look like a fall for an instant.
The signature is collapse **followed by** absence of normal movement, cross-checked against the respiration verdict.
A system that calls 911 when someone flops onto a couch is worse than no system.

One implementation trap, because it fails silently: measure the stillness over frames **after** the transient, never over a window that still contains it. Measuring across it reads the fall itself as movement and discards the candidate one tick later.

Upstream gives us this: RuView ships fall detection at sub-200ms and exposes `fall-risk`, `no-movement`, `bed-exit`.

---

## agents/intruder [tier 1]

**Question:** which presence should not be here, and where is everybody?

Not merged into `people`, and the reason is the same principle that merged the others: it does not share an input. `people` reads the radio; this reads `people` plus the network.

**Domain notes**

- 405,776 residential burglaries in the US in 2024, 52% of all burglaries.
- **Daytime residential burglaries (216,601) outnumber nighttime (174,053).** Burglars prefer empty houses.
- The trend is strongly downward: rate down 69% since 2005, down 8.6% year over year. Do not pitch this as a growing crisis.

**The consequence for design:** the dangerous case is the minority where someone is home and the burglar did not expect it.
Our differentiator is not detection, it is **tracking intruder and resident as separately located presences** so responding officers know where both are.

**Decision rule must be stateable.** Roster plus device association: an unexpected presence is a body that no registered device accounts for.
"How do you tell a burglar from a roommate" is a certainty at judging, and the answer is that the roommate's phone is on the network.

**Name the holes.** A resident who left their phone in the car, a guest, a burglar carrying a phone that never associates. Every real security product has these gaps, and every assertion this agent makes carries them in its basis so they get said out loud.

**Gate on personhood.** Consume `people`. A perturbation with no respiration signature is a curtain. Calling police on a curtain is the failure mode.

**Must not claim:** which resolved presence is the stranger, when residents are also home. We know there is an extra body; without re-identification we cannot say which one, and guessing would send officers to the wrong room. Report every occupied zone and say so.

**Hold the track.** Once declared, hold it through clear ticks rather than dropping it on the first one. A track that flickers off because one window missed a breath tells an officer the intruder left.

See `incidents.md` for full burglary figures.

---

## agents/master [tier 1]

**Question:** what kind of incident is this, and who needs to know.

**Domain notes**

Classification should visibly combine signals rather than switch on one:

| Observation | Classification |
|---|---|
| Fall + elevated CO | Fire incident with a casualty, not a faint |
| Fall + normal air + no other presence | Faint, and nobody is coming to help |
| Unexpected presence + resident in a different room | Burglary in progress with occupants home |
| Unexpected presence + house registered empty | Burglary, no occupants at risk |

The second row is the one to lead with in the demo. It is the case where the statistics say the outcome is decided by discovery time.

**Strictest verification point in the system.** Every accepted claim carries source identity, Trust Index score at that instant, and a verification result. Anything unverifiable is discarded and logged as discarded.

**Must not claim:** that it may dial. A human tap is what releases `agents/caller`.
**Must not claim:** that an UNTRUSTED verdict revokes anything. Suppression is not revocation; only the RA revokes.

### Air quality

**Question:** is the air dangerous.

Absorbed from `agents/environment` on 2026-09-19. **Simulated. No sensor is being purchased.** The interface and master's handling of what comes through it are real; the number is not. It carries `demo-trigger`.

UL 2034 CO alarm thresholds, which is what a real device in this role would implement:

| CO level | Required alarm time |
|---|---|
| Below 30 ppm | No alarm before 30 days |
| 70 ppm | 60-240 minutes |
| 150 ppm | 10-50 minutes |
| 400 ppm | 4-15 minutes |

Health effects: above 200 ppm produces headache, dizziness and nausea quickly; **800 ppm and above can be fatal within minutes.**

Thresholds are derived from carboxyhaemoglobin loading via the Coburn-Forster-Kane equation.

Sources: [NFPA CO alarm threshold review](https://www.nfpa.org/education-and-research/research/fire-protection-research-foundation/projects-and-reports/a-review-of-the-carbon-monoxide-alarm-and-detection-thresholds), [CPSC UL 2034 conformance testing](https://www.cpsc.gov/s3fs-public/pdfs/COAlarmConformanceReportPhaseI.pdf)

**Make the mock ramp.** CO jumping 0 to 800 ppm in one sample is obviously synthetic. Ramp it through the UL bands on a realistic timescale, and start from a plausible household background of a few ppm rather than from zero.

**Why CO and not oxygen:** CSI cannot sense gas composition at all. Oxygen absorption is a ~60 GHz phenomenon; our radio is 2.4/5 GHz.
CO is also the correct signal on the merits: smoke inhalation alone is 35% of residential fire deaths against 6% for burns alone.

**Say it precisely:** possible with the right hardware. Never "CSI can detect gas."

**What absorbing it cost, stated rather than glossed:** read locally, the reading skips the verification gate, because master is both its producer and its consumer. It is labelled unverified-by-construction, capped at CORROBORATING however high the number climbs, and never speakable on its own. Every Fire classification requires a CSI-derived collapse alongside it.

---

## agents/caller [tier 1]

**Question:** what does a dispatcher need to hear, what are they asking, and what does the resident do next.

**Domain notes**

What a 911 dispatcher cannot get from any existing system, and can get from us:

- Number of occupants and their locations, room by room.
- Whether each is breathing.
- How long since someone went down.
- Whether an intruder and a resident are in different rooms.

Fire crews already know the house is burning. **What nobody knows is who is still inside and where**, and that is the entire value of the call.

**Inbound rules** are in `agents/CLAUDE.md` and are not optional: answer from a live verified query rather than cache, keep "I don't know" available, and never let an operator's authority widen what the agent will trust.

**Keep it short.** This is a live dispatcher, not a chat window. Lead with location and life status.

**Identify as an agent immediately, unasked.** A synthetic voice that lets a dispatcher assume it is a person is this project's own threat model being performed by the project.

**Never a silent hang-up.** An abandoned 911 call causes a dispatch: PSAPs treat a dropped call as real, call back, and send units when they cannot reach anyone. An accidental raise that is immediately cancelled should cost the dispatcher ten seconds, not a truck.

### The resident's side

Absorbed from `agents/guidance` on 2026-09-19. Same agent, second audience.

**Question:** what does the frightened person in the house do next.

**Safety rules, not style preferences. Bad first-aid instruction is real-world harm.**

- Stay inside well-established public protocols only: hands-only CPR, recovery position, stop-the-bleed. Do not improvise medical advice.
- **Always defer to the dispatcher.** If the operator is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained in emergency medical dispatch protocols; the agent is not. Enforced: relaying anything sets a deferral flag and the agent stops generating from that point.
- Never instruct an action that could injure the patient or the user. **Moving a fall victim is the canonical example**, and it appears in the protocol table as an explicit "do not" rather than being absent.
- "Wait for responders" is frequently the correct answer. Make sure the agent can give it.
- Fire guidance follows the timeline in `incidents.md`: one to two minutes to escape, modern rooms unsurvivable in under three. Guidance should be to leave, not to investigate.

**Match operator speech on meaning, not exact strings.** A dispatcher will not say the phrase anyone hardcoded. "Units are rolling" and "I've got help on the way" are the same fact.

**Relay half is high value. First-aid half is the one to cut if time runs out.**

`agents/caller/guidance.py` is the only place medical text exists in the system. The iOS client contains none and must not acquire any.

---

## agents/replay [tier 2]

**Question:** what happened, in what order, on whose authority.

Promoted from tier 3 on 2026-09-19. With five agents rather than nine there is more riding on each remaining hop being auditable.

**Domain notes**

- Two audiences: detectives after a burglary, and accountability for the system itself.
- Sealed into the SCITT transparency log; entries cannot be altered after the fact.
- This is where non-repudiation lives. The operator cannot verify us live; an investigator can verify the record afterward.
- **Swatting investigations are entirely post-hoc.** The FBI only began systematically tracking swatting in May 2023 via the NCOP database, precisely because these calls could not be attributed. That is the gap this agent speaks to.
- Discards are recorded with the same weight as acceptances. "It tells you what it discarded" is the sentence that carries the submission, and a record that only keeps what was accepted cannot support it.

**Do not claim** this prevents a malicious call. It makes one attributable.

**Do not claim** the local hash chain is a transparency-log seal. The chain is tamper-evident to whoever holds the record; the log is what makes it verifiable by someone who does not.
