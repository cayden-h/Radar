import SwiftUI

/// The roster, read-only save for removal.
///
/// There is no add button here, deliberately: `app/CLAUDE.md` is explicit that
/// this app has no settings screen, and the only moment the system has a
/// device to bind is the moment it just saw one join, which is what
/// `RememberVisitorSheet` is for. This screen shows who is already
/// remembered, and lets the resident forget someone.
struct HouseholdList: View {
    let members: [HouseholdMember]
    let onForget: (String) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if members.isEmpty {
                    ContentUnavailableView(
                        "Nobody remembered yet",
                        systemImage: "person.crop.circle.badge.questionmark",
                        description: Text("People are added when you recognise them on an alert.")
                    )
                } else {
                    List {
                        ForEach(members) { member in
                            row(for: member)
                        }
                        .onDelete { offsets in
                            for index in offsets { onForget(members[index].id) }
                        }
                    }
                }
            }
            .navigationTitle("Household")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private func row(for member: HouseholdMember) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(member.name)
                .font(TypeScale.body)
                .foregroundStyle(Palette.ink)
            Text(detail(for: member))
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkMuted)
        }
        .padding(.vertical, Space.hair)
    }

    /// `isRecognisable` being false must say so in words. A blank line would
    /// let the roster look like it can see everyone in it, and a named guest
    /// with no device is a real, legal state that the UI must not paper over.
    private func detail(for member: HouseholdMember) -> String {
        var parts = [member.kind.label]
        if member.isRecognisable {
            if let device = member.devices.first {
                parts.append(device.label ?? device.fingerprint)
            }
        } else {
            parts.append("no device, will not be recognised automatically")
        }
        return parts.joined(separator: " · ")
    }
}
