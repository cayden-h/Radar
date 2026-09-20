import Foundation

/// The three things the watch can be showing.
///
/// Three and no more. `app/CLAUDE.md` describes four screens, and the live
/// incident surface is deliberately not one of them here: the call, the
/// transcript and the takeover control are the phone's, and a wrist that offers
/// a second way to end a call is a misfire waiting to happen.
enum WatchScreen: Sendable, Hashable {
    /// Armed, and when the shield last moved. One line.
    case idle
    /// The still frame, the camera's sentence, and the two controls.
    case notice(WatchNotice)
    /// What the hub did with the answer the resident gave.
    case saved(WatchOutcome)
}

/// Which screen a snapshot means, as a pure function of the snapshot and the
/// clock.
///
/// Pulled out of the view so the interesting rule is testable without a paired
/// device, a simulator, or a running hub. Nothing here reads global state.
enum WatchRouter {

    /// How long the confirmation stays up after the hub records an answer.
    ///
    /// Long enough to read on a wrist that may have been raised late, short
    /// enough that the watch returns to Idle on its own rather than holding a
    /// stale screen until someone dismisses it.
    static let confirmationLingers: TimeInterval = 15

    static func screen(for snapshot: WatchSnapshot, now: Date = Date()) -> WatchScreen {

        // An answer that has not landed yet outranks everything. A resident who
        // held Start Incident must never be dropped back to Idle as though they
        // had not, and a failure must be seen rather than expiring quietly.
        if let outcome = snapshot.outcome {
            switch outcome.disposition {
            case .pending, .failed:
                return .saved(outcome)
            case .recorded:
                let recordedAt = outcome.recordedAt ?? .distantPast
                if now.timeIntervalSince(recordedAt) < confirmationLingers {
                    return .saved(outcome)
                }
            }
        }

        // A notice the resident has not answered. An outcome for this same
        // notice means it is answered and the confirmation has already expired,
        // so the notice must not come back around a second time.
        if let notice = snapshot.notice, snapshot.outcome?.noticeID != notice.noticeID {
            return .notice(notice)
        }

        return .idle
    }
}
