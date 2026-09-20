import SwiftUI

/// The Videos tab. Recordings live on the desktop replay console, not on the
/// phone, so this screen just points there instead of trying to play video.
///
/// Reached from `RadarTabBar`'s Videos tab, not a modal — there is no close
/// button here on purpose; switching tabs is how you leave.
struct VideoLibraryView: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                Text("Videos")
                    .font(TypeScale.title)
                    .foregroundStyle(Palette.ink)

                message
                    .frame(maxWidth: .infinity, minHeight: 320, alignment: .center)
            }
            .padding(.horizontal, Space.gutter)
            .padding(.top, Space.sm)
            .padding(.bottom, Space.lg)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AmbientBackground())
        .preferredColorScheme(.dark)
    }

    private var message: some View {
        VStack(spacing: Space.sm) {
            Image(systemName: "desktopcomputer")
                .font(.system(size: 40, weight: .regular))
                .foregroundStyle(Palette.inkMuted)

            Text("View video files on the desktop")
                .font(TypeScale.body)
                .foregroundStyle(Palette.ink)

            Text("Saved recordings are available in the replay console on your computer.")
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkMuted)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, Space.gutter)
    }
}
