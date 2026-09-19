# TRIUI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the six front-end-only iOS UI fixes/additions from `docs/superpowers/specs/2026-09-19-triui-polish-design.md`: hold-to-confirm incident raising (replacing the mis-centered popup), a back button, a placeholder end-call control, a bolded/highlighted "911 Operator" transcript label, a placeholder add-family-member page, and incident/map color changes.

**Architecture:** All changes live in `app/ios/HawkEye/`. A new reusable `HoldToConfirmButton` component in `DesignSystem/Components.swift` replaces the `.confirmationDialog` in `HomeView` and backs the new "End call" control in `IncidentView`. `AppModel` gains one new method for the back button. A new `AddFamilyMemberView` is a self-contained placeholder screen. Color changes are confined to `Palette.swift` plus the handful of call sites the spec identifies.

**Tech Stack:** Swift 6, SwiftUI, iOS 18, XcodeGen (`app/ios/project.yml` → `HawkEye.xcodeproj`). No third-party dependencies, no new test target.

## Global Constraints

- No backend/agent changes. No changes to `Config.swift`, mock scripts, or the wire format.
- No haptics or sound from the hold-to-confirm control — visual feedback only (per `app/CLAUDE.md`'s silent-mode rule).
- No `HawkEyeClienting` calls added for the family-member placeholder — local `@State` only.
- The end-call control does not contact the backend (there is no stand-down route) — it is a local dismiss, clearly commented as a placeholder.
- Every touched/created `.swift` file must pass `swiftc -parse -swift-version 6` (the project's own bar, stated in the root `CLAUDE.md`) after editing, since there is no unit-test target for this app (only `HawkEyeUITests`, which requires a full Simulator launch). The final task builds the whole project and launches it in Simulator for visual review, which is the real verification for UI-only changes like these.
- Minimum tap target `Hit.min` (52pt), existing `Space`/`Radius`/`Motion`/`TypeScale`/`Palette` constants — never a raw magic number at a call site, matching existing file conventions.

---

### Task 1: Recolor the palette

**Files:**
- Modify: `app/ios/HawkEye/DesignSystem/Palette.swift`

**Interfaces:**
- Produces: `Palette.burglary` (deep red), `Palette.personUnexpected` (same deep red), `Palette.faint` (violet), `Palette.collapse` (**new**, violet, same value as `Palette.faint`). `Palette.personUnresponsive` is unchanged.

- [ ] **Step 1: Edit the color constants**

In `app/ios/HawkEye/DesignSystem/Palette.swift`, replace the `MARK: State` and `MARK: Incidents` sections:

```swift
    // MARK: State

    /// The system is healthy and watching. Used sparingly.
    static let calm = Color(hex: 0x4FD1C5)
    /// A confirmed person, moving and breathing. Nothing is wrong.
    static let personMoving = Color(hex: 0x5BA8FF)
    /// A person who is still but breathing. The loudest state in the product.
    /// Also the generic danger/refusal color used across the verification and
    /// connect-error UI. Do not repoint this at the collapse-state map color
    /// below — they are deliberately separate constants even though they used
    /// to share a value.
    static let personUnresponsive = Color(hex: 0xFF3B4E)
    /// A perturbation with no respiration signature. Not a person.
    static let unconfirmed = Color(hex: 0x6E7889)

    /// A confirmed person the system did not expect to be in the building.
    ///
    /// Deliberately the same deep red as the Burglary button: the colour the
    /// roster turns and the button the resident presses are the same fact, and
    /// pairing them means the screen does not have to explain the link.
    ///
    /// `expected` is an orthogonal axis to `PresenceState`, not a fourth state,
    /// so this tint replaces the state tint rather than adding a case to it.
    static let personUnexpected = Color(hex: 0x9A1B1B)

    /// A confirmed person who is still and breathing, on the map/roster only.
    /// Paired with `Palette.faint`: the Faint button and the "person down"
    /// map state are the same fact. Kept separate from
    /// `Palette.personUnresponsive`, which is the unrelated danger/refusal
    /// red used elsewhere in the app.
    static let collapse = Color(hex: 0x8B7CFF)

    // MARK: Incidents

    static let burglary = Color(hex: 0x9A1B1B)
    static let fire = Color(hex: 0xFF7A3D)
    static let faint = Color(hex: 0x8B7CFF)

    /// Active call state.
    static let live = Color(hex: 0xFF3B4E)
```

- [ ] **Step 2: Verify the file parses**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/DesignSystem/Palette.swift`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
cd app/ios && git add HawkEye/DesignSystem/Palette.swift
git commit -m "ios: recolor burglary/unexpected-person to deep red, faint to violet"
```

---

### Task 2: Repoint the collapse-state call sites

**Files:**
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift:186-193` (the `PresenceRow.tint` computed property), `:264` (the "down" duration text color)
- Modify: `app/ios/HawkEye/Features/Home/InteriorView.swift:212-214` (the canvas tint expression)

**Interfaces:**
- Consumes: `Palette.collapse` from Task 1.

- [ ] **Step 1: Update `PresenceRow.tint` in `HomeView.swift`**

Find:
```swift
    private var tint: Color {
        if presence.isUnexpected { return Palette.personUnexpected }
        switch presence.state {
        case .personMoving: return Palette.personMoving
        case .personUnresponsive: return Palette.personUnresponsive
        case .unconfirmed, .unresolved: return Palette.unconfirmed
        }
    }
```

Replace with:
```swift
    private var tint: Color {
        if presence.isUnexpected { return Palette.personUnexpected }
        switch presence.state {
        case .personMoving: return Palette.personMoving
        case .personUnresponsive: return Palette.collapse
        case .unconfirmed, .unresolved: return Palette.unconfirmed
        }
    }
```

- [ ] **Step 2: Update the "down" duration text color in the same file**

Find (inside `PresenceRow.body`, the `if let down = presence.stillDownS` block):
```swift
                    Text(Self.duration(down))
                        .font(.system(size: 15, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Palette.personUnresponsive)
```

Replace with:
```swift
                    Text(Self.duration(down))
                        .font(.system(size: 15, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Palette.collapse)
```

- [ ] **Step 3: Update the canvas draw tint in `InteriorView.swift`**

Find:
```swift
                let tint: Color = presence.isUnexpected
                    ? Palette.personUnexpected
                    : (unresponsive ? Palette.personUnresponsive : Palette.personMoving)
```

Replace with:
```swift
                let tint: Color = presence.isUnexpected
                    ? Palette.personUnexpected
                    : (unresponsive ? Palette.collapse : Palette.personMoving)
```

- [ ] **Step 4: Verify both files parse**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Home/HomeView.swift app/ios/HawkEye/Features/Home/InteriorView.swift`
Expected: this will report unrelated cross-file symbol errors since `swiftc -parse` doesn't resolve the whole module — that's expected and fine; there must be **no syntax errors** (no "expected expression", "expected declaration", etc.) attributable to the lines just edited. If in doubt, confirm by eye that only symbol-resolution errors are printed (they mention types/names, not punctuation).

- [ ] **Step 5: Commit**

```bash
cd app/ios && git add HawkEye/Features/Home/HomeView.swift HawkEye/Features/Home/InteriorView.swift
git commit -m "ios: point the collapse map/roster state at Palette.collapse"
```

---

### Task 3: `HoldToConfirmButton` component

**Files:**
- Modify: `app/ios/HawkEye/DesignSystem/Components.swift`

**Interfaces:**
- Produces:
```swift
struct HoldToConfirmButton<Label: View>: View {
    var duration: TimeInterval = 1.5
    var tint: Color
    var cornerRadius: CGFloat = Radius.md
    var accessibilityLabel: String
    var action: () -> Void
    @ViewBuilder var label: () -> Label
}
```
Consumers pass `label:` for the tile/button content, `tint:` for the fill color, `accessibilityLabel:` for the spoken name, and `action:` to run on a completed 1.5s hold.

- [ ] **Step 1: Add the component to `Components.swift`**

Append to the end of `app/ios/HawkEye/DesignSystem/Components.swift`:

```swift
/// A press-and-hold control for every risky or irreversible action in the
/// app: raising an incident, ending a call. Per `app/CLAUDE.md`, these use a
/// 1.5s hold with continuous visual feedback rather than a modal dialog,
/// because a modal makes a panicking user find and hit a second target, and a
/// hold gives release-to-cancel on the target they already found.
///
/// Feedback is **purely visual** — no haptics, no sound — so it behaves
/// correctly in silent mode, where a confirmation that buzzes would defeat
/// the mode it is confirming inside of.
struct HoldToConfirmButton<Label: View>: View {
    var duration: TimeInterval = 1.5
    var tint: Color
    var cornerRadius: CGFloat = Radius.md
    var accessibilityLabel: String
    var action: () -> Void
    @ViewBuilder var label: () -> Label

    @State private var progress: CGFloat = 0
    @State private var holding = false

    var body: some View {
        label()
            .overlay(alignment: .bottom) {
                GeometryReader { geo in
                    Rectangle()
                        .fill(tint.opacity(0.4))
                        .frame(height: geo.size.height * progress)
                }
                .allowsHitTesting(false)
            }
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in beginHoldIfNeeded() }
                    .onEnded { _ in cancelHold() }
            )
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(accessibilityLabel)
            .accessibilityHint("Double tap and hold for \(Int(duration)) seconds to confirm")
            .accessibilityAction {
                // VoiceOver cannot perform a timed hold gesture, so a double
                // tap fires the action immediately for that audience.
                action()
            }
    }

    private func beginHoldIfNeeded() {
        guard !holding else { return }
        holding = true
        withAnimation(.linear(duration: duration)) { progress = 1 }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            guard holding else { return }
            holding = false
            progress = 0
            action()
        }
    }

    private func cancelHold() {
        guard holding else { return }
        holding = false
        withAnimation(Motion.snappy) { progress = 0 }
    }
}
```

- [ ] **Step 2: Verify the file parses**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/DesignSystem/Components.swift`
Expected: no output, exit code 0.

- [ ] **Step 3: Commit**

```bash
cd app/ios && git add HawkEye/DesignSystem/Components.swift
git commit -m "ios: add HoldToConfirmButton for risky/irreversible controls"
```

---

### Task 4: Replace the raise-incident popup with hold-to-confirm

**Files:**
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift`

**Interfaces:**
- Consumes: `HoldToConfirmButton` from Task 3.
- Produces: `IncidentBar` no longer takes a `raise:` closure that opens a confirmation — it calls `client.raiseIncident` directly through the hold button. `HomeView.pendingIncident` and the `.confirmationDialog` modifier are removed.

- [ ] **Step 1: Remove the confirmation-dialog state and modifier**

In `HomeView.swift`, delete the `@State private var pendingIncident: IncidentType?` property, and delete the entire `.confirmationDialog(...)` modifier block (currently right after the `.fullScreenCover` modifier, from `.confirmationDialog(` through its closing `}` before `}`  that ends `body`).

- [ ] **Step 2: Simplify `IncidentBar` to hold-to-confirm and call the client directly**

Find the whole `IncidentBar` struct:
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

Replace with:
```swift
private struct IncidentBar: View {
    var client: any HawkEyeClienting

    var body: some View {
        VStack(spacing: Space.sm) {
            Text("Hold to call 911")
                .eyebrowStyle(Palette.inkFaint)

            HStack(spacing: Space.sm) {
                ForEach(IncidentType.allCases) { type in
                    HoldToConfirmButton(
                        tint: type.tint,
                        accessibilityLabel: "Hold to raise \(type.title) incident"
                    ) {
                        Task { try? await client.raiseIncident(type) }
                    } label: {
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
                }
            }
        }
    }
}
```

- [ ] **Step 3: Update the `IncidentBar` call site**

Find, inside `HomeView.body`:
```swift
            IncidentBar { type in
                pendingIncident = type
            }
```

Replace with:
```swift
            IncidentBar(client: client)
```

- [ ] **Step 4: Verify the file parses**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Home/HomeView.swift`
Expected: only symbol-resolution errors (unknown types/names), no syntax errors, same caveat as Task 2 Step 4.

- [ ] **Step 5: Commit**

```bash
cd app/ios && git add HawkEye/Features/Home/HomeView.swift
git commit -m "ios: raise incidents via hold-to-confirm, remove the confirmation dialog"
```

---

### Task 5: Back button (Home → Connect)

**Files:**
- Modify: `app/ios/HawkEye/AppModel.swift`
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift`

**Interfaces:**
- Produces: `AppModel.disconnectAndForget()` — calls `client.disconnect()`, sets `stage = .connect`, restarts discovery.

- [ ] **Step 1: Add `disconnectAndForget()` to `AppModel`**

In `app/ios/HawkEye/AppModel.swift`, add this method after `connect(to:)`:

```swift
    /// The Home screen's back control. Leaves the current hub and returns to
    /// the Connect stage, per `app/CLAUDE.md`'s two-stage model — this is a
    /// transition between the two existing stages, not a third one.
    func disconnectAndForget() {
        client.disconnect()
        stage = .connect
        startDiscovery()
    }
```

- [ ] **Step 2: Add the back row to `HomeView`**

In `HomeView.body`, find:
```swift
            PresenceRoster(state: client.interior)

            IncidentBar(client: client)
        }
```

Replace with:
```swift
            PresenceRoster(state: client.interior)

            IncidentBar(client: client)

            BackToConnectButton { model.disconnectAndForget() }
        }
```

Then add this new private view right after the `IncidentBar` struct (before `// MARK: - Roster` or after it — anywhere in the file-private section is fine, e.g. directly below `IncidentBar`):

```swift
// MARK: - Back

/// Leaves the current hub. A plain tap, not a hold: unlike raising an
/// incident, changing hubs is not something a mistaken tap can hurt anyone
/// with — worst case, discovery restarts and the resident reconnects.
private struct BackToConnectButton: View {
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 12, weight: .semibold))
                Text("Change hub")
                    .font(.system(size: 13, weight: .medium))
            }
            .foregroundStyle(Palette.inkMuted)
            .frame(height: Hit.min)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Change hub, return to hub selection")
    }
}
```

- [ ] **Step 3: Verify the file parses**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/AppModel.swift app/ios/HawkEye/Features/Home/HomeView.swift`
Expected: only symbol-resolution errors, no syntax errors.

- [ ] **Step 4: Commit**

```bash
cd app/ios && git add HawkEye/AppModel.swift HawkEye/Features/Home/HomeView.swift
git commit -m "ios: add a back button from Home to the hub picker"
```

---

### Task 6: Add-family-member placeholder page

**Files:**
- Create: `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift`
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift`

**Interfaces:**
- Produces: `struct AddFamilyMemberView: View` taking no arguments except an `onBack: () -> Void` closure.
- Consumes (in `HomeView`): presented via `.fullScreenCover(isPresented:)`, triggered by a new header button.

- [ ] **Step 1: Create the placeholder view**

Write `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift`:

```swift
import SwiftUI

/// Placeholder screen for adding a family member to the household roster.
///
/// **Front-end only.** Nothing here talks to `HawkEyeClienting` or persists
/// past this view's lifetime — `members` is in-memory `@State` and resets the
/// next time this screen is opened. Wiring this to the backend (a roster the
/// hub actually uses for device association) is future work.
struct AddFamilyMemberView: View {
    var onBack: () -> Void

    @State private var members: [String] = []
    @State private var newName: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: Space.lg) {
            backRow

            VStack(alignment: .leading, spacing: Space.xs) {
                Text("Family members")
                    .font(TypeScale.title)
                    .foregroundStyle(Palette.ink)
                Text("Placeholder only. Adding someone here does not yet register them with the hub.")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            HStack(spacing: Space.sm) {
                TextField("Name", text: $newName)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, Space.md)
                    .padding(.vertical, 11)
                    .background(
                        RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                            .fill(Palette.surfaceRaised)
                    )

                Button("Add", action: addMember)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(canAdd ? Palette.ground : Palette.inkFaint)
                    .padding(.horizontal, Space.lg)
                    .frame(height: Hit.min - 8)
                    .background(
                        Capsule().fill(canAdd ? Palette.calm : Palette.surfaceRaised)
                    )
                    .disabled(!canAdd)
            }

            if !members.isEmpty {
                VStack(alignment: .leading, spacing: Space.sm) {
                    ForEach(members, id: \.self) { name in
                        Text(name)
                            .font(TypeScale.body)
                            .foregroundStyle(Palette.ink)
                            .padding(.horizontal, Space.lg)
                            .padding(.vertical, Space.md)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                    .fill(Palette.surface)
                            )
                    }
                }
            }

            Spacer()
        }
        .padding(.horizontal, Space.gutter)
        .padding(.top, Space.sm)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Palette.ground.ignoresSafeArea())
        .preferredColorScheme(.dark)
    }

    private var backRow: some View {
        Button(action: onBack) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 14, weight: .semibold))
                Text("Home")
                    .font(.system(size: 15, weight: .medium))
            }
            .foregroundStyle(Palette.inkMuted)
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Back to Home")
    }

    private var canAdd: Bool {
        !newName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func addMember() {
        members.append(newName.trimmingCharacters(in: .whitespacesAndNewlines))
        newName = ""
    }
}
```

- [ ] **Step 2: Wire the entry point into `HomeView`**

Add a new `@State` property inside `HomeView`, alongside `pendingIncident`'s old spot (just under `@State private var pendingIncident: IncidentType?` if it still exists at this point in the plan — it was removed in Task 4, so add this near the top of `HomeView`'s body properties instead):

```swift
    @State private var showAddFamilyMember = false
```

In `HomeView.header`, find:
```swift
    private var header: some View {
        HStack(alignment: .center, spacing: Space.md) {
            Wordmark(size: 20, breathing: false)

            Spacer(minLength: Space.sm)

            HStack(spacing: 6) {
                Circle()
                    .fill(client.link == .live ? Palette.calm : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                Text(hubName)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }
        }
```

Replace with:
```swift
    private var header: some View {
        HStack(alignment: .center, spacing: Space.md) {
            Wordmark(size: 20, breathing: false)

            Spacer(minLength: Space.sm)

            HStack(spacing: 6) {
                Circle()
                    .fill(client.link == .live ? Palette.calm : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                Text(hubName)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            Button { showAddFamilyMember = true } label: {
                Image(systemName: "person.badge.plus")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Palette.inkMuted)
                    .frame(width: Hit.min - 20, height: Hit.min - 20)
            }
            .buttonStyle(.pressable)
            .accessibilityLabel("Add family member")
        }
```

Then, in `HomeView.body`, find the existing `.fullScreenCover(item: ...) { incident in ... }` modifier and add a second `.fullScreenCover(isPresented:)` modifier directly after it (order matters only in that both must be present; SwiftUI allows multiple `fullScreenCover` modifiers on one view):

```swift
        .fullScreenCover(isPresented: $showAddFamilyMember) {
            AddFamilyMemberView { showAddFamilyMember = false }
        }
```

- [ ] **Step 3: Verify both files parse**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift app/ios/HawkEye/Features/Home/HomeView.swift`
Expected: only symbol-resolution errors, no syntax errors.

- [ ] **Step 4: Commit**

```bash
cd app/ios && git add HawkEye/Features/Family/AddFamilyMemberView.swift HawkEye/Features/Home/HomeView.swift
git commit -m "ios: add placeholder Add Family Member page"
```

---

### Task 7: End call button (placeholder)

**Files:**
- Modify: `app/ios/HawkEye/Features/Home/HomeView.swift` (the `fullScreenCover(item:)` wiring)
- Modify: `app/ios/HawkEye/Features/Incident/IncidentView.swift`

**Interfaces:**
- Consumes: `HoldToConfirmButton` from Task 3.
- Produces: `IncidentView` gains a required `onEndCall: () -> Void` parameter.

- [ ] **Step 1: Give `HomeView` a way to locally dismiss an incident**

`IncidentView` is presented from `client.incident` directly, and the backend has no stand-down route, so "ending" a call here can only mean "stop showing this incident on this phone." Add local state for that.

In `HomeView`, add another `@State` property near `showAddFamilyMember`:
```swift
    @State private var locallyEndedIncidentID: String?
```

Find the existing incident cover:
```swift
        .fullScreenCover(item: Binding(
            get: { client.incident },
            set: { _ in }
        )) { incident in
            IncidentView(incident: incident)
                .environment(model)
        }
```

Replace with:
```swift
        .fullScreenCover(item: Binding(
            get: {
                guard let incident = client.incident,
                      incident.id != locallyEndedIncidentID else { return nil }
                return incident
            },
            set: { _ in }
        )) { incident in
            IncidentView(incident: incident) {
                locallyEndedIncidentID = incident.id
            }
            .environment(model)
        }
```

- [ ] **Step 2: Add `onEndCall` to `IncidentView` and the End Call control**

In `IncidentView.swift`, find:
```swift
    @State private var context: String = ""
    @State private var sending = false
    @State private var feed: Feed = .call
    @FocusState private var fieldFocused: Bool

    private var client: any HawkEyeClienting { model.client }
```

Replace with:
```swift
    var onEndCall: () -> Void

    @State private var context: String = ""
    @State private var sending = false
    @State private var feed: Feed = .call
    @FocusState private var fieldFocused: Bool

    private var client: any HawkEyeClienting { model.client }
```

Then find, inside `body`, the `VStack(spacing: 0) { ... }` that wraps the scroll view and the context field:
```swift
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        ...
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: client.transcript.count) {
                        guard feed == .call else { return }
                        withAnimation(Motion.arrive) {
                            proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                        }
                    }
                }

                contextField
                    .padding(.horizontal, Space.gutter)
                    .padding(.bottom, Space.md)
            }
```

Replace the closing part (leave the `ScrollViewReader` block exactly as-is) so it reads:
```swift
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        ...
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: client.transcript.count) {
                        guard feed == .call else { return }
                        withAnimation(Motion.arrive) {
                            proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                        }
                    }
                }

                endCallButton
                    .padding(.horizontal, Space.gutter)
                    .padding(.top, Space.sm)

                contextField
                    .padding(.horizontal, Space.gutter)
                    .padding(.bottom, Space.md)
            }
```

(i.e. insert a new `endCallButton` line between the `ScrollViewReader` block and `contextField`, leaving the scroll content itself untouched).

Add the new view, e.g. right after the `contextField` computed property's closing brace:

```swift
    // MARK: End call

    /// **Front-end only.** The backend has no stand-down route (see
    /// `app/CLAUDE.md`: "the app has no stand-down button... an incident
    /// closes when `master` sends `resolved`"), so this does not tell the
    /// backend anything — it stops showing this incident on this phone. A
    /// real hang-up needs a real stand-down route; this is a placeholder for
    /// that, not a claim that the 911 call itself was ended.
    private var endCallButton: some View {
        HoldToConfirmButton(
            tint: Palette.personUnresponsive,
            accessibilityLabel: "Hold to end call",
            action: onEndCall
        ) {
            HStack(spacing: 8) {
                Image(systemName: "phone.down.fill")
                    .font(.system(size: 14, weight: .semibold))
                Text("End call")
                    .font(.system(size: 15, weight: .semibold))
            }
            .foregroundStyle(Palette.ink)
            .frame(maxWidth: .infinity)
            .frame(height: Hit.min)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(Palette.personUnresponsive.opacity(0.18))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .strokeBorder(Palette.personUnresponsive.opacity(0.5), lineWidth: 1)
            )
        }
    }
```

- [ ] **Step 3: Verify both files parse**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Home/HomeView.swift app/ios/HawkEye/Features/Incident/IncidentView.swift`
Expected: only symbol-resolution errors, no syntax errors.

- [ ] **Step 4: Commit**

```bash
cd app/ios && git add HawkEye/Features/Home/HomeView.swift HawkEye/Features/Incident/IncidentView.swift
git commit -m "ios: add placeholder End call hold-to-confirm button"
```

---

### Task 8: Bold, highlighted "911 Operator" label

**Files:**
- Modify: `app/ios/HawkEye/Features/Incident/IncidentView.swift` (`TranscriptRow`)

**Interfaces:**
- No new interfaces; purely a rendering change inside `TranscriptRow.body`.

- [ ] **Step 1: Split the speaker label by speaker**

Find, in `TranscriptRow.body`:
```swift
            HStack(spacing: 6) {
                Text(line.speaker.label)
                    .eyebrowStyle(rail.opacity(0.9))
                Text(line.at, style: .time)
```

Replace with:
```swift
            HStack(spacing: 6) {
                speakerLabel
                Text(line.at, style: .time)
```

Add a new computed property to `TranscriptRow`, e.g. directly above `var body: some View {`:

```swift
    /// The operator's label is bold and highlighted red so the one voice the
    /// resident did not choose to be on this call stands out from the other
    /// three speakers, which keep the plain eyebrow treatment.
    @ViewBuilder
    private var speakerLabel: some View {
        if line.speaker == .operatorVoice {
            Text(line.speaker.label)
                .font(.system(size: 11, weight: .bold))
                .tracking(1.0)
                .textCase(.uppercase)
                .foregroundStyle(Palette.ink)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(Capsule().fill(Palette.personUnresponsive))
        } else {
            Text(line.speaker.label)
                .eyebrowStyle(rail.opacity(0.9))
        }
    }
```

- [ ] **Step 2: Verify the file parses**

Run: `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Incident/IncidentView.swift`
Expected: only symbol-resolution errors, no syntax errors.

- [ ] **Step 3: Commit**

```bash
cd app/ios && git add HawkEye/Features/Incident/IncidentView.swift
git commit -m "ios: bold and highlight the 911 Operator transcript label"
```

---

### Task 9: Regenerate the Xcode project, build, and launch for review

**Files:** none (build-only task)

**Interfaces:** none.

- [ ] **Step 1: Regenerate the Xcode project**

Run: `cd app/ios && xcodegen generate`
Expected: `Created project at HawkEye.xcodeproj`, exit code 0. (Picks up `Features/Family/AddFamilyMemberView.swift`, since the target globs `HawkEye/`.)

- [ ] **Step 2: Build for Simulator**

Run:
```bash
cd app/ios && xcodebuild -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```
Expected: `** BUILD SUCCEEDED **`. If it fails, fix the reported errors in the relevant task's file before proceeding — do not skip ahead.

- [ ] **Step 3: Launch in Simulator for visual review**

Boot a simulator, install, and launch the app so the six changes can be seen live (`Config.useMocks` is `true` by default, so this runs with no hardware):
```bash
xcrun simctl boot "iPhone 17 Pro" 2>/dev/null || true
open -a Simulator
cd app/ios && xcodebuild -scheme HawkEye -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath build install
xcrun simctl launch "iPhone 17 Pro" ai.hawkeye.app
```
Expected: the app launches in Simulator, showing the Connect screen and, after connecting to the mock hub, the Home screen with the new "Change hub" back row, the "+" add-family-member button, and the three hold-to-confirm incident tiles — visible for review before anything else proceeds.

- [ ] **Step 4: Stop here for review**

Do not commit further or start any other task. Report back what was built and launched, and wait for the user to review it in Simulator before continuing.
