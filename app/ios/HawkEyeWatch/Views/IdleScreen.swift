import SwiftUI

/// Armed, and when the shield last moved. One line, per `app/CLAUDE.md`.
///
/// The interesting thing about this screen is that its resting state is a
/// privacy claim, not an absence of news: **the camera cannot see, because
/// there is an opaque object in front of the lens.** Saying that plainly, on
/// the screen someone glances at all day, is most of the product's argument.
struct IdleScreen: View {

    var snapshot: WatchSnapshot
    var link: LinkState
    var now: Date

    private var shield: ShieldStatus? { snapshot.shield }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.sm) {

                VStack(alignment: .leading, spacing: Space.md) {
                    HStack(spacing: Space.xs) {
                        Circle()
                            .fill(statusTint)
                            .frame(width: 7, height: 7)
                        Text(headline)
                            .eyebrowStyle(statusTint)
                        Spacer(minLength: 0)
                    }

                    VStack(alignment: .leading, spacing: Space.xs) {
                        Text(shield?.state.label ?? "Shield not reported")
                            .font(TypeScale.heading)
                            .foregroundStyle(Palette.ink)

                        Text(shield?.state.detail
                             ?? "The shutter has not said where the shield is.")
                            .font(.system(size: 13, design: .rounded))
                            .foregroundStyle(Palette.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    if let shield, shield.changedAt > .distantPast {
                        Text(movedLine(shield))
                            .font(TypeScale.numeric)
                            .foregroundStyle(Palette.inkFaint)
                    }
                }
                .padding(Space.sm)
                .frame(maxWidth: .infinity, alignment: .leading)
                .glassPanel()

                if let reason = shield?.refusalReason {
                    Text(reason)
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(Palette.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(Space.sm)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassPanel(cornerRadius: Radius.sm, tint: Palette.personUnresponsive)
                }

                if snapshot.incidentOpen {
                    Text("An incident is open. The call is on your phone.")
                        .font(.system(size: 12, weight: .medium, design: .rounded))
                        .foregroundStyle(Palette.live)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, Space.sm)
            .padding(.bottom, Space.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: Copy

    /// What the watch is allowed to claim about itself right now.
    ///
    /// "Armed" is only said when the phone is actually holding the hub. A watch
    /// that says armed while disconnected is claiming a system is watching when
    /// nothing is.
    private var headline: String {
        switch link {
        case .live: snapshot.hubName.map { "Armed · \($0)" } ?? "Armed"
        case .connecting: "Connecting to your phone"
        case .reconnecting: "Reconnecting"
        case .offline: "Not connected"
        }
    }

    private var statusTint: Color {
        switch link {
        case .live: shield?.state == .refused ? Palette.personUnresponsive : Palette.calm
        case .connecting, .reconnecting: Palette.unconfirmed
        case .offline: Palette.inkFaint
        }
    }

    private func movedLine(_ shield: ShieldStatus) -> String {
        let verb = shield.state == .refused ? "Refused" : "Last moved"
        let seconds = now.timeIntervalSince(shield.changedAt)
        return "\(verb) \(Self.elapsed(seconds)) ago"
    }

    /// Coarse on purpose. Nobody on a wrist needs "1,847 seconds".
    static func elapsed(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds))
        if s < 60 { return "\(s)s" }
        if s < 3_600 { return "\(s / 60)m" }
        if s < 86_400 { return "\(s / 3_600)h" }
        return "\(s / 86_400)d"
    }
}
