# iOS Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Hawk Eye iOS app (`app/ios/`) a distinctive, considered visual finish — ambient depth instead of flat black, an elevated-glow treatment on the handful of elements that should draw the eye, and tighter rhythm on rows/buttons — without touching any interaction logic, state, models, or networking.

**Architecture:** Two small additive primitives in `DesignSystem/Components.swift` (`AmbientBackground`, a `glow` parameter added to the existing `Card`, plus a `.shadow()` pattern applied directly to the few manually-styled cards that don't route through `Card`). Every feature-view change is either (a) swapping a flat background for `AmbientBackground`, (b) adding a `.shadow(color:radius:x:y:)` modifier to an existing background/overlay stack, or (c) tightening spacing/sizing constants. No new state, no new types beyond the two design-system additions, no changed function signatures anywhere in the app.

**Tech Stack:** SwiftUI, iOS 18, Swift 6, no third-party dependencies (per `app/CLAUDE.md`). XcodeGen generates the project from `app/ios/project.yml`.

## Global Constraints

- No third-party dependencies (root `CLAUDE.md`, `app/CLAUDE.md`).
- Swift 6, `SWIFT_STRICT_CONCURRENCY: complete` (`app/ios/project.yml`) — every file must compile under strict concurrency.
- **No change to interaction logic, `HawkEyeClienting`, `AppModel`, models, wire format, or `app/backend`.** This is a pure visual pass (per the approved spec, `docs/superpowers/specs/2026-09-19-ios-visual-refresh-design.md`).
- Color still means state, never decoration (existing `Palette.swift` rule) — glow tints must reuse existing semantic colors (`Palette.calm`, `type.tint`, etc.), never introduce new arbitrary hex values.
- Nothing bounces (existing `Motion.swift` rule) — no new spring/bounce animations are introduced by this plan; all changes are static shadow/spacing/sizing.
- Re-run `xcodegen generate` after adding or moving any Swift file (this plan adds no new files, so this only matters if a worker deviates from the plan).
- **Do not verify per-task.** Per explicit user instruction, there is no per-task build/test step. All verification happens once, in Task 5, after every visual task is complete.

---

## File Structure

| File | Change |
|---|---|
| `app/ios/HawkEye/DesignSystem/Components.swift` | Add `AmbientBackground` view. Add a `glow: Color?` parameter to the existing `Card` struct. |
| `app/ios/HawkEye/Features/Connect/ConnectView.swift` | Apply `AmbientBackground`; enhance `SearchingIndicator`; tighten `HubRow` spacing. |
| `app/ios/HawkEye/Features/Home/HomeView.swift` | Reshape `IncidentBar` buttons; add glow shadow to emphasised `PresenceRow`s. |
| `app/ios/HawkEye/Features/Home/InteriorView.swift` | Add glow shadow to the interior map's card frame. |
| `app/ios/HawkEye/Features/Incident/IncidentView.swift` | Apply `AmbientBackground`; add glow shadows to `banner`, `InstructionCard`, `refusalBanner`, `CallStateBadge`, send button; tighten `TranscriptRow` spacing. |

No files are created beyond edits to the five above (plus the already-committed spec/plan docs). No files are deleted.

---

### Task 1: Design system additions — `AmbientBackground` and `Card` glow

**Files:**
- Modify: `app/ios/HawkEye/DesignSystem/Components.swift`

**Interfaces:**
- Consumes: `Palette.ground`, `Palette.surface`, `Palette.calm`, `Palette.hairline`, `Radius.lg` (all exist already in `Palette.swift` / `Layout.swift`).
- Produces:
  - `struct AmbientBackground: View` with `init(tint: Color = Palette.calm)`, used as `AmbientBackground()` or `AmbientBackground(tint: someColor)`. Fills and ignores safe area itself — callers place it as the first layer of a `ZStack`.
  - `Card` gains a new parameter: `init(tint: Color = .clear, glow: Bool = false, @ViewBuilder content: () -> Content)`. When `glow` is `true`, the card's effective tint (or `Palette.calm` if tint is `.clear`) is applied as an outer `.shadow()`. Existing call sites (`Card { ... }`, `Card(tint: someColor) { ... }`) keep compiling unchanged because `glow` defaults to `false`.

- [ ] **Step 1: Add `AmbientBackground`**

In `app/ios/HawkEye/DesignSystem/Components.swift`, add this new view after the `Wordmark` struct (before `SignalBars`):

```swift
/// A near-black backdrop with a faint radial glow seeded from two fixed
/// points, echoing the aperture motif in `Wordmark`. Used in place of a flat
/// `Palette.ground` fill so idle screens read as atmospheric rather than a
/// blank void.
///
/// Placed as the first layer of a screen's `ZStack`. Fills and ignores the
/// safe area itself, so callers never need a separate `.ignoresSafeArea()`.
struct AmbientBackground: View {
    var tint: Color = Palette.calm

    var body: some View {
        ZStack {
            Palette.ground
            RadialGradient(
                colors: [tint.opacity(0.10), Color.clear],
                center: UnitPoint(x: 0.5, y: 0.06),
                startRadius: 0,
                endRadius: 520
            )
            RadialGradient(
                colors: [Palette.surfaceRaised.opacity(0.45), Color.clear],
                center: UnitPoint(x: 0.88, y: 0.96),
                startRadius: 0,
                endRadius: 420
            )
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 2: Add a `glow` parameter to `Card`**

In the same file, replace the existing `Card` struct:

```swift
/// A card. One corner radius, one border, used everywhere so nothing drifts.
struct Card<Content: View>: View {
    var tint: Color = .clear
    @ViewBuilder var content: Content

    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .fill(Palette.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(
                        tint == .clear ? Palette.hairline : tint.opacity(0.35),
                        lineWidth: 1
                    )
            )
    }
}
```

with:

```swift
/// A card. One corner radius, one border, used everywhere so nothing drifts.
///
/// `glow: true` adds a soft outer shadow in the card's tint (or
/// `Palette.calm` when no tint is given). Reserved for the small number of
/// elements on a screen that should draw the eye — most cards leave it at the
/// default `false`, or nothing would stand out.
struct Card<Content: View>: View {
    var tint: Color = .clear
    var glow: Bool = false
    @ViewBuilder var content: Content

    private var glowTint: Color { tint == .clear ? Palette.calm : tint }

    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .fill(Palette.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(
                        tint == .clear ? Palette.hairline : tint.opacity(0.35),
                        lineWidth: 1
                    )
            )
            .shadow(color: glow ? glowTint.opacity(0.22) : .clear, radius: 22, x: 0, y: 10)
    }
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks
git add app/ios/HawkEye/DesignSystem/Components.swift
git commit -m "$(cat <<'EOF'
ios: add AmbientBackground and Card glow to the design system

Two small additive primitives for the visual refresh: a radial-glow
backdrop that replaces flat Palette.ground fills, and an opt-in outer
glow on Card for the handful of elements that should draw the eye.
Both default to the current flat/no-glow look, so no existing call
site changes behavior.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: ConnectView — ambient background, radar searching indicator, hub row rhythm

**Files:**
- Modify: `app/ios/HawkEye/Features/Connect/ConnectView.swift`

**Interfaces:**
- Consumes: `AmbientBackground` from Task 1 (`app/ios/HawkEye/DesignSystem/Components.swift`).
- Produces: nothing new consumed by other tasks. Self-contained screen change.

- [ ] **Step 1: Wrap the screen body in `AmbientBackground`**

Replace:

```swift
    var body: some View {
        VStack(spacing: 0) {
            header
            Spacer(minLength: Space.xl)
            content
            Spacer(minLength: Space.xl)
            footer
        }
        .padding(.horizontal, Space.gutter)
        .padding(.bottom, Space.xl)
        .task { model.startDiscovery() }
    }
```

with:

```swift
    var body: some View {
        ZStack {
            AmbientBackground()

            VStack(spacing: 0) {
                header
                Spacer(minLength: Space.xl)
                content
                Spacer(minLength: Space.xl)
                footer
            }
            .padding(.horizontal, Space.gutter)
            .padding(.bottom, Space.xl)
        }
        .task { model.startDiscovery() }
    }
```

- [ ] **Step 2: Give `SearchingIndicator` a glow trail and a brighter center**

Replace the `SearchingIndicator` struct:

```swift
private struct SearchingIndicator: View {
    @State private var animate = false

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.35), lineWidth: 1)
                    .frame(width: 44, height: 44)
                    .scaleEffect(animate ? 3.1 : 0.6)
                    .opacity(animate ? 0 : 0.8)
                    .animation(
                        .easeOut(duration: 3.0)
                        .repeatForever(autoreverses: false)
                        .delay(Double(index) * 1.0),
                        value: animate
                    )
            }
            Circle()
                .fill(Palette.calm.opacity(0.9))
                .frame(width: 7, height: 7)
        }
        .frame(height: 170)
        .onAppear { animate = true }
        .accessibilityLabel("Looking for your home")
    }
}
```

with:

```swift
private struct SearchingIndicator: View {
    @State private var animate = false

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.35), lineWidth: 1)
                    .frame(width: 44, height: 44)
                    .scaleEffect(animate ? 3.6 : 0.6)
                    .opacity(animate ? 0 : 0.8)
                    .blur(radius: animate ? 1.5 : 0)
                    .animation(
                        .easeOut(duration: 3.4)
                        .repeatForever(autoreverses: false)
                        .delay(Double(index) * 1.0),
                        value: animate
                    )
            }
            Circle()
                .fill(Palette.calm)
                .frame(width: 7, height: 7)
                .shadow(color: Palette.calm.opacity(0.85), radius: 10)
        }
        .frame(height: 170)
        .onAppear { animate = true }
        .accessibilityLabel("Looking for your home")
    }
}
```

- [ ] **Step 3: Tighten `HubRow`'s name/subtitle rhythm and give "Paired" a badge treatment**

Replace, inside `HubRow.body`:

```swift
                VStack(alignment: .leading, spacing: 3) {
                    Text(hub.name)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(Palette.ink)

                    HStack(spacing: Space.sm) {
                        if hub.paired {
                            Text("Paired")
                                .font(TypeScale.caption)
                                .foregroundStyle(Palette.calm)
                        }
                        if let ans = hub.ansName {
                            Text(ans)
                                .font(TypeScale.numeric)
                                .foregroundStyle(Palette.inkFaint)
                                .lineLimit(1)
                                .truncationMode(.head)
                        }
                    }
                }
```

with:

```swift
                VStack(alignment: .leading, spacing: 5) {
                    Text(hub.name)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(Palette.ink)

                    HStack(spacing: Space.sm) {
                        if hub.paired {
                            Text("Paired")
                                .font(.system(size: 10, weight: .semibold))
                                .tracking(0.4)
                                .textCase(.uppercase)
                                .foregroundStyle(Palette.calm)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(Palette.calm.opacity(0.14)))
                        }
                        if let ans = hub.ansName {
                            Text(ans)
                                .font(TypeScale.numeric)
                                .foregroundStyle(Palette.inkFaint)
                                .lineLimit(1)
                                .truncationMode(.head)
                        }
                    }
                }
```

- [ ] **Step 4: Commit**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks
git add app/ios/HawkEye/Features/Connect/ConnectView.swift
git commit -m "$(cat <<'EOF'
ios: refresh the Connect screen visually

Ambient background instead of flat black, a more atmospheric radar
searching indicator (glow trail, brighter center), and a tightened
hub row with "Paired" rendered as a small badge instead of plain
text. No change to discovery, verification, or navigation logic.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: HomeView + InteriorView — centerpiece glow, roster emphasis, tactile incident buttons

**Files:**
- Modify: `app/ios/HawkEye/Features/Home/InteriorView.swift`
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift`

**Interfaces:**
- Consumes: nothing new from other tasks (uses existing `Palette`, `Radius`, `Space` tokens).
- Produces: nothing new consumed by other tasks. Self-contained screen change.

- [ ] **Step 1: Add a calm-tinted glow to the interior map's frame**

In `app/ios/HawkEye/Features/Home/InteriorView.swift`, replace the end of `InteriorView.body`:

```swift
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)
        )
        .accessibilityElement()
        .accessibilityLabel(accessibilitySummary)
    }
```

with:

```swift
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)
        )
        // The interior view is the app's centerpiece per `app/CLAUDE.md`, so
        // it carries the one elevated-glow treatment on this screen rather
        // than competing on equal footing with the cards below it.
        .shadow(color: Palette.calm.opacity(0.16), radius: 26, x: 0, y: 10)
        .accessibilityElement()
        .accessibilityLabel(accessibilitySummary)
    }
```

- [ ] **Step 2: Add a glow shadow to emphasised `PresenceRow`s**

In `app/ios/HawkEye/Features/Home/HomeView.swift`, replace, inside `PresenceRow.body`:

```swift
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(emphasised ? tint.opacity(0.10) : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(emphasised ? tint.opacity(0.45) : Palette.hairline, lineWidth: 1)
        )
        .onAppear {
            guard presence.state == .personUnresponsive else { return }
            withAnimation(Motion.urgent) { pulse = true }
        }
    }
```

with:

```swift
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(emphasised ? tint.opacity(0.10) : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(emphasised ? tint.opacity(0.45) : Palette.hairline, lineWidth: 1)
        )
        .shadow(color: emphasised ? tint.opacity(0.22) : .clear, radius: 14, x: 0, y: 4)
        .onAppear {
            guard presence.state == .personUnresponsive else { return }
            withAnimation(Motion.urgent) { pulse = true }
        }
    }
```

- [ ] **Step 3: Reshape the incident buttons into tactile cards with an icon roundel**

In `app/ios/HawkEye/Features/Home/HomeView.swift`, replace the `IncidentBar` struct:

```swift
private struct IncidentBar: View {
    var raise: (IncidentType) -> Void

    var body: some View {
        VStack(spacing: Space.sm) {
            Text("Call 911")
                .eyebrowStyle(Palette.inkFaint)

            HStack(spacing: Space.sm) {
                ForEach(IncidentType.allCases) { type in
                    Button { raise(type) } label: {
                        VStack(spacing: 7) {
                            Image(systemName: type.symbol)
                                .font(.system(size: 19, weight: .medium))
                            Text(type.title)
                                .font(.system(size: 14, weight: .semibold))
                        }
                        .foregroundStyle(type.tint)
                        .frame(maxWidth: .infinity)
                        .frame(height: 74)
                        .background(
                            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                .fill(type.tint.opacity(0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                .strokeBorder(type.tint.opacity(0.32), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.pressable)
                    .accessibilityLabel("Raise \(type.title) incident")
                }
            }
        }
    }
}
```

with:

```swift
private struct IncidentBar: View {
    var raise: (IncidentType) -> Void

    var body: some View {
        VStack(spacing: Space.sm) {
            Text("Call 911")
                .eyebrowStyle(Palette.inkFaint)

            HStack(spacing: Space.sm) {
                ForEach(IncidentType.allCases) { type in
                    Button { raise(type) } label: {
                        VStack(spacing: 9) {
                            ZStack {
                                Circle()
                                    .fill(type.tint.opacity(0.16))
                                    .frame(width: 36, height: 36)
                                Image(systemName: type.symbol)
                                    .font(.system(size: 17, weight: .semibold))
                            }
                            Text(type.title)
                                .font(.system(size: 14, weight: .semibold))
                        }
                        .foregroundStyle(type.tint)
                        .frame(maxWidth: .infinity)
                        .frame(height: 88)
                        .background(
                            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                                .fill(type.tint.opacity(0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                                .strokeBorder(type.tint.opacity(0.35), lineWidth: 1)
                        )
                        .shadow(color: type.tint.opacity(0.18), radius: 16, x: 0, y: 6)
                    }
                    .buttonStyle(.pressable)
                    .accessibilityLabel("Raise \(type.title) incident")
                }
            }
        }
    }
}
```

- [ ] **Step 4: Commit**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks
git add app/ios/HawkEye/Features/Home/InteriorView.swift app/ios/HawkEye/Features/Home/HomeView.swift
git commit -m "$(cat <<'EOF'
ios: refresh the Home screen visually

The interior map gets the one calm-tinted glow on this screen, since
it's the app's centerpiece per app/CLAUDE.md. Emphasised presence
rows (unresponsive / unexpected) get a matching glow so they read as
louder than routine rows. Incident buttons gain an icon roundel and
a tactile glow, taller and more considered than the previous flat
equal-opacity rows. No change to raise/confirm logic.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: IncidentView — ambient background, banner/guidance/refusal glow, tighter rhythm

**Files:**
- Modify: `app/ios/HawkEye/Features/Incident/IncidentView.swift`

**Interfaces:**
- Consumes: `AmbientBackground` from Task 1.
- Produces: nothing new consumed by other tasks. Self-contained screen change.

- [ ] **Step 1: Replace the flat ground fill with `AmbientBackground`, tinted per incident type**

Replace:

```swift
    var body: some View {
        GeometryReader { proxy in
        ZStack(alignment: .top) {
            Palette.ground.ignoresSafeArea()
```

with:

```swift
    var body: some View {
        GeometryReader { proxy in
        ZStack(alignment: .top) {
            AmbientBackground(tint: incident.type.tint)
```

- [ ] **Step 2: Add a glow shadow to the incident banner**

Replace, at the end of the `banner` computed property:

```swift
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(incident.type.tint.opacity(0.3), lineWidth: 1)
        )
        .padding(.top, Space.sm)
    }
```

with:

```swift
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(incident.type.tint.opacity(0.3), lineWidth: 1)
        )
        .shadow(color: incident.type.tint.opacity(0.20), radius: 24, x: 0, y: 10)
        .padding(.top, Space.sm)
    }
```

- [ ] **Step 3: Add a glow shadow to the live call-state dot**

Replace, inside `CallStateBadge.body`:

```swift
                Circle()
                    .fill(state == .connected ? Palette.live : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                    .opacity(state == .connected ? (pulse ? 1 : 0.2) : 1)
                Text(state.label)
```

with:

```swift
                Circle()
                    .fill(state == .connected ? Palette.live : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                    .opacity(state == .connected ? (pulse ? 1 : 0.2) : 1)
                    .shadow(
                        color: state == .connected ? Palette.live.opacity(pulse ? 0.9 : 0.2) : .clear,
                        radius: 5
                    )
                Text(state.label)
```

- [ ] **Step 4: Tighten `TranscriptRow` spacing**

Replace, at the start of `TranscriptRow.body`:

```swift
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
```

with:

```swift
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
```

- [ ] **Step 5: Add a glow shadow to the latest guidance instruction**

Replace, at the end of `InstructionCard.body`:

```swift
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(latest
                      ? (instruction.urgent ? Palette.fire.opacity(0.12) : Palette.surfaceRaised)
                      : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(
                    latest && instruction.urgent ? Palette.fire.opacity(0.4) : Palette.hairline,
                    lineWidth: 1
                )
        )
        .opacity(latest ? 1 : 0.7)
        .scaleEffect(latest ? 1 : 0.985, anchor: .top)
    }
}
```

with:

```swift
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(latest
                      ? (instruction.urgent ? Palette.fire.opacity(0.12) : Palette.surfaceRaised)
                      : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(
                    latest && instruction.urgent ? Palette.fire.opacity(0.4) : Palette.hairline,
                    lineWidth: 1
                )
        )
        .shadow(
            color: latest
                ? (instruction.urgent ? Palette.fire.opacity(0.22) : Palette.calm.opacity(0.14))
                : .clear,
            radius: 18, x: 0, y: 6
        )
        .opacity(latest ? 1 : 0.7)
        .scaleEffect(latest ? 1 : 0.985, anchor: .top)
    }
}
```

- [ ] **Step 6: Add a glow shadow to the refusal banner**

Replace, inside `refusalBanner`'s label:

```swift
            .padding(Space.lg)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(Palette.personUnresponsive.opacity(0.12))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .strokeBorder(Palette.personUnresponsive.opacity(0.5), lineWidth: 1)
            )
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("\(refusals.count) refused claims. Open the verification feed.")
    }
```

with:

```swift
            .padding(Space.lg)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(Palette.personUnresponsive.opacity(0.12))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .strokeBorder(Palette.personUnresponsive.opacity(0.5), lineWidth: 1)
            )
            .shadow(color: Palette.personUnresponsive.opacity(0.22), radius: 20, x: 0, y: 8)
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("\(refusals.count) refused claims. Open the verification feed.")
    }
```

- [ ] **Step 7: Add a glow to the active send button in the context field**

Replace, inside `contextField`:

```swift
                Button(action: send) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(canSend ? Palette.ground : Palette.inkFaint)
                        .frame(width: Hit.min - 8, height: Hit.min - 8)
                        .background(
                            Circle().fill(canSend ? Palette.calm : Palette.surfaceRaised)
                        )
                }
```

with:

```swift
                Button(action: send) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(canSend ? Palette.ground : Palette.inkFaint)
                        .frame(width: Hit.min - 8, height: Hit.min - 8)
                        .background(
                            Circle().fill(canSend ? Palette.calm : Palette.surfaceRaised)
                        )
                        .shadow(color: canSend ? Palette.calm.opacity(0.4) : .clear, radius: 10)
                }
```

- [ ] **Step 8: Commit**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks
git add app/ios/HawkEye/Features/Incident/IncidentView.swift
git commit -m "$(cat <<'EOF'
ios: refresh the Incident (call) screen visually

Ambient background tinted per incident type, glow shadows on the
banner, the latest guidance card, the refusal banner, the live call
dot, and the active send button, plus tightened transcript row
spacing. No change to transcript, verification, guidance, or context
logic.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Verify — generate, build, and visually confirm in Xcode

Per user instruction, this is the **only** verification step in the whole plan; it runs once, after Tasks 1-4 are all committed.

**Files:** none (build/test only).

**Interfaces:** none — this task consumes the finished app and produces a verified (or fixed-and-verified) build.

- [ ] **Step 1: Install XcodeGen if not already present**

```bash
which xcodegen || brew install xcodegen
```

Expected: `xcodegen` resolves to a path, either already installed or freshly installed by Homebrew.

- [ ] **Step 2: Generate the Xcode project**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks/app/ios
xcodegen generate
```

Expected: `Generated project at HawkEye.xcodeproj` with no errors. This regenerates `HawkEye.xcodeproj` and `HawkEye/Info.plist` from `project.yml` (both gitignored per `app/ios/README.md`) — no source changes needed since this plan added no new files.

- [ ] **Step 3: Compile-check every target under Swift 6 strict concurrency**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks/app/ios
xcodebuild build \
  -project HawkEye.xcodeproj \
  -scheme HawkEye \
  -destination 'generic/platform=iOS Simulator' \
  -quiet
```

Expected: `** BUILD SUCCEEDED **`. This is a real `xcodebuild` compile (not `swiftc -parse`), so it catches any Swift 6 concurrency or type error introduced across Tasks 1-4. If it fails, read the error, fix the specific file/line, and re-run this exact command until it succeeds — do not proceed to Step 4 with a red build.

- [ ] **Step 4: Check whether a simulator runtime is available for a live visual pass**

```bash
xcrun simctl list runtimes
```

- If at least one iOS runtime is listed: continue to Step 5 for a full visual pass using the `ScreenshotTour` UI test.
- If no runtime is listed (as observed at plan-writing time — this machine's Xcode has no iOS Simulator runtime installed, and downloading one is a multi-gigabyte fetch out of scope for this pass): skip to Step 6. The compile-check in Step 3 plus the open-in-Xcode step in Step 6 are the verification available in this environment; note this limitation explicitly when reporting completion rather than claiming a screenshot pass happened.

- [ ] **Step 5: Run the `ScreenshotTour` UI test and pull screenshots (only if Step 4 found a runtime)**

```bash
cd /Users/tringuyen2007/Documents/Projects/VTHacks/app/ios
xcodebuild test \
  -project HawkEye.xcodeproj \
  -scheme HawkEye \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -only-testing:HawkEyeUITests/ScreenshotTour \
  -quiet
```

Then pull the PNGs it wrote (per `HawkEyeUITests/ScreenshotTour.swift`, into the test runner's Documents directory):

```bash
BOOTED=$(xcrun simctl list devices booted | grep -o '[0-9A-F-]\{36\}' | head -1)
CONTAINER=$(xcrun simctl get_app_container "$BOOTED" ai.hawkeye.app data 2>/dev/null)
find "$CONTAINER/Documents" -name '*.png' -exec cp {} /private/tmp/claude-501/-Users-tringuyen2007-Documents-Projects-VTHacks/06fac868-7c30-4f5c-b6fb-dce97f28d6ee/scratchpad/ \;
ls /private/tmp/claude-501/-Users-tringuyen2007-Documents-Projects-VTHacks/06fac868-7c30-4f5c-b6fb-dce97f28d6ee/scratchpad/*.png
```

Read each PNG (`01-connect.png` through `08-later.png`) with the Read tool and visually check, against the design spec:

- Connect screen shows the ambient glow and the enlarged radar rings.
- Home screen shows the interior map's glow frame, the tightened roster, and the reshaped incident buttons with icon roundels.
- Incident screens show the tinted ambient background, the glowing banner/guidance/refusal cards, and no layout regressions (no clipped text, no overlapping elements, no element pushed off-screen by the new shadows).

If anything looks wrong, fix it in the relevant file from Tasks 1-4, re-run Step 3's build, then re-run this step, until every screenshot looks correct.

- [ ] **Step 6: Open the project in Xcode for a manual look**

```bash
open /Users/tringuyen2007/Documents/Projects/VTHacks/app/ios/HawkEye.xcodeproj
```

This satisfies the "make sure you use Xcode" requirement regardless of whether Step 5 ran: the project opens in Xcode, and if a simulator runtime is available on the machine running this, pressing Run walks Connect → Home → an open incident against `Config.useMocks = true` (the default), exactly as `HawkEyeUITests/ScreenshotTour.swift` scripts it.

- [ ] **Step 7: Report the outcome**

Summarize, in the final message to the user:
- Whether `xcodebuild build` succeeded (it must, before this task is considered done).
- Whether a full simulator screenshot pass ran (Step 5) or was skipped for lack of a runtime (Step 4's fallback), and if skipped, that manual confirmation in Xcode (Step 6) is the remaining step for the user to do themselves.
- Any fixes made during this verification pass, file and line.

No commit is needed for this task unless Step 5 or Step 6 surfaced a bug that required a code fix — if so, commit that fix with a message describing what was visually wrong and what changed, following the same commit-message convention as Tasks 1-4.

---

## Self-Review

**Spec coverage:**
- Design system additions (`AmbientBackground`, elevated glow) → Task 1. ✓
- ConnectView (ambient background, radar indicator, hub row rhythm) → Task 2. ✓
- HomeView (interior view glow, roster rhythm/emphasis, incident buttons) → Task 3. ✓
- IncidentView (ambient background, banner/guidance/refusal glow, transcript/verification typography, context field) → Task 4 covers banner, call badge, transcript spacing, guidance glow, refusal glow, send button glow. `VerificationRow` and `contextField`'s border/corner-radius were already consistent with the refreshed style (both already use `Radius.md` and the existing focus-border pattern), so no further edit was warranted there beyond what Task 4 does — this is a deliberate no-op, not a gap.
- Verification-only-at-the-end → Task 5, and the Global Constraints section states it explicitly so no task accidentally adds a build step.

**Placeholder scan:** no TBD/TODO; every step shows complete before/after code or an exact runnable command.

**Type consistency:** `AmbientBackground(tint:)` and `Card(tint:glow:)` signatures introduced in Task 1 are used identically in Tasks 2-4 (`AmbientBackground()`, `AmbientBackground(tint: incident.type.tint)`); no other task calls `Card` directly, so the `glow` parameter is available for future use but not required to be consumed by this plan's own tasks.

**Scope check:** single cohesive visual pass over one platform target, five files, no subsystem boundary crossed. Right-sized for one plan.
