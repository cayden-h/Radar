import Foundation

/// How healthy the connection is, on either device.
///
/// Shared because both apps answer the same question and must answer it the
/// same way. The phone reports its socket to the hub; the watch reports the
/// relay to the phone, and is never more optimistic than the phone is.
///
/// It exists so that neither app can pretend to be live when it is not. A
/// view that draws a stale house without saying so is the quiet lie this
/// project is built against.
enum LinkState: Sendable, Hashable {
    case offline
    case connecting
    case live
    /// The stream dropped and is backing off before retrying.
    case reconnecting

    var label: String {
        switch self {
        case .offline: "Not connected"
        case .connecting: "Connecting"
        case .live: "Live"
        case .reconnecting: "Reconnecting"
        }
    }
}
