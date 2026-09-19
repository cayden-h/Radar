import SwiftUI

/// Stage 2. The product.
///
/// Live interior view at the top, the presence roster under it, three incident
/// buttons at the bottom. No tabs, no settings, no history. When an incident is
/// open this screen hands over to `IncidentView` and does not compete with it.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    var hubName: String

    @State private var pendingIncident: IncidentType?

    private var client: any HawkEyeClienting { model.client }

    var body: some View {
        VStack(spacing: Space.lg) {
            header

            VStack(spacing: Space.xs) {
                InteriorView(state: client.interior)
                    .frame(maxWidth: .infinity)
                    .aspectRatio(1.12, contentMode: .fit)

                // The honesty rule applied to the drawing. The plan is
                // authored, not discovered: walls are the static baseline the
                // system subtracts to see people, and it never maps them.
                Text("Floor plan set up once, by hand. Hawk Eye does not map walls.")
                    .font(.system(size: 10))
                    .foregroundStyle(Palette.inkFaint)
            }

            PresenceRoster(state: client.interior)

            Spacer(minLength: 0)

            IncidentBar { type in
                pendingIncident = type
            }
        }
        .padding(.horizontal, Space.gutter)
        .padding(.bottom, Space.lg)
        .fullScreenCover(item: Binding(
            get: { client.incident },
            set: { _ in }
        )) { incident in
            IncidentView(incident: incident)
                .environment(model)
        }
        .confirmationDialog(
            pendingIncident.map { "Call 911 for \($0.title.lowercased())?" } ?? "",
            isPresented: Binding(
                get: { pendingIncident != nil },
                set: { if !$0 { pendingIncident = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let type = pendingIncident {
                Button("Raise \(type.title)", role: .destructive) {
                    let raise = type
                    pendingIncident = nil
                    Task { try? await client.raiseIncident(raise) }
                }
            }
            Button("Cancel", role: .cancel) { pendingIncident = nil }
        } message: {
            // One confirmation, because a misfired 911 call is a real-world
            // harm. One tap raises it; the confirmation is the tap.
            Text("Hawk Eye will call 911 and tell them what it can verify.")
        }
    }

    // MARK: Header

    private var header: some View {
        HStack(alignment: .center, spacing: Space.md) {
            Wordmark(size: 20, breathing: false)

            Spacer(minLength: Space.sm)

            HStack(spacing: 6) {
                Circle()
                    .fill(client.link == .live ? Palette.calm : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                Text(hubName)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }
        }
        .padding(.top, Space.sm)
        .overlay(alignment: .bottom) {
            if client.missedFrames {
                // A gap in the stream's `seq` means a frame was missed. Say so
                // rather than quietly drawing a house that may be behind.
                Text("The stream skipped a frame. This view may be behind.")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
                    .offset(y: 18)
            } else if !client.interior.calibrationHealthy {
                // A stale baseline produces confident nonsense. The system
                // suppresses escalation upstream; the app says so rather than
                // drawing a map it cannot stand behind.
                Text("Baseline is stale. Positions may be wrong.")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.fire)
                    .offset(y: 18)
            }
        }
    }
}

// MARK: - Roster

/// The list under the map. It exists so the three states are named in words as
/// well as drawn, because a judge across a table cannot see a blur radius.
private struct PresenceRoster: View {
    var state: InteriorState

    var body: some View {
        VStack(spacing: Space.sm) {
            HStack {
                Text(summary)
                    .eyebrowStyle(Palette.inkMuted)
                    // Three clauses at full tracking just overrun an iPhone
                    // width. Shrink the line rather than wrap it: a summary
                    // that breaks mid-count reads as a layout accident.
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer()
                if let co = state.coPpm, co > 9 {
                    HStack(spacing: 5) {
                        Image(systemName: "aqi.medium")
                            .font(.system(size: 10, weight: .semibold))
                        Text("CO \(Int(co)) ppm")
                            .font(TypeScale.numeric)
                        if state.coSourceIsSimulated {
                            // The honesty rule, enforced in the UI. A simulated
                            // reading cannot be shown as a measured one.
                            Text("SIM")
                                .font(.system(size: 9, weight: .bold))
                                .padding(.horizontal, 4).padding(.vertical, 1)
                                .background(Capsule().fill(Palette.inkFaint.opacity(0.3)))
                        }
                    }
                    .foregroundStyle(Palette.fire)
                }
            }

            ForEach(state.presences) { presence in
                PresenceRow(presence: presence, floorplan: state.floorplan)
                    .transition(.opacity.combined(with: .offset(y: 8)))
            }
        }
        .animation(Motion.arrive, value: state.presences)
    }

    /// Counts, in the order a person would want them. The unexpected person is
    /// named in the summary as well as in their own row, because the summary is
    /// the line someone reads first and it must not say "2 people inside" as
    /// though that were unremarkable.
    private var summary: String {
        let people = state.peopleCount
        let unexpected = state.unexpectedCount
        let others = state.presences.count - people
        var text = people == 1 ? "1 person inside" : "\(people) people inside"
        if unexpected > 0 {
            text += unexpected == 1 ? " · 1 not expected" : " · \(unexpected) not expected"
        }
        if others > 0 { text += " · \(others) unconfirmed" }
        return text
    }
}

private struct PresenceRow: View {
    var presence: Presence
    var floorplan: Floorplan
    @State private var pulse = false

    /// The two person states, crossed with the one orthogonal axis. An
    /// unexpected person takes the violet whichever state they are in.
    private var tint: Color {
        if presence.isUnexpected { return Palette.personUnexpected }
        switch presence.state {
        case .personMoving: return Palette.personMoving
        case .personUnresponsive: return Palette.personUnresponsive
        case .unconfirmed, .unresolved: return Palette.unconfirmed
        }
    }

    /// True for the two rows that must not read as routine.
    private var emphasised: Bool {
        presence.state == .personUnresponsive || presence.isUnexpected
    }

    /// The headline, factual and not morbid. "Unexpected person" is what
    /// `agents/intruder` actually concluded: a confirmed person whose being
    /// here is not accounted for. It is not a recognition result and the words
    /// must not imply one.
    private var headline: String {
        presence.isUnexpected ? "Unexpected person" : presence.state.headline
    }

    /// The unexpected row carries its colour in the headline as well as the
    /// border, because the headline is the part read across a table. The
    /// unresponsive row keeps white type: it is already the loudest thing on
    /// the screen and does not need to compete with itself.
    private var headlineTint: Color {
        if presence.isUnexpected { return Palette.personUnexpected }
        return emphasised ? Palette.ink : Palette.ink.opacity(0.9)
    }

    private var roomName: String {
        floorplan.room(named: presence.zone)?.name ?? presence.zone
    }

    var body: some View {
        HStack(spacing: Space.md) {
            Circle()
                .fill(tint)
                .frame(width: 8, height: 8)
                .opacity(presence.state == .personUnresponsive ? (pulse ? 1 : 0.25) : 0.9)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(headline)
                        .font(emphasised ? TypeScale.bodyStrong : TypeScale.body)
                        .foregroundStyle(headlineTint)
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                    Text("· \(roomName)")
                        .font(TypeScale.body)
                        .foregroundStyle(Palette.inkMuted)
                        .lineLimit(1)
                }
                Text(detail)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkFaint)
            }

            Spacer(minLength: Space.sm)

            if presence.isUnexpected {
                // Reads as tracked, in one glyph, and leaves the headline and
                // the room name their full width. A badge spelling out "NOT
                // EXPECTED" said the same thing as the headline beside it and
                // pushed the room name into an ellipsis, which is worse.
                Image(systemName: "viewfinder")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Palette.personUnexpected)
                    .accessibilityHidden(true)
            }

            if let down = presence.stillDownS, down > 0 {
                // `still_down_s` is the clinical variable, not a diagnostic
                // detail, so it gets the largest number on this row.
                VStack(alignment: .trailing, spacing: 1) {
                    Text(Self.duration(down))
                        .font(.system(size: 15, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Palette.personUnresponsive)
                    Text("down")
                        .eyebrowStyle(Palette.inkFaint)
                }
            }
        }
        .padding(.horizontal, Space.lg)
        .padding(.vertical, Space.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(emphasised ? tint.opacity(0.10) : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(emphasised ? tint.opacity(0.45) : Palette.hairline, lineWidth: 1)
        )
        .onAppear {
            guard presence.state == .personUnresponsive else { return }
            withAnimation(Motion.urgent) { pulse = true }
        }
    }

    private var detail: String {
        var parts: [String] = []
        // First, so it survives truncation. This is a statement that the
        // household has no account of this person, not a claim about who they
        // are: the system does no recognition and must not imply that it does.
        if presence.isUnexpected { parts.append("Not accounted for") }
        parts.append(presence.state.detail)
        if let bpm = presence.breathingBpm { parts.append("\(Int(bpm.rounded())) breaths/min") }
        if presence.state.isPerson, presence.presenceClass != .unknown {
            parts.append(presence.presenceClass.label.lowercased())
        }
        return parts.joined(separator: " · ")
    }

    private static func duration(_ seconds: Double) -> String {
        let s = max(0, Int(seconds))
        return s < 60 ? "\(s)s" : String(format: "%d:%02d", s / 60, s % 60)
    }
}

// MARK: - Incident bar

/// Three buttons. One tap raises an incident.
private struct IncidentBar: View {
    var raise: (IncidentType) -> Void

    var body: some View {
        VStack(spacing: Space.sm) {
            Text("Call 911")
                .eyebrowStyle(Palette.inkFaint)

            HStack(spacing: Space.sm) {
                ForEach(IncidentType.allCases) { type in
                    Button { raise(type) } label: {
                        VStack(spacing: 7) {
                            Image(systemName: type.symbol)
                                .font(.system(size: 19, weight: .medium))
                            Text(type.title)
                                .font(.system(size: 14, weight: .semibold))
                        }
                        .foregroundStyle(type.tint)
                        .frame(maxWidth: .infinity)
                        .frame(height: 74)
                        .background(
                            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                .fill(type.tint.opacity(0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                                .strokeBorder(type.tint.opacity(0.32), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.pressable)
                    .accessibilityLabel("Raise \(type.title) incident")
                }
            }
        }
    }
}
