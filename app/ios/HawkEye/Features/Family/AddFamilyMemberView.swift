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
/// `CoAlertRow` in `HomeView.swift` for the simulated CO reading. It starts
/// empty and fills in one device at a time via `joinSimulatedDevices()`, to
/// read as devices joining the network rather than a static pre-filled list.
///
/// Reached from `RadarTabBar`'s People tab, not a modal — there is no close
/// button here on purpose; switching tabs is how you leave.
struct AddFamilyMemberView: View {
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

    /// A person with no device to bind — CSI recognises a phone on the WiFi,
    /// not a face, so someone who never joins the network can only ever be
    /// named manually here, not auto-recognised.
    private struct Guest: Identifiable {
        var id: String
        var name: String
    }

    /// The full simulated pool, revealed gradually by `joinSimulatedDevices()`
    /// rather than shown all at once — mirrors a phone actually joining the
    /// WiFi network at its own pace instead of a static pre-filled list.
    private static let simulatedPool: [SimulatedDevice] = [
        SimulatedDevice(id: "d1", vendorLabel: "Apple iPhone", suffix: "4F2A"),
        SimulatedDevice(id: "d2", vendorLabel: "Apple Watch", suffix: "9C31"),
        SimulatedDevice(id: "d3", vendorLabel: "Samsung Galaxy", suffix: "7B08"),
    ]

    @State private var devices: [SimulatedDevice] = []
    @State private var members: [FamilyMember] = []
    @State private var namingDeviceID: String?
    @State private var draftName: String = ""

    @State private var guests: [Guest] = []
    @State private var guestName: String = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                Text("Family members")
                    .font(TypeScale.title)
                    .foregroundStyle(Palette.ink)

                deviceSection

                guestSection

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
        .background(AmbientBackground())
        .preferredColorScheme(.dark)
        .task { await joinSimulatedDevices() }
    }

    /// Simulates devices joining the WiFi network one at a time rather than
    /// listing the whole pool the instant this screen opens. Front-end only:
    /// there is no real network being scanned here.
    private func joinSimulatedDevices() async {
        for device in Self.simulatedPool {
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            devices.append(device)
        }
    }

    // MARK: Devices

    private var deviceSection: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("Devices on your network")
                .eyebrowStyle(Palette.ink)

            Text(devices.isEmpty ? "No devices connected" : "\(devices.count) device\(devices.count == 1 ? "" : "s") connected")
                .font(TypeScale.caption)
                .foregroundStyle(Palette.ink)

            if devices.isEmpty {
                Text("No other device to connect")
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
        .glassPanel(cornerRadius: Radius.md)
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
        .glassPanel(cornerRadius: Radius.md)
    }

    // MARK: Guests

    /// A guest has no device to bind, so this is a manual naming path
    /// separate from the device-discovery flow above — not a lesser version
    /// of it.
    private var guestSection: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("Guests")
                .eyebrowStyle(Palette.inkFaint)

            HStack(spacing: Space.sm) {
                TextField("Name", text: $guestName)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, Space.md)
                    .padding(.vertical, 11)
                    .background(
                        RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                            .fill(Palette.surfaceRaised)
                    )

                Button("Add", action: confirmGuest)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(canSaveGuest ? Palette.ground : Palette.inkFaint)
                    .padding(.horizontal, Space.lg)
                    .frame(height: Hit.min - 8)
                    .background(
                        Capsule().fill(canSaveGuest ? Palette.calm : Palette.surfaceRaised)
                    )
                    .disabled(!canSaveGuest)
            }

            if !guests.isEmpty {
                VStack(spacing: Space.sm) {
                    ForEach(guests) { guest in
                        guestRow(guest)
                    }
                }
            }
        }
    }

    private var canSaveGuest: Bool {
        !guestName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func confirmGuest() {
        let trimmed = guestName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guests.append(Guest(id: UUID().uuidString, name: trimmed))
        guestName = ""
    }

    private func guestRow(_ guest: Guest) -> some View {
        HStack(spacing: Space.sm) {
            VStack(alignment: .leading, spacing: 2) {
                Text(guest.name)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink)
                Text("Guest — no device")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            Spacer()

            Button("Remove") { guests.removeAll { $0.id == guest.id } }
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.inkMuted)
        }
        .padding(.horizontal, Space.lg)
        .padding(.vertical, Space.md)
        .glassPanel(cornerRadius: Radius.md)
    }
}
