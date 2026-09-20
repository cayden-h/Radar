import Foundation
import Observation
import os

/// The phone's half of the watch link.
///
/// The watch never speaks to the hub. This is the reason it does not have to:
/// the phone already holds the socket, and this type turns what is on that
/// socket into a snapshot small enough for a wrist, then turns what comes back
/// from the wrist into calls on the hub client.
///
/// **Nothing here invents state.** Every field it publishes is read from the
/// client, and the one thing it authors, `WatchOutcome`, is only ever marked
/// `recorded` after the hub has acknowledged. A watch that says "recorded" for
/// something the hub never took is exactly the quiet lie this project is built
/// against.
@MainActor
@Observable
final class PhoneWatchRelay {

    /// How often the snapshot is rebuilt. Sends are gated on the snapshot
    /// actually differing, so this is a change-detection interval and not a
    /// transmit rate.
    static let publishInterval: Duration = .milliseconds(500)

    private let client: any HawkEyeClienting

    /// Whether the watch app is awake and reachable right now. Surfaced so the
    /// phone can say "not on your watch" rather than implying delivery.
    private(set) var watchReachable = false

    /// The last snapshot actually sent. Also the equality gate.
    private(set) var published: WatchSnapshot?

    @ObservationIgnored private var link: WatchSessionLink?
    @ObservationIgnored private var pump: Task<Void, Never>?

    /// The answer the resident last gave on the wrist, and what the hub did
    /// with it. Authored here because it is the one fact the hub does not hold.
    @ObservationIgnored private var outcome: WatchOutcome?

    /// Commands already acted on, so a message and its queued fallback copy do
    /// not raise two incidents. WatchConnectivity delivers at least once.
    @ObservationIgnored private var handledCommandIDs: Set<String> = []

    init(client: any HawkEyeClienting) {
        self.client = client
    }

    // MARK: Lifecycle

    func start() {
        guard link == nil else { return }

        let link = WatchSessionLink(
            role: .phone,
            onPayload: { [weak self] data in
                // Off the main actor, on WatchConnectivity's queue. Decode is
                // pure, so it happens here; everything stateful hops first.
                guard let command = try? WatchWire.decode(WatchCommand.self, from: data) else { return }
                Task { @MainActor [weak self] in await self?.handle(command) }
            },
            onReachability: { [weak self] reachable in
                Task { @MainActor [weak self] in self?.watchReachable = reachable }
            }
        )
        self.link = link
        link.activate()

        pump = Task { [weak self] in
            while !Task.isCancelled {
                self?.publish()
                try? await Task.sleep(for: Self.publishInterval)
            }
        }
    }

    func stop() {
        pump?.cancel()
        pump = nil
    }

    // MARK: Phone to watch

    /// Rebuild the snapshot and send it only if it says something new.
    ///
    /// **`published` is recorded only after the payload has actually left the
    /// device.** Recording it on the attempt loses the first snapshot every
    /// time: `WCSession` activation is asynchronous, the first publish lands
    /// before it completes, and the change gate then blocks every retry because
    /// the snapshot it never sent already looks like the last one it sent. The
    /// watch sits on "connecting" forever with both apps running happily.
    func publish() {
        let next = snapshot()
        guard hasNews(next) else { return }
        let data: Data
        do {
            data = try WatchWire.encode(next)
        } catch {
            watchLinkLog.error("snapshot did not encode: \(error.localizedDescription, privacy: .public)")
            return
        }
        guard let link else {
            watchLinkLog.error("publish with no link")
            return
        }
        guard link.send(data) else { return }
        published = next
    }

    /// Whether this snapshot says anything the last one did not.
    ///
    /// **`generatedAt` is excluded on purpose.** It is rebuilt on every tick, so
    /// comparing whole snapshots makes every one of them look new and the gate
    /// stops gating: the phone then publishes at 2 Hz forever into a watch that
    /// has nothing new to draw, which is both a battery cost and a good way to
    /// have WatchConnectivity start dropping application contexts.
    private func hasNews(_ next: WatchSnapshot) -> Bool {
        guard var last = published else { return true }
        last.generatedAt = next.generatedAt
        return last != next
    }

    private func snapshot() -> WatchSnapshot {
        WatchSnapshot(
            generatedAt: Date(),
            hubLinked: client.link == .live,
            hubName: client.hello?.hubName,
            shield: client.interior.shield,
            notice: watchNotice(),
            outcome: outcome,
            incidentOpen: client.incident != nil
        )
    }

    /// The newest unanswered notice, trimmed for a wrist.
    ///
    /// **A notice with no narration is not sent.** The sentence is the whole
    /// point of the notification, and a wrist buzz that says nothing specific
    /// is worse than no buzz: it trains the resident to ignore the next one.
    /// Such a notice still reaches the phone, which has room to explain itself.
    private func watchNotice() -> WatchNotice? {
        guard let notice = client.notices.first, let narration = notice.narration else { return nil }
        return WatchNotice(
            noticeID: notice.noticeID,
            narration: narration,
            room: notice.room,
            raisedAt: notice.raisedAt,
            stillFrame: notice.stillFrame?.jpeg,
            presenceID: notice.presenceID,
            // Mock mode means the frame came from `SimulatedCameraFrame` and
            // the sentence came from a script, so the whole notice is marked
            // rather than only the half whose producer happened to say so.
            simulated: Config.useMocks || notice.provenance.simulated
        )
    }

    // MARK: Watch to phone

    private func handle(_ command: WatchCommand) async {
        guard !handledCommandIDs.contains(command.commandID) else { return }
        handledCommandIDs.insert(command.commandID)

        // Publish the pending state before doing the work, so the wrist stops
        // showing a button the moment it is pressed rather than when the hub
        // answers. The watch holds no state of its own here: even "sending" is
        // something the phone told it.
        outcome = WatchOutcome(
            commandID: command.commandID,
            noticeID: command.noticeID,
            action: command.action,
            disposition: .pending
        )
        publish()

        do {
            switch command.action {
            case .startIncident:
                // One type, so there is nothing to choose. The human hold on
                // the wrist is what released this; nothing else in the system
                // may reach this line.
                try await client.raiseIncident(.intrusion)

            case .expected:
                guard let presenceID = client.notices
                    .first(where: { $0.noticeID == command.noticeID })?.presenceID
                else {
                    throw HawkEyeClientError.transport(
                        "That notice is no longer open on the phone."
                    )
                }
                try await client.approvePresence(presenceID)
                client.dismissNotice(command.noticeID)
            }

            outcome = WatchOutcome(
                commandID: command.commandID,
                noticeID: command.noticeID,
                action: command.action,
                disposition: .recorded,
                recordedAt: Date()
            )
        } catch {
            outcome = WatchOutcome(
                commandID: command.commandID,
                noticeID: command.noticeID,
                action: command.action,
                disposition: .failed,
                failureReason: (error as? LocalizedError)?.errorDescription
                    ?? "The hub did not take it."
            )
            // The command ID stays in the handled set even though this failed.
            //
            // Retrying is the watch's job and it issues a fresh ID to do it, so
            // nothing is lost by keeping this one. Dropping it would be worse
            // than useless: WatchConnectivity delivers at least once, so a
            // command whose hub call succeeded but whose reply was lost would
            // be re-delivered, find itself unhandled, and raise a second
            // incident nobody asked for.
        }

        publish()
    }
}
