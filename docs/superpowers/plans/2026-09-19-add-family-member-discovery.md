# Add Family Member Discovery UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text "Add Family Member" placeholder with a discovery-first UI: a simulated list of devices seen on the home WiFi, which the resident names to build the "Family members" roster.

**Architecture:** Single-file SwiftUI rewrite of `AddFamilyMemberView.swift`. No new files, no changes to `HawkEyeClienting`, `MockHawkEyeClient`, or any other view. All state (`@State`) is local and in-memory, matching the current placeholder's persistence model exactly.

**Tech Stack:** SwiftUI, iOS 18, Swift 6. Existing design tokens only: `Palette`, `TypeScale`, `Space`, `Radius`, `Hit`, `.pressable` button style.

## Global Constraints

- Touch only `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift`. No other file changes (per spec scope and explicit user instruction).
- Stays front-end only: no calls into `HawkEyeClienting`/`MockHawkEyeClient`, no backend wiring. (Spec: Scope)
- `@State`, in-memory, resets when the view is dismissed and reopened — same as today. (Spec: §5 Persistence)
- Simulated device data must carry a visible `SIM` tag per row, styled like the existing `CoAlertRow` SIM tag in `HomeView.swift` (same font size 9/bold, capsule background, `Palette.inkFaint.opacity(0.3)`). (Spec: §2)
- Removing a family member is a plain tap, **not** hold-to-confirm — this action is not in the app's hold-to-confirm risk table. (Spec: §4)
- Naming a device is inline (reveal a text field on the same row), not a navigation push. (Spec: §2)
- Empty-state copy is exactly: "No phones seen on your WiFi yet. Ask them to join your home network, then come back here." (Spec: §3)
- Verification command for this repo (no Xcode installed on this machine, per root `CLAUDE.md`): `swiftc -parse -swift-version 6 app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift` must succeed with no errors related to this file (module-resolution errors for cross-file symbols like `Palette`/`Space` are expected and not a failure signal, since `-parse` doesn't resolve imports across files — see Task 1 Step 2 for the exact accepted output shape).

---

### Task 1: Rewrite AddFamilyMemberView with device discovery

**Files:**
- Modify: `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift` (full rewrite, same file)

**Interfaces:**
- Consumes: `Palette`, `TypeScale`, `Space`, `Radius`, `Hit` (existing `DesignSystem` tokens, already imported implicitly via module), `.pressable` button style — all already used by the current file and by `HomeView.swift`'s `CoAlertRow`.
- Produces: `struct AddFamilyMemberView: View` with the same public interface as today — `var onBack: () -> Void` — so `HomeView.swift:67`'s call site (`AddFamilyMemberView { showAddFamilyMember = false }`) does not change.

- [ ] **Step 1: Write the new file contents**

Replace the entire contents of `app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift` with:

```swift
import SwiftUI

/// Discovery-first screen for adding a family member to the household
/// roster.
///
/// **Front-end only.** Nothing here talks to `HawkEyeClienting` or
/// persists past this view's lifetime — both `devices` and `members` are
/// in-memory `@State` and reset the next time this screen is opened.
/// Wiring this to a real device-discovery source (or `MockHawkEyeClient`)
/// is future work; see `docs/superpowers/specs/2026-09-19-add-family-member-discovery-design.md`.
///
/// The device list below is simulated, not a real WiFi scan — hence the
/// `SIM` tag on every row, the same honesty-rule tag already used by
/// `CoAlertRow` in `HomeView.swift` for the simulated CO reading.
struct AddFamilyMemberView: View {
    var onBack: () -> Void

    private struct SimulatedDevice: Identifiable {
        var id: String
        var vendorLabel: String
        var suffix: String
        var label: String { "\(vendorLabel) · …\(suffix)" }
    }

    private struct FamilyMember: Identifiable {
        var id: String
        var name: String
        var deviceLabel: String
    }

    @State private var devices: [SimulatedDevice] = [
        SimulatedDevice(id: "d1", vendorLabel: "Apple iPhone", suffix: "4F2A"),
        SimulatedDevice(id: "d2", vendorLabel: "Apple Watch", suffix: "9C31"),
        SimulatedDevice(id: "d3", vendorLabel: "Samsung Galaxy", suffix: "7B08"),
    ]
    @State private var members: [FamilyMember] = []
    @State private var namingDeviceID: String?
    @State private var draftName: String = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                backRow

                VStack(alignment: .leading, spacing: Space.xs) {
                    Text("Family members")
                        .font(TypeScale.title)
                        .foregroundStyle(Palette.ink)
                    Text("Placeholder only. Naming a device here does not yet register it with the hub.")
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }

                deviceSection

                if !members.isEmpty {
                    memberSection
                }

                Spacer(minLength: 0)
            }
            .padding(.horizontal, Space.gutter)
            .padding(.top, Space.sm)
            .padding(.bottom, Space.lg)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.ground.ignoresSafeArea())
        .preferredColorScheme(.dark)
    }

    // MARK: Devices

    private var deviceSection: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("Devices on your network")
                .eyebrowStyle(Palette.inkFaint)

            if devices.isEmpty {
                Text("No phones seen on your WiFi yet. Ask them to join your home network, then come back here.")
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.inkMuted)
                    .padding(.vertical, Space.sm)
            } else {
                VStack(spacing: Space.sm) {
                    ForEach(devices) { device in
                        deviceRow(device)
                    }
                }
            }
        }
    }

    private func deviceRow(_ device: SimulatedDevice) -> some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            HStack(spacing: Space.sm) {
                Circle()
                    .fill(Palette.calm)
                    .frame(width: 6, height: 6)

                Text(device.label)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink)

                Text("SIM")
                    .font(.system(size: 9, weight: .bold))
                    .padding(.horizontal, 4).padding(.vertical, 1)
                    .background(Capsule().fill(Palette.inkFaint.opacity(0.3)))
                    .foregroundStyle(Palette.inkFaint)

                Spacer()

                if namingDeviceID != device.id {
                    Button("Name") {
                        namingDeviceID = device.id
                        draftName = ""
                    }
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Palette.calm)
                }
            }

            if namingDeviceID == device.id {
                HStack(spacing: Space.sm) {
                    TextField("Name", text: $draftName)
                        .font(TypeScale.body)
                        .foregroundStyle(Palette.ink)
                        .padding(.horizontal, Space.md)
                        .padding(.vertical, 11)
                        .background(
                            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                .fill(Palette.surfaceRaised)
                        )

                    Button("Save", action: { confirmName(for: device) })
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(canSave ? Palette.ground : Palette.inkFaint)
                        .padding(.horizontal, Space.lg)
                        .frame(height: Hit.min - 8)
                        .background(
                            Capsule().fill(canSave ? Palette.calm : Palette.surfaceRaised)
                        )
                        .disabled(!canSave)
                }
            }
        }
        .padding(Space.md)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.surface)
        )
    }

    private var canSave: Bool {
        !draftName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func confirmName(for device: SimulatedDevice) {
        let trimmed = draftName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        members.append(FamilyMember(id: device.id, name: trimmed, deviceLabel: device.label))
        devices.removeAll { $0.id == device.id }
        namingDeviceID = nil
        draftName = ""
    }

    // MARK: Members

    private var memberSection: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("Family members")
                .eyebrowStyle(Palette.inkFaint)

            VStack(spacing: Space.sm) {
                ForEach(members) { member in
                    memberRow(member)
                }
            }
        }
    }

    private func memberRow(_ member: FamilyMember) -> some View {
        HStack(spacing: Space.sm) {
            VStack(alignment: .leading, spacing: 2) {
                Text(member.name)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink)
                Text("Linked from \(member.deviceLabel)")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            Spacer()

            Button("Remove") { members.removeAll { $0.id == member.id } }
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.inkMuted)
        }
        .padding(.horizontal, Space.lg)
        .padding(.vertical, Space.md)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.surface)
        )
    }

    // MARK: Back

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
}
```

- [ ] **Step 2: Verify the file parses**

Run:
```bash
cd app/ios && swiftc -parse -swift-version 6 HawkEye/Features/Family/AddFamilyMemberView.swift 2>&1 | grep -v "error: no such module\|cannot find type\|cannot find '.*' in scope"
```

Expected: no output (the grep filters out the cross-file symbol-resolution
errors that `-parse` always produces for a single file outside its module —
`Palette`, `TypeScale`, `Space`, `Radius`, `Hit`, `eyebrowStyle`,
`.pressable` are all defined in sibling files under `DesignSystem/`). Any
remaining line after the filter (a real syntax error) is a failure —
fix and re-run before continuing.

- [ ] **Step 3: Confirm the call site is untouched**

Run:
```bash
grep -n "AddFamilyMemberView" app/ios/HawkEye/Features/Home/HomeView.swift
```

Expected output includes exactly:
```
67:            AddFamilyMemberView { showAddFamilyMember = false }
```
unchanged from before this task. If it differs, `HomeView.swift` was
touched — revert it; this plan's constraint is single-file.

- [ ] **Step 4: Commit**

```bash
git add app/ios/HawkEye/Features/Family/AddFamilyMemberView.swift
git commit -m "$(cat <<'EOF'
ios: rebuild Add Family Member as WiFi device discovery

Replaces free-typed names with a simulated list of devices seen on
the home WiFi that the resident names, matching the roster + device
association concept the rest of the app already reasons in.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

- **Spec coverage:** §1 (two sections) → Task 1 `deviceSection`/`memberSection`. §2 (device row: label, SIM tag, inline Name/Save) → `deviceRow`. §3 (empty state copy) → exact string in `deviceSection`. §4 (confirmed roster row, provenance line, plain-tap Remove) → `memberRow`. §5 (persistence unchanged, doc comment updated) → `@State` only, doc comment rewritten. All covered by Task 1.
- **Placeholder scan:** none — full working Swift source is included in Step 1.
- **Type consistency:** `SimulatedDevice.id: String` and `FamilyMember.id: String` are consistent throughout; `onBack: () -> Void` matches `HomeView.swift:67`'s existing call site exactly, so no other file needs to change.
