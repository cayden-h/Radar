# Tagging people: what is possible, what ships, what is roadmap

Settled 2026-09-19. Read before writing anything in `agents/occupancy` or `agents/intruder`
that sounds like it identifies a person.

## The rule

**Hawk Eye tracks presences, not identities.**
Identity, where it exists at all, comes from **devices the resident chose to put on their own network** - never from the body.

This is a technical limit and a product position, and they happen to agree.

## Why CSI cannot identify a body

WiFi person identification is a real research area (WiWho, WifiU, FreeSense). It works on **gait**.
Reported accuracy of 80-95% comes with conditions that disqualify it here:

- Per-person enrollment with labeled training data
- Same environment only; models do not transfer between rooms
- Small closed sets, typically 2-6 people
- **The subject must be walking**

That last condition kills it for our headline scenario. **A person motionless on a bedroom floor has no gait.**
The one case where identity would matter most is the one case gait recognition cannot address even in a lab.

RuView says the same: named re-identification is experimental and data-gated, not a shipped feature.

## What ships: roster plus device association

The household is **configuration, not a discovery problem.** A home system knows who lives there.

```
CSI:            3 distinct presences in the house
Roster:         2 registered residents
Associated:     2 resident phones on the network
                ---------------------------------
                1 body with no corresponding device
```

That is a rule we can state on stage, and it is what makes `agents/intruder` defensible.
It survives "how do you tell a burglar from a roommate": the roommate's phone is on the network.

**Name the holes rather than pretending there are none.** A resident who left their phone in the car.
A guest. A burglar carrying a phone that never associates. Every real security product has these gaps.

Randomized MACs are stable per-network, so on the home router a phone presents a consistent address.

## Roadmap: binding at the boundary

The design, for the roadmap slide. **Not buildable before submission.**

`nexmon_csi` captures CSI per frame, and frames carry a transmitter address.
`makecsiparams -c 36/80 -C 1 -N 1 -m <mac>` filters capture to one device, so a per-device channel stream is available.

### Bind at the door, maintain by tracking

Identity is assigned at the boundary and then carried by the track, the way a badge-in system works.
Entry is the ideal binding moment for four reasons:

- The phone association is a discrete timestamped event.
- The body crossing the entry zone is discrete too: one presence where there were none.
- Both are moving, which is the best SNR available for correlating them.
- A doorway is one body wide. Two people cannot occupy it ambiguously.

**Once bound, the label follows the body, not the phone.** Put the phone on the nightstand and the label stays with the person.

**Re-entry re-anchors.** This is self-healing, not merely a reset: every door crossing is a chance to correct a drifted label.
A system that re-anchors several times a day degrades far more gracefully than one that binds once at boot.

### Correlate motion, not position

Do not try to match phone position to body position. Localizing a transmitter needs angle-of-arrival, which needs an antenna array.
**The BCM43455c0 is 1x1.** No bearing. Position matching would compound two coarse estimates.

Correlate **timing** instead. When a body moves, its presence channel perturbs; if the phone is on that body, that phone's channel perturbs at the same instant. Binding confidence rises with each correlated event. This works without AoA.

### Why this beats gait recognition

You label the person **while they are walking** and carry the label forward when they lie down.
It sidesteps the exact failure that makes gait ID useless here.

## How it breaks

| Failure | Consequence |
|---|---|
| Two people pass close; tracks merge then split | **Labels swap silently and stay swapped** |
| Someone sits still long enough to fade into the baseline | Track dies; they stand up unlabeled |
| Coverage gap between rooms | Track drops, new track on the far side |
| Two people enter together | Two associations seconds apart; binding ambiguous |
| Phone associates from the driveway | Association precedes the body by 10-20s; match on a window, not an instant |
| Phone in power save, screen off, in a pocket | Frames seconds apart. Fine for presence, thin for correlation |

The merge-and-swap case is the dangerous one, because afterwards the system is not uncertain. It is **confidently wrong.**

## The safety rule

**Labels decorate. They never determine.**

The physical observation is always true: a body is down and not breathing normally.
The name attached to it is a hypothesis with a confidence that decays since the last anchor.

- On an ambiguous merge, **drop the label rather than guess.** An unlabeled presence is strictly better than a wrong one.
- A label alone never triggers an action.
- Where a label and a physical observation disagree, **the body is the truth and the label is what is wrong.**
- On the 911 call, state the physical fact plainly and hedge the identity:
  "an occupant is down and not breathing normally; we believe it is the resident registered to the second phone."

Telling a dispatcher that a specific named person is down, when the labels swapped an hour earlier, is a real-world harm rather than a demo bug.

## The privacy argument for stopping here

The pitch is "no camera, no microphone; it reads a signal already passing through the house."

**Person identification would undercut that.** A through-wall sensor that recognises specific individuals by body is a far more alarming product than one that counts anonymous presences. There is no lens to cover and nothing to unplug.

The better answer, and the true one:

"We track presences, not identities. Identity comes from the devices you already chose to put on your own network."

For the per-person agents on the roadmap, medical context is keyed off the **roster**. The system knows a resident has a pacemaker because someone typed it in, not because the WiFi recognised them.
