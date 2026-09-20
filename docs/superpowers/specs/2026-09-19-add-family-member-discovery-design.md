# Add Family Member: WiFi device discovery UI

Status: approved, not yet implemented.

## Problem

`app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift` is a placeholder:
type a name, tap Add, it appears in an in-memory list that resets when the
screen closes. It doesn't reflect the mechanism the rest of the app already
assumes for telling a resident from an intruder — **roster plus device
association**. `MockHawkEyeClient.swift` and the burglary scenario already
reason in these terms ("2 registered residents... both resident phones
associated with the network"), but the UI that would populate that roster
doesn't use the concept at all.

The idea: a phone that joins the home WiFi has a network identifier. If we
can see that identifier, we can let the resident attach a name to it instead
of asking them to just type a name into a void with no link to anything the
rest of the system checks.

## Scope

**Front-end only**, same as the current placeholder. This does not wire into
`HawkEyeClienting`, `MockHawkEyeClient`, or the backend roster/device
association model described in `MockHawkEyeClient.swift`. It's a visual and
interaction redesign of `AddFamilyMemberView` using a small self-contained
simulated device list, `@State`, in-memory, resets on next open — exactly
like today. Wiring a real (or mock-client-backed) device discovery source is
explicitly out of scope and left as future work, same as it is today.

## Design

### 1. Screen structure

Two sections under the existing back row:

- **"Devices on your network"** — the discovery list, simulated.
- **"Family members"** — the confirmed roster, populated only from named
  devices (not free-typed names).

This mirrors a pattern already used elsewhere in the app: an unconfirmed
thing resolves into a confirmed thing (see the interior map's
unconfirmed-perturbation → confirmed-person states in `InteriorState.swift`).
Here it's discovered device → named family member, applied to the roster
screen instead of the floorplan.

### 2. Device row

Each discovered device shows:

- A vendor-derived label + short ID suffix, e.g. `Apple iPhone · …4F2A`.
  Derived from a small hardcoded/simulated OUI-style vendor table plus a
  short suffix of a generated ID — not implying real network introspection.
- A small connected indicator (reuse the existing dot pattern from
  `HomeView.header`'s link-status dot).
- A `SIM` tag, visually identical to the one already used in
  `CoAlertRow` (`app/ios/HawkEye/Features/Home/HomeView.swift`), because this
  is simulated data and the app's honesty rule requires that a simulated
  reading never be presentable as measured by accident. This applies here as
  much as it does to the CO sensor: no implying an actual network scan.
- A "Name" affordance. Tapping it reveals an inline text field on that same
  row (not a navigation push), consistent with the app's preference for
  single-gesture, non-modal interactions for non-risky actions.

### 3. Empty state

When the simulated device list is empty:

> "No phones seen on your WiFi yet. Ask them to join your home network, then come back here."

Plain language, no jargon — consistent with the rest of the app's copy voice
(e.g. the floor-plan footer disclaimer, the CO alert row).

### 4. Confirmed roster

Named entries move into "Family members" below the device list. Each row
shows:

- The name the resident entered.
- A muted secondary line showing the device label it was linked from (e.g.
  `Linked from Apple iPhone · …4F2A`) — a small provenance detail, the same
  idea as attributing resident-typed context vs. system observation
  elsewhere in the app (see the "what is happening" box rules in
  `app/CLAUDE.md`).
- A trailing "Remove" affordance. **Plain tap, not hold-to-confirm.**
  Removing a roster entry is not a risky or irreversible action under the
  app's own risk model (`app/CLAUDE.md`'s hold-to-confirm table covers
  raising an incident, ending a call, turning on sound, and takeover —
  nothing about roster edits). A hold here would be inconsistent friction,
  not safety.

### 5. Persistence

Unchanged from today: `@State`, in-memory only, resets the next time this
screen is opened. The view's doc comment gets updated to describe the new
device-discovery shape instead of the old free-text-list shape, keeping the
"front-end only, not wired to `HawkEyeClienting`" disclosure intact.

## Out of scope

- Any real WiFi/network device enumeration.
- Wiring into `MockHawkEyeClient` or the backend roster/device-association
  model.
- Any change to how `agents/intruder`'s expected/unexpected logic works —
  this is purely the resident-facing naming UI, not the detection pipeline.
