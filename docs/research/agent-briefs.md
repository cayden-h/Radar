# Per-agent domain research

Researched 2026-09-19. One brief per agent: what it needs to know, what thresholds it acts on, and what it must not claim.

**Restructured 2026-09-19** when the roster was cut from nine agents to five.
Nothing was deleted in that merge; the briefs for `biometrics`, `occupancy` and `collapse` became sections of `agents/people`, `environment` a section of `agents/master`, and `guidance` a section of `agents/caller`.
The merge rationale is in `agents/CLAUDE.md`; the domain facts below are unchanged, because the physics did not move.

**Fall detection was then cut on 2026-09-19** and the collapse reader was deleted.
What replaced it is responsiveness: `people.respiration_lost`, the seconds since a breathing signature was last resolvable on a presence that previously had one.
The fall statistics are not deleted either - they are kept, as history, in the Faint section of `incidents.md`, because a decision you cannot explain is a decision you cannot defend.

Architecture and trust rules live in `agents/CLAUDE.md`. Signal-level detail lives in `sensor/CLAUDE.md`.
This file is the domain knowledge underneath both.

**Every "must not claim" line below is also published on the agent's own card** under `x-hawkeye.mustNotClaim`, and each one has a test in `agents/tests/`.
A limit that only exists in prose is a limit nobody checks.

Priority tiers match `agents/CLAUDE.md`.

---

## agents/people [tier 1]

**Question:** how many people, where, in what state, and should a dispatcher expect an answer?

The load-bearing agent, and the only consumer of the CSI stream.
Two readers in a fixed order each tick: respiration, then presence. The second depends on the first.

### Personhood, respiration and heart rate

**The arbiter of personhood.** Everything downstream consumes this verdict.

- RuView ranges: respiration 6-30 BPM, heart rate 40-120 BPM.
- Normal resting adult respiration is 12-20 BPM. **Note the two ranges are different questions**: 6-30 is what we can measure, 12-20 is what is normal, and conflating them makes every infant an emergency.
- **Respiration carries every decision.** Chest wall displacement is 5-12mm for breathing versus a few tenths of a millimetre for a heartbeat, and the cardiac component sits under respiration harmonics.
- Heart rate is a stretch goal and a good number to say on the call. It is not a decision input.
- Heart rate is refused outright while the zone is moving. Movement is broadband and puts energy across the whole spectrum including that band; a peak found under those conditions is a peak in the movement, not in anybody's chest.

**Escalation-relevant:** respiration outside the normal band, or absent where a presence was previously breathing, is the signal that turns an occupancy report into a medical emergency.
"I had a breathing signature in the main bedroom four minutes ago and I do not have one now" originates here.

**Must not claim:** that absence of respiration proves absence of a person. Shallow breathing, breath-holding, and range limits all degrade toward invisible.
Escalate the uncertainty rather than resolving it silently. Reporting nothing is safer than reporting a number outside the supported range.

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

### Responsiveness, and what replaced the fall clock

**The question a dispatcher needs answered is whether to expect a response from a room**, and that is narrower than "did someone fall".

`people.respiration_lost` carries the seconds since a breathing signature was last resolvable on a presence that previously had one.
**The transition is the signal.** A presence that never resolved a signature produces nothing, because shallow breathing, breath-holding and range limits are indistinguishable from an empty room, and a claim that cannot tell those apart tells a dispatcher nothing.

**Stamp it from the last resolvable signature, not from the moment the agent became confident.** "I had breathing there four minutes ago" is the sentence a dispatcher needs; "we decided twenty seconds ago" is not.

- 28% of community-dwelling older adults live alone; 42% of women 75+. There is often nobody in the building to answer for them.
- House fire toxic gases can render someone unconscious in under a minute, often before they know there is a fire, and a modern room is unsurvivable in under three. Figures and sources in `incidents.md`.

**Must not claim:** that a person has stopped breathing. A signature that is no longer resolvable is a reason to look, never a finding about a body.

**Must not claim:** anything at all about a presence that never established a breathing signature. A moving body swamps its own chest sinusoid with broadband motion, so someone who goes from walking to gone leaves no transition to report. That limit is the price of the claim being worth anything.

**Fall detection was cut on 2026-09-19.** Debounce was the whole engineering problem and it never got better: sitting down fast, lying down to sleep and a child playing all look like a fall for an instant, and a system that calls 911 when someone flops onto a couch is worse than no system.
RuView does ship fall detection upstream, at sub-200ms, with `fall-risk`, `no-movement` and `bed-exit`. We are not using it.
The statistics that motivated the original design are kept in the Faint section of `incidents.md`.

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

| Observation                                           | Classification                           |
|-------------------------------------------------------|------------------------------------------|
| Elevated CO + a lost breathing signature              | Fire, with someone who may not respond   |
| Elevated CO + a still, breathing presence             | Fire, with someone who is not moving     |
| Elevated CO + every resolved presence up and breathing | Fire, everyone on their feet             |
| Elevated CO + no presence resolved at all             | Fire, occupancy unknown                  |
| Unexpected presence + resident in a different room    | Burglary in progress with occupants home |
| Unexpected presence + house registered empty          | Burglary, no occupants at risk           |

`agents/master/classify.py` quotes this table in its module docstring. The two must match exactly; change them together.

**The first row is the one to lead with in the demo**, and it is the only row built from two independent modalities: CSI resolved the breathing, a separate gas sensor read the air. Two views of one CSI stream agreeing is not corroboration; this is.

The second row ranks below it deliberately. A lost signature means something changed; a still, breathing presence means something has not, and a radio that sees stillness and breathing cannot separate unconsciousness from sleep.
The fourth row exists because "every presence the radio resolves is breathing and moving" is vacuously true over an empty set, and an empty set is exactly what an unreachable or fully-discarded `people` produces. That row says so out loud rather than reassuring a dispatcher about a building nothing has told us anything about.

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

**What absorbing it cost, stated rather than glossed:** read locally, the reading skips the verification gate, because master is both its producer and its consumer. It is labelled unverified-by-construction, capped at CORROBORATING however high the number climbs, and never speakable on its own. The two corroborated Fire rows each require a CSI-derived respiration claim alongside it.

---

## agents/caller [tier 1]

**Question:** what does a dispatcher need to hear, what are they asking, and what does the resident do next.

**Domain notes**

What a 911 dispatcher cannot get from any existing system, and can get from us:

- Number of occupants and their locations, room by room.
- Whether each is breathing.
- How long since a breathing signature that was resolvable in a room stopped being resolvable, which is what decides whether to expect an answer from it.
- Whether an intruder and a resident are in different rooms.

Fire crews already know the house is burning. **What nobody knows is who is still inside and where**, and that is the entire value of the call.

**Inbound rules** are in `agents/CLAUDE.md` and are not optional: answer from a live verified query rather than cache, keep "I don't know" available, and never let an operator's authority widen what the agent will trust.

**Keep it short.** This is a live dispatcher, not a chat window. Lead with location and life status.

**Identify as an agent immediately, unasked.** A synthetic voice that lets a dispatcher assume it is a person is this project's own threat model being performed by the project.

**Never a silent hang-up.** An abandoned 911 call causes a dispatch: PSAPs treat a dropped call as real, call back, and send units when they cannot reach anyone. An accidental raise that is immediately cancelled should cost the dispatcher ten seconds, not a truck.

### The resident's side

Absorbed from `agents/guidance` on 2026-09-19. Same agent, second audience.

**Question:** what does the frightened person in the house do next.

**Safety rules, not style preferences. A bad safety instruction is real-world harm.**

**There is no patient-care protocol, and the absence is deliberate.** CPR and the recovery position went with the Faint incident type on 2026-09-19.
Neither surviving incident type is one where staying to help is correct guidance: during a fire the protocol is to leave and stay out, and during a burglary it is to stay hidden and not confront anyone.

- Stay inside well-established public protocols only: fire-ground guidance, and the dispatcher's own words. Do not improvise medical advice.
- **Always defer to the dispatcher.** If the operator is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained in emergency medical dispatch protocols; the agent is not. Enforced: relaying anything sets a deferral flag and the agent stops generating from that point.
- Never instruct an action that could injure the user or the person they are worried about. The protocol table carries its do-nots explicitly rather than leaving them absent: do not go back into a fire, do not go looking during a burglary, do not confront anyone.
- "Wait for responders" is frequently the correct answer. Make sure the agent can give it.
- Fire guidance follows the timeline in `incidents.md`: one to two minutes to escape, modern rooms unsurvivable in under three. Guidance should be to leave, not to investigate.

**Match operator speech on meaning, not exact strings.** A dispatcher will not say the phrase anyone hardcoded. "Units are rolling" and "I've got help on the way" are the same fact.

**Relay half is high value. The safety-instruction half is the one to cut if time runs out.**

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
