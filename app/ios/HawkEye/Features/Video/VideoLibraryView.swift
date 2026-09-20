import SwiftUI

/// The saved-incident library. One entry per past incident: what Hawk Eye
/// saw in the house, timestamped alongside the 911 call transcript.
///
/// **Front-end only, for now.** `Recording.samples` is the entire data
/// source — see the honesty note there. This screen and `VideoDetailView`
/// are what a real recording pipeline plugs into; nothing about their shape
/// should need to change when it does.
///
/// Reached from `RadarTabBar`'s Videos tab, not a modal — there is no close
/// button here on purpose; switching tabs is how you leave.
struct VideoLibraryView: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Space.lg) {
                    Text("Videos")
                        .font(TypeScale.title)
                        .foregroundStyle(Palette.ink)

                    VStack(spacing: Space.sm) {
                        ForEach(Recording.samples) { recording in
                            NavigationLink(value: recording) {
                                RecordingRow(recording: recording)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.horizontal, Space.gutter)
                .padding(.top, Space.sm)
                .padding(.bottom, Space.lg)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(AmbientBackground())
            .navigationDestination(for: Recording.self) { recording in
                VideoDetailView(recording: recording)
            }
            .toolbarBackground(Palette.ground, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
        .preferredColorScheme(.dark)
    }
}

// MARK: - Row

private struct RecordingRow: View {
    var recording: Recording

    private static let dateStyle: Date.FormatStyle = .dateTime.month(.abbreviated).day().hour().minute()

    var body: some View {
        HStack(spacing: Space.md) {
            ZStack {
                RoundedRectangle(cornerRadius: Radius.sm, style: .continuous)
                    .fill(recording.incidentType.tint.opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: recording.incidentType.symbol)
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(recording.incidentType.tint)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(recording.incidentType.title)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Palette.ink)
                Text(recording.startedAt.formatted(Self.dateStyle))
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            Spacer(minLength: Space.sm)

            VStack(alignment: .trailing, spacing: 3) {
                Text(Self.duration(recording.duration))
                    .font(TypeScale.numeric)
                    .foregroundStyle(Palette.inkMuted)
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Palette.inkFaint)
            }
        }
        .padding(Space.md)
        .glassPanel(cornerRadius: Radius.md)
    }

    private static func duration(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}
