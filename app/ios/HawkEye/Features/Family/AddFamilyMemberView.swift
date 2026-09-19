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
