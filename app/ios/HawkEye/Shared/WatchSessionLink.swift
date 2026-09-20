import Foundation
import os
#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

/// One logger for the whole relay, on both devices.
///
/// A link that silently fails to deliver is the single most likely thing to go
/// wrong here and the hardest to see, because both apps keep running and simply
/// disagree. `log stream --predicate 'subsystem == "ai.hawkeye"'` on either
/// simulator shows which half is quiet.
let watchLinkLog = Logger(subsystem: "ai.hawkeye", category: "watchlink")

/// Which end of the link this is.
///
/// The two ends are not symmetric. The phone publishes a latest-wins snapshot
/// that is cheap to lose, because another one is along shortly. The watch sends
/// commands that must not be lost, because each one is a thing a frightened
/// person did on purpose.
enum WatchLinkRole: Sendable {
    case phone
    case watch

    /// The key this end reads from an inbound payload.
    var inboundKey: String {
        switch self {
        case .phone: WatchWire.commandKey
        case .watch: WatchWire.snapshotKey
        }
    }

    /// The key this end writes.
    var outboundKey: String {
        switch self {
        case .phone: WatchWire.snapshotKey
        case .watch: WatchWire.commandKey
        }
    }
}

#if canImport(WatchConnectivity)

/// The WatchConnectivity plumbing, shared by both apps.
///
/// **Nothing in here knows what a notice is.** It moves `Data` and reports
/// reachability, and the two stores on either side do the rest. That split is
/// what makes the interesting half testable without a paired device.
///
/// Callbacks arrive on WatchConnectivity's own queue, never the main actor, so
/// they are `@Sendable` and hand over `Data`, which is. `WCSession`'s own
/// dictionaries are `[String: Any]` and are unwrapped here rather than being
/// carried across an isolation boundary.
final class WatchSessionLink: NSObject, @unchecked Sendable {

    typealias PayloadHandler = @Sendable (Data) -> Void
    typealias ReachabilityHandler = @Sendable (Bool) -> Void

    private let role: WatchLinkRole
    private let onPayload: PayloadHandler
    private let onReachability: ReachabilityHandler

    init(
        role: WatchLinkRole,
        onPayload: @escaping PayloadHandler,
        onReachability: @escaping ReachabilityHandler
    ) {
        self.role = role
        self.onPayload = onPayload
        self.onReachability = onReachability
        super.init()
    }

    /// True when WatchConnectivity exists on this device at all. False on an
    /// iPad, and false in a simulator with no paired watch.
    var isSupported: Bool { WCSession.isSupported() }

    var isReachable: Bool {
        guard WCSession.isSupported() else { return false }
        return WCSession.default.isReachable
    }

    func activate() {
        guard WCSession.isSupported() else {
            watchLinkLog.error("WatchConnectivity is not supported on this device")
            return
        }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        watchLinkLog.info("activating, role=\(String(describing: self.role), privacy: .public)")
    }

    /// Publish a payload to the other end.
    ///
    /// Returns false when nothing left the device, so a caller that gates on
    /// change can avoid recording a snapshot it never managed to send.
    ///
    /// The phone's snapshots go out as an application context, which is
    /// latest-wins and survives the watch app being asleep, plus a message when
    /// the watch is awake so the update is immediate rather than next-wake.
    ///
    /// The watch's commands go out as a message when reachable and as queued
    /// user info when not, because a command must not be dropped just because
    /// the phone was in a pocket.
    @discardableResult
    func send(_ data: Data) -> Bool {
        guard WCSession.isSupported() else { return false }
        let session = WCSession.default
        guard session.activationState == .activated else {
            // Activation is asynchronous and the first publish routinely lands
            // before it finishes. Saying so lets the caller try again rather
            // than recording a snapshot that never left.
            watchLinkLog.notice("send skipped, session not activated yet")
            return false
        }
        let payload = [role.outboundKey: data]

        switch role {
        case .phone:
            // No watch is paired, so there is nowhere to publish. Without this
            // every snapshot change raises `WCErrorCodeDeviceNotPaired`, which
            // buries anything worth reading in the log.
            //
            // Deliberately not also gated on `isWatchAppInstalled`: that flag
            // reports false for a watch app side-loaded with `simctl install`
            // rather than installed through the phone's companion, which is how
            // every simulator run of this gets set up. Gating on it means the
            // phone silently never publishes and the watch sits on "connecting"
            // with nothing to show for it.
            #if os(iOS)
            guard session.isPaired else {
                watchLinkLog.notice("send skipped, no watch is paired")
                return false
            }
            #endif
            // An application context that is identical to the last one is
            // rejected, which is fine: an identical snapshot has nothing to say.
            do {
                try session.updateApplicationContext(payload)
            } catch {
                watchLinkLog.error("application context rejected: \(error.localizedDescription, privacy: .public)")
            }
            if session.isReachable {
                session.sendMessage(payload, replyHandler: nil, errorHandler: { error in
                    watchLinkLog.error("message failed: \(error.localizedDescription, privacy: .public)")
                })
            }
            watchLinkLog.info("published \(data.count) bytes, reachable=\(session.isReachable)")
            return true

        case .watch:
            if session.isReachable {
                session.sendMessage(payload, replyHandler: nil, errorHandler: { [onReachability] _ in
                    // A failed message is not a dropped command: fall back to
                    // the queue, which survives the phone being unreachable.
                    onReachability(false)
                    WCSession.default.transferUserInfo(payload)
                })
            } else {
                session.transferUserInfo(payload)
            }
            return true
        }
    }

    /// Pull this end's payload out of a WatchConnectivity dictionary.
    ///
    /// Returns nil for anything else on the wire, so an unrelated key added
    /// later cannot be mistaken for a snapshot or a command.
    private func payload(in dictionary: [String: Any]) -> Data? {
        guard let data = dictionary[role.inboundKey] as? Data else {
            watchLinkLog.notice("inbound payload had no \(self.role.inboundKey, privacy: .public) key")
            return nil
        }
        watchLinkLog.info("received \(data.count) bytes")
        return data
    }
}

extension WatchSessionLink: WCSessionDelegate {

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: (any Error)?
    ) {
        if let error {
            watchLinkLog.error("activation failed: \(error.localizedDescription, privacy: .public)")
        } else {
            watchLinkLog.info("activated, state=\(activationState.rawValue) reachable=\(session.isReachable)")
        }
        onReachability(activationState == .activated && session.isReachable)
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        onReachability(session.isReachable)
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        if let data = payload(in: message) { onPayload(data) }
    }

    func session(_ session: WCSession, didReceiveApplicationContext context: [String: Any]) {
        if let data = payload(in: context) { onPayload(data) }
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        if let data = payload(in: userInfo) { onPayload(data) }
    }

    #if os(iOS)
    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        // The only supported recovery is reactivating for the newly paired watch.
        WCSession.default.activate()
    }
    #endif
}

#endif
