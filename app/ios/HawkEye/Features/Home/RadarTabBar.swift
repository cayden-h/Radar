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
/// A fixed-height row, not a floating or absolutely-positioned bar — the
/// parent is expected to place this at the bottom of a `VStack` and handle
/// safe-area insets itself, per the surrounding screen's layout.
struct RadarTabBar: View {
    @Binding var selection: RadarTab
    var onBack: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            backButton

            tabButton(
                tab: .camera,
                systemImage: "video.fill",
                label: "Camera"
            )

            tabButton(
                tab: .videos,
                systemImage: "play.rectangle.fill",
                label: "Videos"
            )

            tabButton(
                tab: .people,
                systemImage: "person.badge.plus",
                label: "People"
            )
        }
        .frame(height: Hit.min + Space.lg)
        .background(Palette.surface)
        .overlay(alignment: .top) {
            Rectangle()
                .fill(Palette.hairline)
                .frame(height: 1)
        }
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
            .foregroundStyle(Palette.inkMuted)
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
        label: String,
        alwaysTint: Color? = nil
    ) -> some View {
        let isSelected = selection == tab
        let tint = alwaysTint ?? (isSelected ? Palette.calm : Palette.inkMuted)

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
}

#Preview("Tab bar") {
    struct PreviewHost: View {
        @State private var selection: RadarTab = .camera
        var body: some View {
            ZStack {
                Palette.ground.ignoresSafeArea()
                VStack {
                    Spacer()
                    RadarTabBar(selection: $selection, onBack: {})
                }
            }
        }
    }
    return PreviewHost()
}
