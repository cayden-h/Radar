# Removing Faint, keeping responsiveness

Date: 2026-09-19
Status: approved, not yet implemented

## Why

Faint was one of the three incident types and carried the project's headline statistics: the long lie, 53% still on the floor when the ambulance arrives, half of those down over an hour dead within six months.
Those statistics are about falls.
The capability that actually matters to a dispatcher is narrower and more defensible: **whether the people inside can respond.**

A 1x1 radio resolves a respiration signature.
It does not resolve consciousness, and the fall-detection path was the weakest link in the chain - a debounce problem dressed as a clinical variable.
Cutting it removes the part of the system most likely to be wrong on stage, and promotes the part that was already load-bearing.

The new framing: **during an incident, dispatch learns where each person is and whether to expect a response from them.**

## Decisions

1. **The incident roster becomes Burglary and Fire.** `IncidentType.FAINT` is removed.
2. **Fall detection is cut entirely.** `people/collapse.py`, `people.collapse_detected`, `people.still_down_s`, and `Presence.still_down_s` all go.
3. **Respiration stays and is promoted.** It already carries the personhood verdict; it now also carries the responsiveness answer.
4. **`people.respiration_lost` becomes the primary responsiveness signal.** It already exists and already has the right shape - seconds since a signature was last resolvable on a presence that previously had one.
5. **The system never says "unresponsive."** It says what it measured.

## The responsiveness signal

`respiration.py` already holds the line: *absence of a respiration signature is not absence of a person.*
Shallow breathing, breath-holding and range limits all degrade toward invisible.
A presence that never had a signature is therefore weak evidence of nothing in particular.

The defensible signal is the **transition** - a presence that had a breathing signature and lost it.
That is what `people.respiration_lost` already asserts, with `value` as the elapsed seconds, `confidence` 0.5 and a `severity_ceiling` of ACTIONABLE.

Two changes to it:

- Its `basis` string currently ends "Cross-check the collapse state before concluding anything."
  The collapse reader is going away, so that sentence is rewritten to stand on its own.
- It stops being a secondary escalation and becomes a field `classify` and `caller` both read.

No new sensing code. This is a promotion, not an addition.

### Wording at the human boundary

The operator hears the measurement and its limit, never a conclusion:

> "Three people inside. Two breathing, in the kitchen. One in the back bedroom - we had a breathing signature there four minutes ago and we do not have one now. Do not expect them to answer the door."

The final clause is the deliverable. Everything before it is what licenses it.

## Classification

`agents/master/classify.py`. Burglary is untouched.

| Observation | Classification |
|---|---|
| Elevated CO + a presence that lost its respiration signature | Fire, with an occupant in that room who may not be able to respond |
| Elevated CO, every presence still breathing | Fire, everyone on their feet, this is the moment to leave |
| Unexpected presence + residents home | Burglary with occupants home |
| Unexpected presence + house registered empty | Burglary, no occupants at risk |

The first row preserves the two-independent-modalities beat that makes this function worth showing a judge - CSI respiration and a separate gas sensor - without fall detection.

The function currently falls through to a placeholder `FAINT` verdict at confidence 0.0 when nothing corroborates and nothing was raised.
That becomes an explicit no-classification result rather than a defaulted incident type, so no caller can mistake the placeholder for a verdict.

## Scope

116 references across 33 files.

**Agents.** Delete `people/collapse.py`; drop its wiring from `people/agent.py`. Rewrite the fall branch and the fallback in `master/classify.py`, the CO reasoning in `master/agent.py`, and the Faint guidance in `caller/guidance.py`. In `caller/agent.py`, the `collapse_detected` and `still_down_s` question-routing entries and their answer cases are replaced by `respiration_lost`. Remove the collapse capability text from `core/identity.py`.

**Backend.** `IncidentType` in `models/incident.py`; `Presence.still_down_s` in `models/state.py`; the Faint paths in `api.py` and `master/simulated.py`; the Faint tap in `scripts/demo.sh`. `master/scenario.py` carries only a historical comment about the collapse agent merge and needs no change. Regenerate every file under `app/backend/schema/` from `tools/gen_schema.py` rather than editing them by hand.

**iOS.** `IncidentType` in `Models/Incident.swift` loses `.faint` along with its label, icon and palette entry; `Palette.faint` goes - it is the same hex as `Palette.personUnresponsive`, which stays. `Config.mockFaintDebounce` goes. `MockHawkEyeClient` loses the faint script and reworks the two remaining ones so the respiration-lost transition is what the mock demonstrates. `InteriorView` marks a presence that has lost its signature distinctly - `Palette.personUnresponsive` already exists. `HomeView` shows two tiles.

**Cards.** `people`'s capability set shrinks, so its agent card changes. Rebuild with `python scripts/build_cards.py`; `--check` fails until that is done.

**Docs.** `CLAUDE.md` at the repo root, `agents/CLAUDE.md`, `app/CLAUDE.md`, `docs/CLAUDE.md`, `docs/research/*`, `docs/architecture-diagrams.md` and `docs/swapping-in-real-parts.md` all carry the three-incident roster or the long-lie framing. The headline story is rewritten around responsiveness.

## Testing

The suites that cover this are `agents/tests/test_people.py`, `test_trust.py`, `test_caller.py`, `test_wire.py` and `app/backend/tests/`.

- `test_people.py` loses its collapse cases and gains cases on the respiration-lost transition: a presence that never had a signature must not produce the claim; one that had a signature and lost it must, with the elapsed seconds correct.
- `test_trust.py::test_a_fall_with_elevated_co_is_a_fire_not_a_faint` becomes the CO-plus-lost-respiration case.
- `test_caller.py` opening-report assertions move from Faint to Fire and must assert the capability-bounded wording, not a conclusion.
- The verification suite in `app/backend/tests/` should be unaffected; if a schema fixture references `faint` or `still_down_s`, it regenerates.

Acceptance: `cd agents && python -m pytest -q`, `cd app/backend && python -m pytest -q`, `python scripts/build_cards.py --check`, and `swiftc -parse -swift-version 6` clean across `app/ios`.

## Explicitly out of scope

- Any new sensing capability. Respiration already exists; nothing here measures anything new.
- The `SYSTEM` raise path and `assert_human_released`. Hawk Eye still never dials on its own, and that is untouched.
- The gas sensor's simulated status. It stays simulated and stays labeled.
