import SwiftUI

/// One saved incident: the interior activity, the AI summary, the timestamped
/// call transcript, and a way to hand the whole thing to the people who
/// might need it as evidence.
///
/// **Front-end only, for now.** See the honesty note on `Recording` — the
/// playback area is an honest placeholder rather than a fabricated video,
/// and "Send as Evidence" below records local UI state only; no bytes go
/// anywhere yet.
struct VideoDetailView: View {
    var recording: Recording

    @State private var sendState: SendState = .idle

    private enum SendState { case idle, sending, sent }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.lg) {
                playbackPlaceholder

                VStack(alignment: .leading, spacing: Space.xs) {
                    HStack(spacing: 8) {
                        Image(systemName: recording.incidentType.symbol)
                            .font(.system(size: 13, weight: .semibold))
                        Text(recording.incidentType.title)
                            .font(.system(size: 15, weight: .semibold))
                    }
                    .foregroundStyle(recording.incidentType.tint)

                    Text(recording.startedAt.formatted(.dateTime.month(.wide).day().year().hour().minute()))
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }

                summaryCard

                transcriptSection

                sendSection
            }
            .padding(.horizontal, Space.gutter)
            .padding(.top, Space.sm)
            .padding(.bottom, Space.xl)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AmbientBackground())
        .navigationTitle(recording.incidentType.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(Palette.ground, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
    }

    // MARK: Playback

    /// What a real recording pipeline will fill in. Honest about not being
    /// one yet, per the root `CLAUDE.md`'s rule that a simulated capability
    /// must never be presentable as a measured one — here, as a captured one.
    private var playbackPlaceholder: some View {
        ZStack {
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)

            Image(systemName: "play.circle.fill")
                .font(.system(size: 44, weight: .regular))
                .foregroundStyle(Palette.inkFaint)
        }
        .frame(maxWidth: .infinity)
        .aspectRatio(16.0 / 10.0, contentMode: .fit)
    }

    // MARK: Summary

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("AI summary")
                .eyebrowStyle(Palette.inkFaint)
            Text(recording.summary)
                .font(TypeScale.body)
                .foregroundStyle(Palette.ink.opacity(0.9))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)
        )
    }

    // MARK: Transcript

    private var transcriptSection: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            Text("Call transcript")
                .eyebrowStyle(Palette.inkFaint)

            VStack(alignment: .leading, spacing: Space.md) {
                ForEach(Array(recording.transcript.enumerated()), id: \.element.id) { index, line in
                    TranscriptEntryRow(
                        line: line,
                        elapsed: Self.elapsed(from: recording.startedAt, to: line.at, fallbackIndex: index)
                    )
                }
            }
            .padding(Space.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(Palette.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .strokeBorder(Palette.hairline, lineWidth: 1)
            )
        }
    }

    /// The sample transcript lines all share one placeholder `at`, since they
    /// are illustrative rather than captured — see `Recording.samples`. A
    /// real recording's lines will each carry their own time and this falls
    /// away; until then, spacing them out by index keeps the timeline
    /// readable instead of printing the same "0:00" five times.
    private static func elapsed(from start: Date, to at: Date, fallbackIndex: Int) -> String {
        let seconds = at > start ? at.timeIntervalSince(start) : Double(fallbackIndex) * 14
        let s = max(0, Int(seconds))
        return String(format: "%d:%02d", s / 60, s % 60)
    }

    // MARK: Send

    private var sendSection: some View {
        Button(action: send) {
            HStack(spacing: 8) {
                if sendState == .sending {
                    ProgressView().controlSize(.small).tint(Palette.ground)
                } else {
                    Image(systemName: sendState == .sent ? "checkmark.circle.fill" : "paperplane.fill")
                        .font(.system(size: 15, weight: .semibold))
                }
                Text(sendState == .sent ? "Sent as Evidence" : "Send as Evidence")
                    .font(.system(size: 16, weight: .semibold))
            }
            .foregroundStyle(Palette.ground)
            .frame(maxWidth: .infinity)
            .frame(height: Hit.min)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(sendState == .sent ? Palette.calm : Palette.ink)
            )
        }
        .buttonStyle(.pressable)
        .disabled(sendState != .idle)
        .accessibilityLabel(sendState == .sent ? "Sent as evidence" : "Send as evidence")
        .padding(.top, Space.sm)
    }

    /// Local UI state only. There is no destination yet — see the honesty
    /// note on the type.
    private func send() {
        guard sendState == .idle else { return }
        withAnimation(Motion.standard) { sendState = .sending }
        Task {
            try? await Task.sleep(for: .milliseconds(900))
            withAnimation(Motion.standard) { sendState = .sent }
        }
    }
}

// MARK: - Transcript row

private struct TranscriptEntryRow: View {
    var line: TranscriptLine
    var elapsed: String

    private var tint: Color {
        switch line.speaker {
        case .operatorVoice: return Palette.fire
        case .caller: return Palette.calm
        case .resident: return Palette.personMoving
        case .system: return Palette.inkFaint
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: Space.md) {
            Text(elapsed)
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(Palette.inkFaint)
                .frame(width: 36, alignment: .leading)

            VStack(alignment: .leading, spacing: 2) {
                Text(line.speaker.label)
                    .eyebrowStyle(tint.opacity(0.9))
                Text(line.text)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink.opacity(0.9))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}
