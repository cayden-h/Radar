import Foundation

/// The whole demo, on the wrist, with no phone and no hub.
///
/// It publishes the same `WatchSnapshot` the phone publishes, so the three
/// screens cannot tell the difference and there is no scripted branch anywhere
/// in a view. The script is the timing budget from the root `CLAUDE.md`, played
/// slower than real time only where a person needs a beat to read something.
///
/// Every frame it produces is marked `simulated`, so nothing here can be
/// mistaken on stage for something a lens saw.
@MainActor
final class MockWatchFeed: WatchFeed {

    /// How long after launch the shutter is granted and the shield starts moving.
    static let grantAfter: TimeInterval = 6
    /// How long the servo takes to clear the lens.
    static let travelDuration: TimeInterval = 0.4
    /// How long after the shield opens the camera's first sentence lands.
    static let narrationAfter: TimeInterval = 1.8
    /// How long the hub takes to acknowledge a command.
    static let acknowledgementDelay: Duration = .milliseconds(900)

    private static let room = "Living room"

    private var onSnapshot: (@MainActor (WatchSnapshot) -> Void)?
    private var loop: Task<Void, Never>?
    private var startedAt = Date()

    /// Authored here exactly as `PhoneWatchRelay` authors it, because the watch
    /// must not be able to tell the two apart.
    private var outcome: WatchOutcome?

    /// Rendered once. Re-rendering it every tick would churn the image and
    /// change the snapshot's bytes on every frame, which would defeat the
    /// phone's change gate if this ever ran there.
    private lazy var stillFrame: Data? = SimulatedCameraFrame.jpeg(room: Self.room)

    func start(
        onSnapshot: @escaping @MainActor (WatchSnapshot) -> Void,
        onReachability: @escaping @MainActor (Bool) -> Void
    ) {
        self.onSnapshot = onSnapshot
        startedAt = Date()
        onReachability(true)

        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                self.publish()
                try? await Task.sleep(for: .milliseconds(250))
            }
        }
    }

    func send(_ command: WatchCommand) {
        outcome = WatchOutcome(
            commandID: command.commandID,
            noticeID: command.noticeID,
            action: command.action,
            disposition: .pending
        )
        publish()

        Task { [weak self] in
            try? await Task.sleep(for: Self.acknowledgementDelay)
            guard let self else { return }
            self.outcome = WatchOutcome(
                commandID: command.commandID,
                noticeID: command.noticeID,
                action: command.action,
                disposition: .recorded,
                recordedAt: Date()
            )
            self.publish()
        }
    }

    // MARK: The script

    private func publish() {
        let elapsed = Date().timeIntervalSince(startedAt)
        onSnapshot?(
            WatchSnapshot(
                generatedAt: Date(),
                hubLinked: true,
                hubName: "Chestnut",
                shield: shield(at: elapsed),
                notice: notice(at: elapsed),
                outcome: outcome,
                incidentOpen: outcome?.action == .startIncident
                    && outcome?.disposition == .recorded
            )
        )
    }

    private func shield(at elapsed: TimeInterval) -> ShieldStatus {
        let attestation = Provenance(
            // A stub servo, and it says so. Naming this `servoGPIO` would let a
            // demo with no hardware attached present as one with hardware
            // attached, which is the whole reason the two sources are separate.
            source: .servoStub,
            producer: "agents/shutter",
            ansName: "shutter.hawkeye.invalid",
            detail: "Servo position attested against the nonce shutter itself issued.",
            sourceClass: .derived,
            simulated: true
        )
        let grantAt = startedAt.addingTimeInterval(Self.grantAfter)

        if elapsed < Self.grantAfter {
            return ShieldStatus(state: .closed, changedAt: startedAt, commandedAngle: 0,
                                provenance: attestation)
        }
        if elapsed < Self.grantAfter + Self.travelDuration {
            return ShieldStatus(state: .opening, changedAt: grantAt, commandedAngle: 90,
                                grantNonce: "nonce-7f3a91", provenance: attestation)
        }
        return ShieldStatus(
            state: .open,
            changedAt: grantAt.addingTimeInterval(Self.travelDuration),
            commandedAngle: 90,
            grantNonce: "nonce-7f3a91",
            provenance: attestation
        )
    }

    private func notice(at elapsed: TimeInterval) -> WatchNotice? {
        let due = Self.grantAfter + Self.travelDuration + Self.narrationAfter
        guard elapsed >= due else { return nil }
        return WatchNotice(
            noticeID: "ntc-p4",
            // The camera's own first sentence. Build, clothing, and what the
            // person is doing. It does not name them and does not claim a match
            // against any database, because `agents/vision` has neither.
            narration: "A person in a dark jacket is standing just inside the "
                + "living room, carrying something in their right hand.",
            room: Self.room,
            raisedAt: startedAt.addingTimeInterval(due),
            stillFrame: stillFrame,
            presenceID: "p4",
            simulated: true
        )
    }
}
