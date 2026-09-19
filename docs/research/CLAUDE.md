# docs/research/

Verified background research. Written 2026-09-19.

Everything here was checked against a primary or near-primary source during that session, and the sources are linked inline in each file.
**Do not add a number to these files without a link.** Unsourced statistics are how a good pitch dies to one follow-up question.

## Files

| File | What it holds |
|---|---|
| `incidents.md` | Fire, Burglary, Faint. Annual figures, what actually kills people, and the synthesis for each. |
| `agent-briefs.md` | One domain brief per agent: thresholds it acts on, what it must not claim. |
| `footage.md` | B-roll sourcing for the video, with the licensing rules. |
| `identity.md` | **How we tag people, and why not from the body.** Roster plus device association is what ships; boundary binding is roadmap. Read before writing anything that sounds like person identification. |

## The three findings that matter most

If you read nothing else here:

1. **The long lie.** Half of older adults who lie on the floor more than an hour after a fall die within six months, even where the fall caused no injury. 53% are still on the floor when the ambulance arrives. **The fall is not what kills; the time to discovery is.** That is a clinical outcome Hawk Eye directly moves, and it is the strongest claim the project has.

2. **Unconscious before aware.** Toxic gases in a house fire can render someone unconscious in under a minute, often before they know there is a fire, in a modern room that becomes unsurvivable in under three. This is why a crew needs to be told who is still inside and where, rather than asking at the door.

3. **28% of older adults live alone.** 42% of women over 75. There is nobody else in the house to press it for them either.

Together these say the same thing: **by the time anyone calls, the information that decides the outcome is already unavailable to them.**

Note that Hawk Eye does not call 911 itself; that was settled 2026-09-19 and the framing above reflects it.
These figures argue for the *information*, not for autonomy. Do not let the pitch drift back into implying the system dials on its own.

## How this feeds the rest of the repo

- `docs/CLAUDE.md` owns the pitch and the Devpost writeup; both draw from `incidents.md`.
- `agents/CLAUDE.md` owns architecture; `agent-briefs.md` is the domain layer underneath it.
- `media/CLAUDE.md` owns the video; `footage.md` is its sourcing rules.

## The assigned security research

The three research items the track owner asked for directly are **not** in this folder. They are deliverables in `docs/`, not background:

- `docs/fraud-13.md` - the 13 attacks at fraud.webmesh.ai
- `docs/geo.md` - Generative Engine Optimization
- `docs/threat-landscape.md` - current agent attacks, OSI, OWASP, MAESTRO

All three were written 2026-09-19. See `docs/CLAUDE.md`.

One open item remains inside them: the `fraud.webmesh.ai` battery has not actually been run against `agents/caller`, because the deployment is still broken.
The results column in `docs/fraud-13.md` is deliberately empty rather than guessed, and it fills in Saturday.
