import SwiftUI

/// The tabs available on the Radar main screen's bottom bar.
///
/// A live call is deliberately not a tab here — see `LiveCallBanner`. The
/// call screen bleeds full-screen when it's up, the same way it always did;
/// the bar (and this enum) only ever covers the three pages a resident can
/// freely switch between.
enum RadarTab: Hashable {
    case camera
    case videos
    case people
}

/// The bottom tab bar for the Radar main screen.
///
/// A floating glass pill, inset from both edges, rather than a bar docked
/// flush to them — the same frosted-material language `glassPanel` gives
/// every other surface now, so the bar reads as one more pane held up to the
/// ambient gradient instead of a hard shelf across the bottom of the screen.
/// Camera — the page a resident lands on and returns to most — is raised out
/// of the row into its own circular button carrying the mascot, the same
/// principle the whole app now follows wherever a bar like this appears: one
/// raised centre button, and everything else balanced two-and-two around it
/// rather than lopsided.
///
/// That symmetry is why Household moved here from a header icon on Home —
/// it made the fourth side slot, matching Back and Videos on the left against
/// People and Household on the right. Nothing about what any of the five
/// buttons *do* changed, only where the household one lives.
///
/// Still expects its parent to place it at the bottom of a `VStack` and
/// handle safe-area insets itself, per the surrounding screen's layout — the
/// bar supplies its own bottom padding, not a full-bleed background, so
/// whatever is behind the parent (the ambient gradient) shows through around
/// the pill rather than being papered over.
struct RadarTabBar: View {
    @Binding var selection: RadarTab
    var onBack: () -> Void
    var onHousehold: () -> Void

    var body: some View {
        ZStack {
            HStack(spacing: 0) {
                backButton
                tabButton(tab: .videos, systemImage: "play.rectangle.fill", label: "Videos")
                Color.clear.frame(width: 70)
                tabButton(tab: .people, systemImage: "person.badge.plus", label: "People")
                householdButton
            }
            .padding(.horizontal, Space.sm)
            .frame(height: 68)
            .glassPanel(cornerRadius: Radius.pill)

            cameraButton
        }
        .padding(.horizontal, Space.gutter)
        .padding(.bottom, Space.xs)
    }

    // MARK: Buttons

    private var backButton: some View {
        Button {
            onBack()
        } label: {
            VStack(spacing: Space.xs) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 20, weight: .semibold))
                Text("Back")
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(Palette.ink.opacity(0.85))
            .frame(maxWidth: .infinity)
            .frame(minWidth: Hit.min, minHeight: Hit.min)
            .contentShape(Rectangle())
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Back, disconnect from hub")
    }

    private func tabButton(
        tab: RadarTab,
        systemImage: String,
        label: String
    ) -> some View {
        let isSelected = selection == tab
        let tint = isSelected ? Palette.calm : Palette.ink.opacity(0.85)

        return Button {
            withAnimation(Motion.snappy) {
                selection = tab
            }
        } label: {
            VStack(spacing: Space.xs) {
                Image(systemName: systemImage)
                    .font(.system(size: 20, weight: .semibold))
                Text(label)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity)
            .frame(minWidth: Hit.min, minHeight: Hit.min)
            .contentShape(Rectangle())
        }
        .buttonStyle(.pressable)
        .accessibilityLabel(label)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    /// Opens the household sheet directly, rather than switching `selection`
    /// — Household isn't a page in the `Group { switch selectedTab }` on
    /// Home, it's a modal, the same as it was when this button lived in the
    /// header. Only its position moved.
    private var householdButton: some View {
        Button {
            onHousehold()
        } label: {
            VStack(spacing: Space.xs) {
                Image(systemName: "person.2.fill")
                    .font(.system(size: 20, weight: .semibold))
                Text("House")
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(Palette.ink.opacity(0.85))
            .frame(maxWidth: .infinity)
            .frame(minWidth: Hit.min, minHeight: Hit.min)
            .contentShape(Rectangle())
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Household")
    }

    /// The raised centre button. Bigger than a `Hit.min` tap target on
    /// purpose — it is the button a resident reaches for without looking.
    private var cameraButton: some View {
        let isSelected = selection == .camera

        return Button {
            withAnimation(Motion.snappy) {
                selection = .camera
            }
        } label: {
            ZStack {
                Circle()
                    .fill(isSelected ? Palette.calm.opacity(0.24) : Color.clear)
                Image("Mascot")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 32, height: 32)
            }
            .frame(width: 62, height: 62)
            .glassPanel(cornerRadius: Radius.pill, tint: isSelected ? Palette.calm : .clear)
            .shadow(color: Palette.calm.opacity(isSelected ? 0.35 : 0.18), radius: 14, y: 6)
        }
        .buttonStyle(.pressable)
        .offset(y: -16)
        .accessibilityLabel("Camera")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

#Preview("Tab bar") {
    struct PreviewHost: View {
        @State private var selection: RadarTab = .camera
        var body: some View {
            ZStack {
                Palette.groundGradient.ignoresSafeArea()
                VStack {
                    Spacer()
                    RadarTabBar(selection: $selection, onBack: {}, onHousehold: {})
                }
            }
        }
    }
    return PreviewHost()
}
