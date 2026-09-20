# docs/research/

**Pivot note, 2026-09-19.** The research deliverables survive; the incident data does not, in part.
Fire and Faint are both cut and their sections in `incidents.md` are history. Burglary is the one remaining incident type and its figures still stand.
See `docs/PIVOT.md`.

Verified background research. Written 2026-09-19.

Everything here was checked against a primary or near-primary source during that session, and the sources are linked inline in each file.
**Do not add a number to these files without a link.** Unsourced statistics are how a good pitch dies to one follow-up question.

## Files

| File | What it holds |
|---|---|
| `incidents.md` | Fire and Burglary. Annual figures, what actually kills people, and the synthesis for each. The cut third incident type keeps a section, marked as history, because its figures explain a decision. |
| `agent-briefs.md` | One domain brief per agent: thresholds it acts on, what it must not claim. |
| `footage.md` | B-roll sourcing for the video, with the licensing rules. |
| `identity.md` | **How we tag people, and why not from the body.** Roster plus device association is what ships; boundary binding is roadmap. Read before writing anything that sounds like person identification. |

## The three findings that matter most

If you read nothing else here:

1. **Responders arrive knowing nothing about who is inside.** Not how many people, not which rooms, not whether any of them can answer. Hawk Eye tells them: which rooms hold a presence, and how long since a breathing signature that was resolvable there stopped being resolvable. **That is a measurement and a clock, and it is never a finding that somebody has stopped breathing.**

   This replaced the long lie on 2026-09-19. Those were fall statistics, fall detection was cut, and a headline the system cannot measure is not a headline. The figures are kept in `incidents.md` under the cut incident type, because a scope cut you cannot explain is a scope cut you cannot defend.

2. **Unconscious before aware.** Toxic gases in a house fire can render someone unconscious in under a minute, often before they know there is a fire, in a modern room that becomes unsurvivable in under three. This is why a crew needs to be told who is still inside and where, rather than asking at the door.

3. **28% of older adults live alone.** 42% of women over 75. There is nobody else in the house to press it for them either.

Together these say the same thing: **by the time anyone calls, the information that decides the outcome is already unavailable to them.**
Which rooms hold someone. Whether they are breathing. How long since a signature that was there went missing.

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
