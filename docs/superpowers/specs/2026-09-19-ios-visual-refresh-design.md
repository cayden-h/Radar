# iOS visual refresh — design spec

Branch: `UXUI`. Scope: `app/ios/` only. Pure visual/design pass — no new interaction logic, no backend wiring, no change to wire format, state machine, or existing tap/confirm behavior.

## Why

`app/CLAUDE.md` names the interior view as the strongest Best-UI/UX-Hack candidate on the team, and the app is the one surface a judge will actually hold. The existing `DesignSystem/` (Palette, Typography, Motion, Components) already encodes real emergency-UX discipline — dark-first because a bright screen is a safety leak during a burglary, color-means-state-never-decoration, no bouncy motion because it reads as playful on a screen reporting an unresponsive person, confidence-as-coherence instead of a floating percentage. That discipline is correct and stays untouched. What's missing is polish: the screens are functionally complete but visually generic in places (flat rows, plain black voids, default SwiftUI system feel) rather than distinctive and reassuring.

## Research basis

- **Dark-first, not dark-available.** Already correct; extend, don't fight.
- **Calm by default, loud only at the moment of truth.** The alarm state (unresponsive person) must stay the one unmistakably different thing on screen. Any new visual richness must not compete with it.
- **Glanceability over density.** Bigger hit targets, shorter labels, whitespace, order-by-what-to-do-first. Someone scared reads in fragments.
- **Consistency removes cognitive load.** One corner-radius scale, one motion rhythm, one icon language (SF Symbols) everywhere — no per-screen one-offs.
- **Warmth without weakness.** Reassuring, not cute. No gamified motion, no mascots, no bounce.
- **Distinctiveness from restraint.** The aperture/radar motif already exists (Wordmark, Connect screen's searching rings). Carry it as the one signature visual idea rather than adding new ornament.

## What is explicitly out of scope

- The `.confirmationDialog` on raising an incident stays as-is (no hold-to-confirm mechanic).
- No TAKE OVER control, no audio mode switches, no silent-mode side effects.
- No text-driven mode inference.
- No changes to `HawkEyeClienting`, `AppModel`, models, or any networking code.
- No changes to `app/backend`.

All of the above are real gaps against `app/CLAUDE.md` but are functionality, not visual design, and are explicitly deferred by the user to a later backend-integration pass.

## Design system additions (`DesignSystem/`)

1. **Ambient ground.** Replace the flat `Palette.ground` fill used as a screen background with a subtle radial vignette (still reads as near-black, still passes contrast checks) — a very faint glow seeded from screen-center or a fixed point, echoing the aperture motif, so screens don't feel like a blank void. Implemented as a reusable `AmbientBackground` view in `Components.swift`, not per-screen ad hoc gradients.
2. **Elevated-card glow.** A second elevation treatment alongside the existing flat-hairline `Card`: for the few cards that should feel "lifted" (the interior view frame, the active guidance card, the call-state badge area), a soft outer glow in the card's tint color instead of/alongside the 1px hairline. Additive to `Card`, not a replacement — most cards keep the current flat treatment; only ones that need to draw the eye get glow.
3. **Display type moment.** The wordmark and the two screen titles (Connect's status line context, `IncidentView`'s incident title) get a slightly more considered treatment — tighter tracking, consistent weight — so branded moments read as designed rather than default-system. Still SF rounded, still six sizes, no new font import (no third-party dependencies per `app/CLAUDE.md`).

All additions live in `DesignSystem/`, are named and documented the way the existing tokens are, and are consumed by the feature views — never inlined per-screen.

## Per-screen changes

### ConnectView (Stage 1)

- `SearchingIndicator` gets a more atmospheric radar feel: the existing three expanding rings keep their timing but gain a soft glow trail and slightly larger max scale, so the "empty" searching state feels alive rather than static.
- Apply `AmbientBackground` behind the whole screen.
- Tighten `HubRow` internal spacing/hierarchy: paired badge and ANS name get clearer visual separation from the hub name.
- No change to the Bonjour-honesty footer copy or logic.

### HomeView (Stage 2, idle)

- Header: apply the display-type treatment to nothing new here (header stays minimal by design), but tidy the missed-frames/stale-baseline banner's spacing against the wordmark row.
- `InteriorView` card frame: adopt the elevated-card glow treatment (subtle, tinted toward `Palette.calm`) so the interior map reads as the centerpiece per `app/CLAUDE.md`, rather than one card among equals.
- `PresenceRoster` rows: tighten vertical rhythm, make the unexpected/unresponsive emphasis states slightly more pronounced (weight, glow) relative to normal rows, consistent with "the loudest thing on screen" requirement already in the code's comments.
- `IncidentBar` (the three incident buttons): reshape from flat equal-opacity rows into more tactile, slightly larger cards with clearer per-type iconography weight and a more pronounced pressed state, while leaving the tap→`raise(type)`→confirmationDialog flow completely unchanged.

### IncidentView (Stage 2, active call)

- Apply `AmbientBackground` in place of the flat `Palette.ground` fill (still covers the status-bar strip per the existing fix).
- `banner`: incident icon roundel and `CallStateBadge` get the elevated-card glow so the call header reads as the most important fixed element on screen.
- `guidanceStack` / `InstructionCard`: refine the latest-instruction card's visual weight (already distinguished from older ones) with the same glow language so guidance instructions feel authoritative.
- `refusalBanner`: keep it visually alarming (unchanged color logic) but align its card treatment with the new elevated style so it doesn't look like a different design system bolted on.
- `TranscriptRow` / `VerificationRow`: typography and spacing pass only — tighten label/timestamp rhythm, keep all existing logic (claim links, expand/collapse, refusal styling) untouched.
- `contextField`: visual polish only (border/focus treatment already good; align corner radii and spacing with the rest of the refreshed screen).

## Testing / verification

Per user instruction: **no verification during individual tasks.** Verification happens once, at the end, after all subagent tasks are complete:

1. `cd app/ios && xcodegen generate`
2. Open in Xcode and build for a simulator target (confirms `swiftc` correctness beyond `swiftc -parse`).
3. Run the app in Simulator with `Config.useMocks = true` (already the default) and walk both `.burglary` and `.faint` mock scenarios visually across all three screens.
4. Fix any build errors or visual regressions found, in one pass, at the end.

## Out of scope, restated

This spec produces a **frontend-only visual refresh**. Functionality, interaction patterns named in `app/CLAUDE.md` but not yet built (hold-to-confirm, TAKE OVER, audio modes, silent-mode side effects), and all backend/agent work remain untouched and are explicitly deferred.
