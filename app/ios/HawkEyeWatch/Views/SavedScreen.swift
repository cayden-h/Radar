import SwiftUI

/// What the hub did with the answer the resident gave.
///
/// **`Recorded` is set from the hub's acknowledgement and never optimistically
/// on send.** A watch that confirms something the hub did not take is exactly
/// the quiet lie this project is built against, so this screen has three states
/// and shows the honest one.
///
/// It also says where the record actually is. The sealed, hash-chained copy
/// lives on the hub and is read back on the phone and at `/replay`; the watch
/// keeps nothing, which is why it can be truthful about what it knows.
struct SavedScreen: View {

    var outcome: WatchOutcome
    var now: Date

    var body: some View {
        ScrollView {
            VStack(spacing: Space.md) {

                ZStack {
                    Circle()
                        .fill(tint.opacity(0.16))
                    Image(systemName: symbol)
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(tint)
                }
                .frame(width: 52, height: 52)
                .padding(.top, Space.sm)

                VStack(spacing: Space.xs) {
                    Text(headline)
                        .font(.system(size: 17, weight: .semibold, design: .rounded))
                        .foregroundStyle(Palette.ink)
                        .multilineTextAlignment(.center)

                    Text(detail)
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(Palette.inkMuted)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if let recordedAt = outcome.recordedAt {
                    Text(recordedAt.formatted(date: .omitted, time: .shortened))
                        .font(TypeScale.numeric)
                        .foregroundStyle(Palette.inkFaint)
                }
            }
            .padding(Space.md)
            .padding(.bottom, Space.xs)
            .frame(maxWidth: .infinity)
            .glassPanel(tint: tint)
            .padding(.horizontal, Space.sm)
            .padding(.top, Space.sm)
        }
    }

    // MARK: Copy

    private var headline: String {
        switch outcome.disposition {
        case .pending: "Sending"
        case .recorded: outcome.action.pastTense
        case .failed: "Not sent"
        }
    }

    private var detail: String {
        switch outcome.disposition {
        case .pending:
            return "Waiting for your phone."
        case .failed:
            return outcome.failureReason ?? "The hub did not take it."
        case .recorded:
            switch outcome.action {
            case .startIncident:
                // The one place the watch says what it just released. It is
                // worth being exact: a human hold is the only thing in this
                // system that can put a call through to an operator.
                return "Sealed into the record. The call and the transcript are on your phone."
            case .expected:
                // Session-scoped, and said so plainly, because the resident
                // will otherwise assume they just added someone permanently.
                return "Vouched for this visit only. Nothing was saved about them. "
                    + "To remember them, use your phone."
            }
        }
    }

    private var symbol: String {
        switch outcome.disposition {
        case .pending: "arrow.up.circle"
        case .recorded: "checkmark.circle.fill"
        case .failed: "exclamationmark.triangle.fill"
        }
    }

    private var tint: Color {
        switch outcome.disposition {
        case .pending: Palette.unconfirmed
        case .recorded: outcome.action == .startIncident ? Palette.live : Palette.calm
        case .failed: Palette.personUnresponsive
        }
    }
}
