import SwiftUI

/// Names a visitor and, optionally, binds the device that just joined the
/// network. Permanent, unlike "This is expected" on the banner, which vouches
/// for a presence for this session only and writes nothing down.
///
/// One control does not serve both purposes. Conflating them would routinely
/// persist a stranger because someone just wanted the banner to go away, which
/// is the exact failure this sheet exists to prevent: the resident sees, in
/// words, what they are about to remember, before they remember it.
struct RememberVisitorSheet: View {
    let unclaimedDevices: [ObservedDevice]
    let onSave: (_ name: String, _ kind: HouseholdMember.Kind, _ deviceID: String?) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var kind: HouseholdMember.Kind = .guest
    @State private var deviceID: String?

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $name)
                        .textInputAutocapitalization(.words)
                }

                Section {
                    Picker("Kind", selection: $kind) {
                        ForEach(HouseholdMember.Kind.allCases, id: \.self) { kind in
                            Text(kind.label).tag(kind)
                        }
                    }
                } footer: {
                    Text("Whether they live here or are just visiting.")
                }

                Section {
                    Picker("Device", selection: $deviceID) {
                        Text("No device").tag(String?.none)
                        ForEach(unclaimedDevices) { device in
                            Text(device.fingerprint).tag(Optional(device.id))
                        }
                    }
                } footer: {
                    Text(deviceFooter)
                        // This line exists because binding is an inference from
                        // timing, not proof: two people arriving together can
                        // bind the wrong phone. Showing what is about to be
                        // remembered, rather than deciding quietly, is the
                        // point of this whole sheet.
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }
            }
            .navigationTitle("Remember Visitor")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        onSave(trimmedName, kind, deviceID)
                        dismiss()
                    }
                    .disabled(trimmedName.isEmpty)
                }
            }
        }
    }

    private var deviceFooter: String {
        if deviceID == nil {
            return "Without a device they will not be recognised automatically next time."
        }
        return "This phone joined the network just now. If someone else arrived at the same moment, pick theirs instead."
    }
}
