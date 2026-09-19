# Per-agent domain research

Researched 2026-09-19. One brief per agent: what it needs to know, what thresholds it acts on, and what it must not claim.

Architecture and trust rules live in `agents/CLAUDE.md`. Signal-level detail lives in `sensor/CLAUDE.md`.
This file is the domain knowledge underneath both.

Priority tiers match `agents/CLAUDE.md`.

---

## agents/occupancy [tier 1]

**Question:** how many people, where, and what kind.

**Domain notes**

- Zones are room-level. The literature on CSI localization does not support coordinates at this hardware tier, and claiming them invites a question we lose.
- Class comes from respiration rate, not amplitude. Resting rates: adult 12-20, child 20-30, infant 30-60, dog/cat 15-30+.
- The adult/child/pet boundaries **overlap**. Honest resolution is "adult versus small and fast-breathing."

**Needs a baseline.** The only tier 1 agent that does. Rolling percentile, slow adaptation. See `sensor/CLAUDE.md`.

**Must not claim:** person re-identification. RuView flags it experimental and data-gated.

---

## agents/intruder [tier 1]

**Question:** which presence should not be here.

**Domain notes**

- 405,776 residential burglaries in the US in 2024, 52% of all burglaries.
- **Daytime residential burglaries (216,601) outnumber nighttime (174,053).** Burglars prefer empty houses.
- The trend is strongly downward: rate down 69% since 2005, down 8.6% year over year. Do not pitch this as a growing crisis.

**The consequence for design:** the dangerous case is the minority where someone is home and the burglar did not expect it.
Our differentiator is not detection, it is **tracking intruder and resident as separately located presences** so responding officers know where both are.

**Decision rule must be stateable.** Without re-identification, "unexpected" has to come from context: entry through an unusual point, presence when the house is registered empty, a count exceeding what residents reported, movement inconsistent with residents.
Pick one and be able to say it. "How do you tell a burglar from a roommate" is a certainty at judging.

**Gate on personhood.** Consume `biometrics`. A perturbation with no respiration signature is a curtain. Calling police on a curtain is the failure mode.

See `incidents.md` for full burglary figures.

---

## agents/biometrics [tier 1]

**Question:** is this a living person, and what is their respiration and heart rate.

**The arbiter of personhood.** Everything downstream consumes this verdict.

**Domain notes**

- RuView ranges: respiration 6-30 BPM, heart rate 40-120 BPM.
- Normal resting adult respiration is 12-20 BPM.
- **Respiration carries every decision.** Chest wall displacement is 5-12mm for breathing versus a few tenths of a millimetre for a heartbeat, and the cardiac component sits under respiration harmonics.
- Heart rate is a stretch goal and a good number to say on the call. It is not a decision input.

**Escalation-relevant:** respiration outside the normal band, or absent where a presence was previously breathing, is the signal that turns an occupancy report into a medical emergency.
"Unresponsive occupant in the west bedroom" originates here.

**Must not claim:** that absence of respiration proves absence of a person. Shallow breathing, breath-holding, and range limits all degrade toward invisible.
Cross-check `collapse` and escalate uncertainty rather than resolving it silently. Reporting nothing is safer than reporting a number outside the supported range.

---

## agents/collapse [tier 1]

**Question:** did someone go down, and are they still down.

**This is the agent the strongest statistics belong to.** See the faint/fall section of `incidents.md`.

**Domain notes**

- 43,020 deaths from preventable falls among adults 65+ in 2024. Fall deaths up 51% in ten years.
- **A "long lie" is clinically defined as being unable to get up for more than one hour.** Use that definition; it is not ours, it is the literature's.
- **53% of older fall patients were still on the floor when the ambulance arrived.**
- **Half of those who lay more than an hour died within six months, even absent injury from the fall itself.**
- 28% of community-dwelling older adults live alone; 42% of women 75+.

**The design consequence:** `still_down_s` is not a diagnostic detail, it is the clinical variable.
The literature's threshold is 60 minutes, and every minute below that is outcome we are buying back. Surface it, escalate on it, and say it aloud on the 911 call.

**Debounce is the whole engineering problem.** Sitting down fast, lying down to sleep, and a child playing all look like a fall for an instant.
The signature is collapse **followed by** absence of normal movement, cross-checked against `biometrics`.
A system that calls 911 when someone flops onto a couch is worse than no system.

Upstream gives us this: RuView ships fall detection at sub-200ms and exposes `fall-risk`, `no-movement`, `bed-exit`.

---

## agents/environment [tier 3]

**Question:** is the air dangerous.

**Simulated. No sensor is being purchased.** The agent, its ANS identity, and the driver interface are real; the number is not. `environment.source` carries `demo-trigger`.

**Domain notes, for making the mock plausible and the claim honest**

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

**Make the mock ramp.** CO jumping 0 to 800 ppm in one sample is obviously synthetic. Ramp it through the UL bands on a realistic timescale.

**Why CO and not oxygen:** CSI cannot sense gas composition at all. Oxygen absorption is a ~60 GHz phenomenon; our radio is 2.4/5 GHz.
CO is also the correct signal on the merits: smoke inhalation alone is 35% of residential fire deaths against 6% for burns alone.

**Say it precisely:** possible with the right hardware. Never "CSI can detect gas."

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

---

## agents/caller [tier 1]

**Question:** what does a dispatcher need to hear, and what are they asking.

**Domain notes**

What a 911 dispatcher cannot get from any existing system, and can get from us:

- Number of occupants and their locations, room by room.
- Whether each is breathing.
- How long since someone went down.
- Whether an intruder and a resident are in different rooms.

Fire crews already know the house is burning. **What nobody knows is who is still inside and where**, and that is the entire value of the call.

**Inbound rules** are in `agents/CLAUDE.md` and are not optional: answer from a live verified query rather than cache, keep "I don't know" available, and never let an operator's authority widen what the agent will trust.

**Keep it short.** This is a live dispatcher, not a chat window. Lead with location and life status.

---

## agents/guidance [tier 2]

**Question:** what does the frightened person in the house do next.

**Safety rules, not style preferences. Bad first-aid instruction is real-world harm.**

- Stay inside well-established public protocols only: hands-only CPR, recovery position, stop-the-bleed. Do not improvise medical advice.
- **Always defer to the dispatcher.** If the operator is giving instructions, relay theirs rather than generating competing ones. Dispatchers are trained in emergency medical dispatch protocols; the agent is not.
- Never instruct an action that could injure the patient or the user. **Moving a fall victim is the canonical example.**
- "Wait for responders" is frequently the correct answer. Make sure the agent can give it.
- Fire guidance follows the timeline in `incidents.md`: one to two minutes to escape, modern rooms unsurvivable in under three. Guidance should be to leave, not to investigate.

**Relay half is tier 2 and high value. First-aid half is the one to cut if time runs out.**

---

## agents/replay [tier 3]

**Question:** what happened, in what order, on whose authority.

**Domain notes**

- Two audiences: detectives after a burglary, and accountability for the system itself.
- Sealed into the SCITT transparency log; entries cannot be altered after the fact.
- This is where non-repudiation lives. The operator cannot verify us live; an investigator can verify the record afterward.
- **Swatting investigations are entirely post-hoc.** The FBI only began systematically tracking swatting in May 2023 via the NCOP database, precisely because these calls could not be attributed. That is the gap this agent speaks to.

**Do not claim** this prevents a malicious call. It makes one attributable.
