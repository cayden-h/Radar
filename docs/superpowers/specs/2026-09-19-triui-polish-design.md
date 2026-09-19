# TRIUI polish — design

2026-09-19. Branch `TRIUI`, off `main`.

## Problem

Six front-end-only fixes/additions to the iOS app (`app/ios/`), none requiring backend or agent changes:

1. The "raise incident" popup is not centered/consistent across phone sizes.
2. No way to go back from Home to the hub picker.
3. No way to end a call from `IncidentView`.
4. The "911 Operator" transcript label doesn't stand out.
5. No way to add a family member (placeholder only, no backend wiring).
6. Incident/map colors need to change: unexpected person → red, burglary → deep red, faint → purple.

## 1. Raise-incident control

Root cause of the centering bug: `HomeView` raises incidents via `.confirmationDialog`, a system action sheet. This also contradicts `app/CLAUDE.md`, which specifies **hold-to-confirm, not modal dialogs** for every risky/irreversible control (raise incident, end call, take over, turn on sound), specifically because a modal makes a panicking user find and hit a second target.

Fix: remove the `.confirmationDialog` and `pendingIncident` state from `HomeView` entirely. Add a new reusable component:

```swift
struct HoldToConfirmButton<Label: View>: View {
    var duration: TimeInterval = 1.5
    var tint: Color
    var action: () -> Void
    @ViewBuilder var label: () -> Label
}
```

Behavior:
- A `DragGesture(minimumDistance: 0)` (not a `LongPressGesture`, so progress is visible continuously) drives a `0...1` progress value via a `TimelineView` or a driven `Animation` from press-down.
- A fill overlay (bottom-up rectangle mask or radial sweep, in `tint`) animates from 0 to 1 over `duration` while pressed.
- Releasing before completion cancels: fill animates back to 0, no action fires.
- Reaching 1.0 fires `action()` once and resets.
- **No haptics, no sound** — purely visual, so it behaves correctly in silent contexts per the spec's rule that hold feedback must be visual-only.
- Accessibility: expose as a button with a hint ("Double tap and hold to confirm") since `DragGesture` alone isn't VoiceOver-accessible; add a VoiceOver-specific fallback path (`.accessibilityAction` that fires `action()` directly) so the control isn't unusable under VoiceOver.

`IncidentBar` in `HomeView.swift` wraps each of the three tiles in `HoldToConfirmButton` instead of `Button`, calling `Task { try? await client.raiseIncident(type) }` directly on completion (no intermediate confirmation state needed since the hold *is* the confirmation).

## 2. Back button (Home → Connect)

`AppModel` gains:

```swift
func disconnectAndForget() {
    client.disconnect()
    stage = .connect
}
```

`HomeView` adds a back row below `IncidentBar`: a plain (tap, not hold — this is not a risky/irreversible action) button, left-chevron + "Change hub", calling `model.disconnectAndForget()`. Not shown on `IncidentView`, which is unaffected by this change and has no back control today.

## 3. End call button

`IncidentView` adds a `HoldToConfirmButton` labeled "End call", styled as a danger action (red, `Palette.personUnresponsive`), placed above the context field, visually separated from the transcript/feed content above it.

**This is a local, front-end-only action.** The backend has no stand-down route (per `app/CLAUDE.md`: "the app has no stand-down button... an incident closes when `master` sends `resolved`"). On confirm, it simply dismisses the incident screen back to Home — no request is sent, no claim is made that the call was terminated server-side. A one-line comment marks this as a placeholder pending a real stand-down route.

## 4. "911 Operator" label

In `TranscriptRow` (`IncidentView.swift`), when `line.speaker == .operatorVoice`, the eyebrow label renders bold with a red pill background instead of the current plain `Palette.fire`-colored text:

```swift
Text(line.speaker.label)
    .font(.system(size: 11, weight: .bold))
    .foregroundStyle(Palette.ink)
    .padding(.horizontal, 6).padding(.vertical, 2)
    .background(Capsule().fill(Palette.personUnresponsive))
```

All other speakers keep their current plain `eyebrowStyle` treatment. Only the label changes — transcript text and rail color are unaffected.

## 5. Add family member (placeholder)

New file `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift`.

Entry point: a small "+" icon button in `HomeView`'s header, next to the hub-status pill. Tapping it sets `@State private var showAddFamilyMember = false` → `true`, presented via `.fullScreenCover` (consistent with how `IncidentView` is presented) or pushed if a `NavigationStack` is introduced — using `.fullScreenCover` to avoid adding navigation infrastructure the rest of the app doesn't have.

`AddFamilyMemberView` contents:
- A back button (top-left, chevron) that dismisses back to Home.
- Title "Family members", a short line explaining what this will do once wired up.
- A local, in-memory list of added names (`@State private var members: [String] = []`) and a text field + "Add" button that appends to it.
- **No `HawkEyeClienting` calls.** No persistence beyond the view's lifetime. This is explicitly a placeholder; a comment says so.

This adds a third screen to an app whose own docs say "exactly two stages... no third stage." Noted as a deliberate, explicit exception for this placeholder, not a precedent — it doesn't touch `AppModel.Stage`, it's local presentation state on `HomeView`.

## 6. Color changes (`DesignSystem/Palette.swift`)

| Constant | Before | After |
|---|---|---|
| `Palette.burglary` | `0x8B7CFF` (violet) | `0x9A1B1B` (deep red) |
| `Palette.personUnexpected` | `0x8B7CFF` (violet) | `0x9A1B1B` (same as `burglary` — preserves the existing intentional pairing) |
| `Palette.faint` | `0xFF3B4E` (red) | `0x8B7CFF` (violet, reusing the freed-up burglary value) |
| `Palette.collapse` (**new**) | — | `0x8B7CFF` (same violet as `faint` — pairs the "person down" map/roster state with the Faint button) |
| `Palette.personUnresponsive` | `0xFF3B4E` (red) | **unchanged** |

`Palette.personUnresponsive` stays red and keeps its existing meaning of "danger/refused" wherever it's used for non-collapse UI (verification refusal banners, discarded-claim styling in `IncidentView.swift`, connect-error text in `ConnectView.swift`). It is *not* repainted purple, because doing so would recolor unrelated refusal/error UI that the request didn't ask to change.

`Palette.collapse` (new, violet) replaces `Palette.personUnresponsive` only at its "person still, breathing / not responding" map/roster call sites:
- `HomeView.swift`: `PresenceRow.tint` (the `.personUnresponsive` case), the pulsing dot opacity condition stays keyed on `presence.state` (unchanged), the "down" duration text color.
- `InteriorView.swift`: the canvas draw color for the unresponsive-but-not-unexpected case.

`personUnexpected` still takes priority over the state-based tint in both files (unchanged branching), so an unexpected + unresponsive person still reads as unexpected-red, not collapse-purple — same precedence as today, just with the new hex values.

## Out of scope

- No backend/agent changes.
- No real call-ending, no real family-member persistence.
- No changes to `Config.swift`, mock scripts, or wire format.
- No take-over button (not requested).
