import Foundation
import Observation

/// The scripted client. Everything the live client does, with no hub, no Pi and
/// no network.
///
/// This is not a stub that returns empty arrays. It runs the full demo: the
/// household drifting through the house, a detection landing with nobody
/// pressing anything, and then, once a human taps, a 911 call with a two-way
/// transcript, instructions arriving alongside it, and the ANS verification
/// feed including **a claim that is refused.**
///
/// Two scenarios, selected by `Config.mockScenario`, sharing one sensor loop
/// and one detection timer:
///
/// - `.burglary`, the default. A fourth presence walks into the living room.
///   It is unconfirmed until respiration is acquired, then becomes a confirmed
///   person the system did not expect, and routes room to room toward the
///   resident. Two tracked presences, different rooms, both moving.
///
///   **Unexpected is roster plus device association**, settled 2026-09-19 and
///   specified in `agents/CLAUDE.md` and `docs/research/identity.md`: three
///   presences, two registered residents, two resident phones associated with
///   the network, so one body with no corresponding device. The household is
///   configuration, not a discovery problem, and this is a second modality
///   rather than a second view of the CSI stream.
/// - `.fire`. The child's breathing signature in the second bedroom stops
///   being resolvable while carbon monoxide climbs, and `respiration_lost_s`
///   counts from the last signature and does not reset. The claim is that we
///   had a signature and no longer have one, never that anyone stopped
///   breathing: shallow breathing degrades to exactly the same reading.
///
/// The detection raises an alert, never a call. Hawk Eye does not dial 911 on
/// its own.
///
/// Everything it emits is shaped exactly like `app/backend`'s wire format, built
/// out of the same `Codable` types the live client decodes into, so the views
/// cannot tell the difference and neither can a code reader looking for a
/// demo-only branch inside the UI. There isn't one.
@MainActor
@Observable
final class MockHawkEyeClient: HawkEyeClienting {

    private(set) var interior = InteriorState()
    private(set) var incident: Incident?
    private(set) var transcript: [TranscriptLine] = []
    private(set) var instructions: [Instruction] = []
    private(set) var verifications: [VerificationResult] = []
    private(set) var notices: [Notice] = []
    private(set) var hello: HubHello?
    private(set) var link: LinkState = .offline
    private(set) var missedFrames = false

    /// The mock's camera thumbnail.
    ///
    /// Rebuilt from `SimulatedCameraFrame` rather than stored, so it tracks the
    /// shield: closed lens, no frame, which is the honest answer rather than a
    /// grey rectangle. `source` is `.ruviewSim`, so `Provenance.simulated` is
    /// true and every view draws the SIMULATED marker off the data rather than
    /// off a branch on `Config.useMocks`.
    var cameraFrame: CameraFrame? {
        guard shieldStatus().state == .open,
              let jpeg = SimulatedCameraFrame.jpeg(room: Config.cameraRoom)
        else { return nil }
        return CameraFrame(
            jpeg: jpeg,
            capturedAt: Date(),
            source: .ruviewSim,
            live: true,
            room: Config.cameraRoom
        )
    }

    /// Nil, always. There is no socket to stream from on the mock path, and the
    /// view falls back to `cameraFrame` above.
    var cameraStreamURL: URL? { nil }
    private(set) var household: [HouseholdMember] = []
    private(set) var unclaimedDevices: [ObservedDevice] = [MockHawkEyeClient.seededVisitorDevice]

    /// The resident's leg of the bridge. `.watching` at rest and at the start
    /// of every call; nothing in this file ever moves it toward `.fullVoice`
    /// except `setParticipationMode`/`takeOver`, which are only ever called
    /// from a human-initiated control per `ParticipationMode`'s doc.
    private(set) var participationMode: ParticipationMode = .watching

    /// Mirrors `incident?.callState`, `.notPlaced` with nothing open, so a
    /// view can ask this directly instead of unwrapping `incident` first.
    var callState: CallState { incident?.callState ?? .notPlaced }

    /// Presences vouched for this session only. Nothing here persists across
    /// `disconnect()`/`resolve()`, which is the point: "this is expected" is a
    /// session-scoped fact, unlike remembering a visitor.
    @ObservationIgnored private var approvedPresences: Set<String> = []

    @ObservationIgnored private var sensorLoop: Task<Void, Never>?
    @ObservationIgnored private var scriptTask: Task<Void, Never>?
    @ObservationIgnored private var detectionTask: Task<Void, Never>?

    /// Drives the scripted loss of a breathing signature. Once this is set the
    /// mock keeps reporting the presence with no signature and
    /// `respiration_lost_s` counts from the last one, because the elapsed time
    /// since the last signature is the answer a dispatcher needs and it must
    /// not reset.
    @ObservationIgnored private var respirationLostAt: Date?

    /// Drives the scripted entry. Once this is set a fourth presence exists in
    /// the living room, and the seconds since it decide everything about that
    /// presence: unconfirmed at first, then a confirmed person the system did
    /// not expect, then a track moving room to room toward the resident.
    @ObservationIgnored private var enteredAt: Date?

    /// Set once the burglary notice has been raised, so dismissing it from the
    /// UI does not make `raiseNoticeIfDue` fire again on the next tick. The
    /// array being non-empty is not a fit signal for "already raised": a
    /// dismissal empties it, and the sensor loop runs at 4 Hz.
    @ObservationIgnored private var hasRaisedNotice = false

    /// When this connection opened. The resting shield's `changedAt` is
    /// measured from here rather than from `.distantPast`, so the Idle screen
    /// says something true instead of "55 years ago".
    @ObservationIgnored private var connectedAt = Date()

    @ObservationIgnored private var tick: Double = 0
    @ObservationIgnored private var lineCounter = 0

    private static let siteID = "site-demo-01"
    private static let address = "1872 Ridgeview Lane, Blacksburg VA 24060"

    /// The one unclaimed device the mock seeds: the phone that walked in with
    /// the intruder. Present from the start so "Remember this visitor" has a
    /// binding candidate to offer without waiting on any network path that
    /// does not exist here.
    private static let seededVisitorDevice = ObservedDevice(
        deviceID: "obs-visitor",
        fingerprint: "a4:3c:91:0d:7e:22",
        firstSeenAt: Date(),
        provenance: Provenance(
            source: .ruviewSim,
            producer: "master/simulated",
            ansName: nil,
            detail: "association table, simulated; no router integration exists yet",
            sourceClass: .simulated,
            simulated: true
        )
    )

    // MARK: Connect

    func connect(to hub: Hub) async throws {
        disconnect()
        connectedAt = Date()
        link = .connecting
        try? await Task.sleep(for: .milliseconds(320))
        // The same `hello` frame the hub sends first on every connection.
        hello = HubHello(
            hubName: hub.name,
            hubANSName: hub.ansName ?? "hub.hawkeye.invalid",
            mode: "simulated",
            streamProtocolVersion: 1,
            activeIncidentID: nil,
            replayFromSeq: nil
        )
        link = .live
        PairingStore.remember(hub.id)
        startSensorLoop()
        startDetectionTimer()
    }

    func disconnect() {
        sensorLoop?.cancel(); sensorLoop = nil
        scriptTask?.cancel(); scriptTask = nil
        detectionTask?.cancel(); detectionTask = nil
        respirationLostAt = nil
        enteredAt = nil
        hasRaisedNotice = false
        incident = nil
        transcript = []
        instructions = []
        verifications = []
        notices = []
        hello = nil
        link = .offline
        household = []
        unclaimedDevices = [MockHawkEyeClient.seededVisitorDevice]
        approvedPresences = []
        participationMode = .watching
    }

    // MARK: Household

    /// Vouches for a presence for this session only. Nothing is written to
    /// `household`: `approvePresence` and `rememberVisitor` are deliberately
    /// different actions, and only the latter persists.
    func approvePresence(_ presenceID: String) async throws {
        approvedPresences.insert(presenceID)
    }

    func rememberVisitor(name: String, kind: HouseholdMember.Kind, deviceID: String?) async throws {
        var devices: [KnownDevice] = []
        if let deviceID, let observed = unclaimedDevices.first(where: { $0.id == deviceID }) {
            devices.append(
                KnownDevice(
                    deviceID: observed.deviceID,
                    fingerprint: observed.fingerprint,
                    label: nil,
                    addedAt: Date(),
                    lastSeenAt: Date()
                )
            )
        }
        let member = HouseholdMember(
            memberID: "mem-\(household.count + 1)",
            name: name,
            kind: kind,
            devices: devices,
            addedAt: Date(),
            addedBy: .approval,
            provenance: Provenance(
                source: .userInput,
                producer: "app/ios",
                ansName: nil,
                detail: nil,
                sourceClass: .human,
                simulated: false
            ),
            isRecognisable: !devices.isEmpty
        )
        household.append(member)
        if let deviceID {
            unclaimedDevices.removeAll { $0.id == deviceID }
        }
    }

    func forgetMember(_ memberID: String) async throws {
        guard let member = household.first(where: { $0.id == memberID }) else { return }
        household.removeAll { $0.id == memberID }
        // Their devices become unclaimed again, matching the live contract.
        for device in member.devices {
            unclaimedDevices.append(
                ObservedDevice(
                    deviceID: device.deviceID,
                    fingerprint: device.fingerprint,
                    firstSeenAt: device.addedAt,
                    provenance: MockHawkEyeClient.seededVisitorDevice.provenance
                )
            )
        }
    }

    func refreshHousehold() async {
        // Nothing to fetch: the mock's household is already the ground truth
        // in process, and there is no round trip that could be behind it.
    }

    // MARK: Commands

    func raiseIncident(_ type: IncidentType) async throws {
        guard incident == nil else { return }
        detectionTask?.cancel()
        open(type, raisedBy: .user)
    }

    func dismissIncident() {
        scriptTask?.cancel(); scriptTask = nil
        respirationLostAt = nil
        enteredAt = nil
        incident = nil
        transcript = []
        instructions = []
        verifications = []
        participationMode = .watching
    }

    func dismissNotice(_ id: String) {
        notices.removeAll { $0.id == id }
    }

    func sendContext(_ text: String) async throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let open = incident else { return }
        let note = ContextNote(
            noteID: "note-\(open.contextNotes.count + 1)",
            incidentID: open.id,
            text: trimmed,
            at: Date(),
            provenance: Provenance(
                source: .userInput,
                producer: "app/ios",
                ansName: nil,
                detail: nil,
                sourceClass: .human,
                simulated: false
            ),
            deliveredToCaller: true
        )
        incident?.contextNotes.append(note)

        // What the resident types is a human statement, and `caller` attributes
        // it as one rather than asserting it as something a sensor observed.
        try? await Task.sleep(for: .milliseconds(700))
        appendTranscript(.caller, "The resident reports: \(trimmed)")
    }

    /// Switches the resident's leg. Scripted rather than networked, same as
    /// everything else here, but it is a real state transition: a view
    /// reading `participationMode` afterward sees it change, and the system
    /// line below is the same "announce every transition" behaviour
    /// `agents/caller` owes on the live path per `app/CLAUDE.md`.
    func setParticipationMode(_ mode: ParticipationMode) async throws {
        guard mode != participationMode else { return }
        participationMode = mode
        guard incident != nil else { return }
        appendTranscript(.system, Self.transitionAnnouncement(for: mode))
    }

    /// `TAKE OVER`. Always a human action — the UI holds this for 1.5s before
    /// calling it — so it goes straight to `.fullVoice` rather than working
    /// through whisper first.
    func takeOver() async throws {
        try await setParticipationMode(.fullVoice)
    }

    /// "Announce every transition", per `app/CLAUDE.md`: a mode change nobody
    /// narrated is the failure mode on a call built around not surprising a
    /// dispatcher with an unexplained voice.
    private static func transitionAnnouncement(for mode: ParticipationMode) -> String {
        switch mode {
        case .watching: "The resident has gone quiet again. Transcript only."
        case .whisper: "The resident is joining but cannot hear you. They are hiding and will respond by voice only."
        case .fullVoice: "The resident is joining. They can hear you."
        }
    }

    // MARK: Sensor loop

    /// 4 Hz. Enough for the blobs to drift and breathe smoothly, cheap enough
    /// to leave running for the length of a judging session.
    private func startSensorLoop() {
        sensorLoop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                self.tick += 0.25
                self.interior = self.state(at: self.tick)
                self.raiseNoticeIfDue()
                try? await Task.sleep(for: .milliseconds(250))
            }
        }
    }

    /// Builds an `InteriorState` exactly as the hub would send it, including the
    /// server-decided `presence.state` the client now trusts.
    private func state(at t: Double) -> InteriorState {
        let lost = respirationLostAt
        let lostFor = lost.map { Date().timeIntervalSince($0) }
        let plan = Floorplan.home

        // The baseline household, and it is the same household in both
        // scenarios. p1: the resident, awake and moving between the main bedroom
        // and the hallway, which is the left-hand half of the apartment.
        // p2: a child in the second bedroom, whose breathing signature goes
        // missing once the fire script fires.
        // p3: a curtain over the vent above the dryer in the laundry, which is
        // the case the system must not report as a person.
        //
        // p3 is on screen the whole time the burglary runs, so the view shows a
        // confirmed unexpected person and an unconfirmed perturbation at once
        // and they do not look alike. That contrast is the argument: the system
        // is not calling everything that moves a person.
        let p1Zone = (sin(t * 0.06) > 0) ? "main_bedroom" : "hallway"

        let simulatedCSI = Provenance(
            source: .ruviewSim,
            producer: "sensor/",
            ansName: "sensor.hawkeye.invalid",
            detail: "Synthetic CSI. Nothing here was measured.",
            sourceClass: .simulated,
            simulated: true
        )

        let p1 = Presence(
            presenceID: "p1",
            state: .personMoving,
            position: Self.position(plan, p1Zone),
            moving: true,
            confidence: clamp(0.86 + 0.06 * sin(t * 0.4)),
            vitals: Vitals(respiration: .breathing, breathingBpm: 15,
                           heartBpm: 72, personConfidence: 0.91),
            presenceClass: .adult,
            classBasis: "respiration_rate",
            expected: true,
            respirationLostS: nil,
            provenance: simulatedCSI
        )

        // The signature goes, the person does not. The personhood verdict must
        // not waver just because the radio stopped resolving breathing: shallow
        // breathing, breath-holding and range limits all read the same way, so
        // the confidence drops rather than the verdict flipping.
        let p2 = Presence(
            presenceID: "p2",
            state: lost == nil ? .personMoving : .personUnresponsive,
            position: Self.position(plan, "second_bedroom"),
            moving: lost == nil,
            confidence: clamp(0.79 + 0.05 * sin(t * 0.31 + 1.2)),
            vitals: Vitals(respiration: lost == nil ? .breathing : .noSignature,
                           breathingBpm: lost == nil ? 24 : nil,
                           heartBpm: nil,
                           personConfidence: lost == nil ? 0.84 : 0.71),
            presenceClass: .child,
            classBasis: "respiration_rate",
            expected: true,
            respirationLostS: lostFor,
            provenance: simulatedCSI
        )

        // No respiration signature. This is the curtain, and it must never be
        // drawn as a person.
        let p3 = Presence(
            presenceID: "p3",
            state: .unconfirmed,
            position: Self.position(plan, "laundry"),
            moving: true,
            confidence: clamp(0.34 + 0.08 * sin(t * 0.9 + 2.3)),
            vitals: Vitals(respiration: .noSignature, breathingBpm: nil,
                           heartBpm: nil, personConfidence: 0.12),
            presenceClass: .unknown,
            classBasis: nil,
            expected: true,
            respirationLostS: nil,
            provenance: simulatedCSI
        )

        // p4: the intruder, and only once the entry has happened. Everything
        // about it is a function of how long it has been inside.
        var presences = [p1, p2, p3]
        if let entry = enteredAt {
            presences.append(
                Self.intruder(since: Date().timeIntervalSince(entry),
                              plan: plan, t: t, provenance: simulatedCSI)
            )
        }

        return InteriorState(
            siteID: Self.siteID,
            capturedAt: Date(),
            sensorIdentity: "sensor.hawkeye.invalid",
            calibration: Calibration(baselineAgeS: 412 + t, healthy: true,
                                     note: "Rolling percentile baseline, slow adaptation."),
            presences: presences,
            // Simulated, and labelled in the data itself rather than in a
            // comment. `demo-trigger` is the literal string the honesty rule
            // requires, and the UI reads the derived flag to caption it.
            environment: EnvironmentReading(
                coPpm: lost == nil ? 4 : 186,
                smokeDetected: false,
                confidence: 0.88,
                provenance: Provenance(
                    source: .demoTrigger,
                    producer: "agents/master",
                    ansName: "master.hawkeye.invalid",
                    detail: "No gas sensor was purchased. An MQ-7 drops in behind this.",
                    sourceClass: .simulated,
                    simulated: true
                )
            ),
            floorplan: plan,
            shield: shieldStatus(),
            activeIncidentID: incident?.id
        )
    }

    /// The shield, as `agents/shutter` would attest it.
    ///
    /// Driven off the same entry clock as the intruder, so the whole timing
    /// budget in the root `CLAUDE.md` plays out on screen: the grant is issued
    /// about 800ms after `intruder` returns its verdict, and the servo takes
    /// about 400ms to clear the lens.
    ///
    /// `Config.mockShutterRefuses` runs the other path, which is the one worth
    /// having: the camera never opens and the resident is told that something
    /// asked to open it and could not prove it was allowed to.
    private func shieldStatus() -> ShieldStatus {
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

        guard let entry = enteredAt else {
            return ShieldStatus(state: .closed, changedAt: connectedAt, commandedAngle: 0,
                                provenance: attestation)
        }

        let grantAt = entry.addingTimeInterval(Config.mockIntruderIdentifiedAfter + 0.8)
        let openAt = grantAt.addingTimeInterval(0.4)
        let now = Date()

        guard now >= grantAt else {
            return ShieldStatus(state: .closed, changedAt: connectedAt, commandedAngle: 0,
                                provenance: attestation)
        }

        if Config.mockShutterRefuses {
            return ShieldStatus(
                state: .refused,
                changedAt: grantAt,
                // The shield never moved, so the commanded angle is still the
                // resting one. A refusal that reported 90 would be claiming a
                // move that did not happen.
                commandedAngle: 0,
                grantNonce: "nonce-7f3a91",
                refusalCode: "lookalike_ansname",
                refusalReason: "The grant was signed by a key that is not the one "
                    + "master publishes in its trust card.",
                provenance: attestation
            )
        }

        if now < openAt {
            return ShieldStatus(state: .opening, changedAt: grantAt, commandedAngle: 90,
                                grantNonce: "nonce-7f3a91", provenance: attestation)
        }

        return ShieldStatus(state: .open, changedAt: openAt, commandedAngle: 90,
                            grantNonce: "nonce-7f3a91", provenance: attestation)
    }

    private func clamp(_ value: Double) -> Double { min(max(value, 0.05), 0.98) }

    /// A zone centroid in metres. Not a localization claim: the agents reason
    /// over the zone, and these coordinates exist so the view has somewhere to
    /// draw.
    private static func position(_ plan: Floorplan, _ zone: String) -> Position {
        guard let room = plan.room(named: zone) else {
            return Position(zone: zone, x: plan.widthM / 2, y: plan.depthM / 2, zoneConfidence: 0.4)
        }
        let b = room.bounds()
        return Position(zone: zone, x: b.midX, y: b.midY, zoneConfidence: 0.86)
    }

    // MARK: The intruder

    /// The fourth presence, built entirely from how many seconds it has been in
    /// the building.
    ///
    /// Three beats, and they are the burglary demo:
    ///
    /// 1. **Entry.** A new presence appears in the living room with no
    ///    respiration signature yet, so `unconfirmed`, exactly like the curtain
    ///    in the laundry. The system does not call it a person before it can
    ///    tell.
    /// 2. **Identified.** Respiration is acquired, so it is a person, and the
    ///    device correlation says nobody's phone came in with them. It becomes
    ///    a confirmed person with `expected: false`: someone is in the building
    ///    and no enrolled device accounts for them.
    /// 3. **Approach.** It routes room to room toward the resident, its
    ///    position interpolated between zone centroids so it visibly moves.
    ///
    /// Nothing here dials. The detection is an alert and the incident waits on
    /// a human tap, per `app/CLAUDE.md`.
    private static func intruder(
        since elapsed: Double,
        plan: Floorplan,
        t: Double,
        provenance: Provenance
    ) -> Presence {
        let identified = elapsed >= Config.mockIntruderIdentifiedAfter
        let position = route(plan: plan, since: elapsed)

        // Confidence climbs as the track accumulates frames, then holds. It is
        // never pinned at 1: the system does not become certain about a person
        // by deciding it does not like them.
        let settle = min(1, elapsed / 9)
        let confidence = 0.30 + 0.52 * settle + 0.04 * sin(t * 0.8 + 0.4)

        return Presence(
            presenceID: "p4",
            state: identified ? .personMoving : .unconfirmed,
            position: position,
            moving: true,
            confidence: min(max(confidence, 0.05), 0.92),
            vitals: Vitals(
                respiration: identified ? .breathing : .noSignature,
                breathingBpm: identified ? 21 : nil,
                heartBpm: nil,
                personConfidence: identified ? 0.88 : 0.19
            ),
            presenceClass: identified ? .adult : .unknown,
            classBasis: identified ? "respiration_rate" : nil,
            // The orthogonal axis, and the only presence in the apartment that
            // carries it.
            //
            // `agents/intruder` decides it by **roster plus device
            // association**, settled 2026-09-19. The rule is written down in
            // `agents/CLAUDE.md` and `docs/research/identity.md` and this is
            // the same arithmetic:
            //
            //   CSI:        3 distinct presences
            //   Roster:     2 registered residents (configuration, not discovery)
            //   Associated: 2 resident phones on the network
            //   ------------------------------------------------------------
            //               1 body with no corresponding device
            //
            // The household is known rather than discovered, so this is not
            // "an unfamiliar MAC appeared". The router's association table is
            // a genuinely independent modality, not a second view of the CSI
            // stream, which is what makes it corroboration at all.
            //
            // It consumes the personhood verdict first: a perturbation with no
            // respiration signature is a curtain, not an intruder, and calling
            // police on a curtain is the failure mode this is designed against.
            //
            // We do not recognise individuals and the app never presents this
            // as though we do. Name the holes rather than pretending there are
            // none: a resident who left their phone in the car, a guest, a
            // burglar carrying a phone that never associates. That is why this
            // surfaces as a notification a human acts on rather than as
            // anything that dials.
            expected: identified ? false : nil,
            respirationLostS: nil,
            provenance: provenance
        )
    }

    /// Walks `Config.mockIntruderRoute`, dwelling in each zone and interpolating
    /// between centroids in between.
    ///
    /// The reported `zone` flips at the midpoint of a leg, so the roster says
    /// the room the presence is actually closer to. The interpolated `x`/`y` is
    /// what makes the blob move across the floorplan rather than teleport, and
    /// it is a drawing position rather than a localization claim, same as every
    /// other centroid in this file.
    private static func route(plan: Floorplan, since elapsed: Double) -> Position {
        let legs = Config.mockIntruderRoute
        let travel = Config.mockIntruderTravelSeconds
        var cursor = 0.0

        for (index, leg) in legs.enumerated() {
            if elapsed < cursor + leg.dwellS || index == legs.count - 1 {
                return position(plan, leg.zone)
            }
            cursor += leg.dwellS

            let next = legs[index + 1]
            if elapsed < cursor + travel {
                let progress = (elapsed - cursor) / travel
                let from = position(plan, leg.zone)
                let to = position(plan, next.zone)
                return Position(
                    zone: progress < 0.5 ? leg.zone : next.zone,
                    x: from.x + (to.x - from.x) * progress,
                    y: from.y + (to.y - from.y) * progress,
                    // In transit between two enrolled zones, which is exactly
                    // when the zone answer is least certain. Say so.
                    zoneConfidence: 0.52
                )
            }
            cursor += travel
        }

        return position(plan, legs[legs.count - 1].zone)
    }

    // MARK: The notice

    /// The burglary scenario's one notice.
    ///
    /// Scripted against the same elapsed-time constants the presence generator
    /// uses, so it lands `Config.mockNoticeHoldSeconds` after the intruder
    /// acquires respiration, which is what the hub's detector does given the
    /// same frames. The mock does not re-implement the rule.
    ///
    /// Guarded by `hasRaisedNotice` rather than `notices.isEmpty`: dismissing
    /// the notice from the UI (`dismissNotice`) empties `notices`, and this
    /// runs every 250ms off the sensor loop, so an emptiness check would raise
    /// it right back on the very next tick. Once raised, it stays raised for
    /// the rest of this entry, same as `enteredAt` staying set once the
    /// intruder is inside.
    private func raiseNoticeIfDue() {
        guard Config.mockScenario == .burglary else { return }
        guard !hasRaisedNotice else { return }
        guard let entry = enteredAt else { return }
        let elapsed = Date().timeIntervalSince(entry)
        let due = Config.mockIntruderIdentifiedAfter + Config.mockNoticeHoldSeconds
        guard elapsed >= due else { return }
        guard let intruder = interior.presences.first(where: \.isUnexpected) else { return }
        // Approved this session: the resident already vouched for them, so the
        // notice this branch exists to raise would just be re-litigating a
        // question that is settled for the rest of this connection.
        guard !approvedPresences.contains(intruder.presenceID) else { return }

        // The floorplan's authored name, read directly. `roomName(of:)`
        // lowercases for spoken transcript lines, and reconstructing the
        // original casing from that is lossy: it only works for names whose
        // capitals happen to be leading. One place decides what a room is
        // called, and it is the plan.
        let room = interior.floorplan.room(named: intruder.zone)?.name ?? intruder.zone

        // The camera's own first sentence. **This is the notification.** A
        // generic "motion detected" on a wrist throws away the entire camera
        // pivot, so the mock scripts a real sentence rather than a placeholder.
        //
        // It describes build, clothing and what the person is doing, and stops
        // there. It does not name them and it does not claim a match against
        // any database, because `agents/vision` has neither.
        let narration = "A person in a dark jacket is standing just inside the "
            + "\(room.lowercased()), carrying something in their right hand."

        // Nil when the shield refused, and that is the honest answer: there is
        // no frame because the camera never opened. The notice still goes out.
        let frame = shieldStatus().state == .open
            ? SimulatedCameraFrame.jpeg(room: room).map {
                NoticeFrame(jpeg: $0, capturedAt: Date(), room: room)
            }
            : nil

        hasRaisedNotice = true
        notices.insert(
            Notice(
                noticeID: "ntc-\(intruder.presenceID)",
                severity: .attention,
                title: "Unexpected person",
                body: "Not accounted for. \(room).",
                zone: intruder.zone,
                room: room,
                presenceID: intruder.presenceID,
                raisedAt: Date(),
                provenance: Provenance(
                    source: .agentInference,
                    producer: "agents/intruder",
                    ansName: "intruder.hawkeye.invalid",
                    detail: "presence surplus against roster and device association",
                    sourceClass: .derived,
                    simulated: false
                ),
                narration: narration,
                stillFrame: frame
            ),
            at: 0
        )
    }

    // MARK: The detection

    /// The detection fires with nobody pressing anything, and it raises an
    /// **alert, not a call.**
    ///
    /// Hawk Eye does not dial 911 on its own; a human tap releases
    /// `agents/caller`. What the detection buys is an informed tap.
    ///
    /// For `.fire`: the presence keeps its position, its respiration goes to
    /// `no_signature`, and `respirationLostS` starts counting from the last
    /// resolvable signature. The roster says which room has stopped answering,
    /// and where the rest of the household is, before the resident has touched
    /// anything.
    ///
    /// For `.burglary`: a new presence appears in the living room, is
    /// identified as a person no enrolled device accounts for, and starts
    /// moving through the apartment. **It is a notification, not an
    /// escalation:** nothing dials and nothing raises an incident on its own.
    /// By the time the resident taps Burglary, the dispatcher can be told how
    /// many people are inside, which rooms they are in, and which one is not
    /// accounted for.
    ///
    /// One timer, one sensor loop, both scenarios. The switch is
    /// `Config.mockScenario` and it is the only one.
    private func startDetectionTimer() {
        guard let delay = Config.mockDetectionAfter else { return }
        let scenario = Config.mockScenario
        detectionTask = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard let self, !Task.isCancelled, self.incident == nil else { return }
            switch scenario {
            case .fire:
                // Debounce, as `agents/people` does: one window without a
                // signature is not a lost signature. A system that alarms the
                // moment a breathing estimate goes marginal is worse than no
                // system, because every such alarm teaches the household to
                // ignore the next one.
                try? await Task.sleep(for: Config.mockRespirationLostDelay)
                guard !Task.isCancelled, self.incident == nil else { return }
                self.respirationLostAt = Date()
            case .burglary:
                // No separate debounce here. The debounce *is* the respiration
                // acquisition: for the first few seconds the presence is
                // unconfirmed, and it is only called a person once there is a
                // breathing signature to say so.
                self.enteredAt = Date()
            }
        }
    }

    // MARK: The call

    private func open(_ type: IncidentType, raisedBy: IncidentOrigin) {
        // Tapping a button before the scripted detection has fired starts the
        // matching sensor story, so the call is never talking about a house
        // where nothing is happening.
        if type == .fire, respirationLostAt == nil { respirationLostAt = Date() }
        if type == .burglary, enteredAt == nil { enteredAt = Date() }
        transcript = []
        instructions = []
        verifications = []
        lineCounter = 0
        participationMode = .watching
        incident = Incident(
            incidentID: "inc-0001",
            siteID: Self.siteID,
            incidentType: type,
            status: .raised,
            raisedBy: raisedBy,
            raisedAt: Date(),
            updatedAt: Date(),
            address: Self.address,
            callState: .notStarted
        )
        scriptTask?.cancel()
        scriptTask = Task { [weak self] in await self?.runCall(type) }
    }

    /// The scripted incident.
    ///
    /// Note what `caller` does and does not say. It reports the room, the
    /// breathing rate, and how long it has been since a breathing signature was
    /// last resolvable, because those are verified claims from named agents,
    /// and it says the limit of that last one out loud in the same breath. It
    /// does not diagnose, it does not
    /// assert to the operator that the call is cryptographically verified, and
    /// when it does not know something it says so.
    private func runCall(_ type: IncidentType) async {
        switch type {
        case .burglary: await runBurglaryCall(type)
        case .fire: await runFireCall(type)
        }
    }

    private func runFireCall(_ type: IncidentType) async {
        // Verification runs before a word is spoken. That ordering is the
        // architecture: nothing crosses the human boundary unverified.
        await step(0.9) { self.emit(Self.assertedRespirationLost()) }
        await step(0.7) { self.emit(Self.attributedBiometrics()) }
        await step(0.8) { self.emit(Self.corroborationEnvironment()) }
        await step(1.0) {
            // The refusal. An impostor at a lookalike ANSName made a claim that
            // would have escalated the response, and it was discarded.
            self.emit(Self.discardedImpostor())
            self.setStatus(.classified)
            self.incident?.classification = Self.classification(for: type)
        }

        await step(1.0) { self.setCall(.dialing) }
        await step(2.0) { self.setCall(.connected); self.setStatus(.onCall) }

        await step(0.6) {
            self.appendTranscript(.operatorVoice, "911, what is the address of your emergency?")
        }
        await step(2.2) {
            self.appendTranscript(
                .caller,
                "This is an automated call from a monitoring system at \(Self.address). I am calling on behalf of the resident.",
                claimIDs: []
            )
        }
        await step(2.4) {
            self.appendInstruction(
                "Radar is on the line with 911. Stay on this screen.",
                origin: .systemStatus, urgent: false
            )
        }
        await step(1.4) {
            self.appendTranscript(.operatorVoice, "What is happening there?")
        }
        await step(2.4) {
            let seconds = self.respirationLostAt.map { Int(Date().timeIntervalSince($0)) } ?? 0
            self.appendTranscript(
                .caller,
                "I had a breathing signature from a person in the second bedroom \(seconds) seconds ago and I do not have one now. That is not the same as them having stopped breathing - I cannot resolve shallow breathing. Do not expect them to answer. Carbon monoxide in the building is elevated. One other adult is in the house, moving normally and still breathing.",
                claimIDs: ["clm-001", "clm-002", "clm-004"]
            )
        }
        await step(2.8) {
            self.appendTranscript(.operatorVoice, "Is anyone else in the building?")
        }
        await step(2.0) {
            // The discarded claim is not repeated to the operator. This is the
            // refusal being load-bearing rather than decorative.
            self.appendTranscript(
                .caller,
                "Two people, and one perturbation with no breathing signature in the laundry that I am not calling a person. A third occupant was reported to me by an agent I could not verify, so I am not repeating that claim.",
                claimIDs: ["clm-001", "clm-003"]
            )
        }
        await step(2.6) {
            self.appendInstruction(
                "Get out now. Do not collect anything, and do not go to the second bedroom. Tell the responders which room they are in.",
                origin: .relayedOperator, urgent: true
            )
        }
        await step(3.0) {
            self.appendTranscript(.operatorVoice, "I've dispatched units. They're about four minutes out. Can someone unlock the front door?")
            self.setStatus(.dispatched)
        }
        await step(1.6) {
            self.appendInstruction(
                "Units are on the way, about four minutes out. Unlock the front door if you can do that safely.",
                origin: .relayedOperator, urgent: true
            )
        }
        await step(2.2) {
            self.appendTranscript(.caller, "Understood. The resident has been told.")
        }
        await step(4.0) {
            self.appendInstruction(
                "Once you are out, stay out. Do not go back in for anyone or anything. If anything changes, type it in the box below and it goes straight to the dispatcher.",
                origin: .relayedOperator, urgent: false
            )
        }
        await step(5.0) {
            self.appendTranscript(.operatorVoice, "Stay on the line until they arrive.")
        }
        await step(18.0) {
            // The call ends when responders are on scene. `master` resolves the
            // incident and the screen stands down with it, exactly as the live
            // path does off a resolved incident event.
            self.appendTranscript(.system, "Responders on scene. Call ended.")
            self.setCall(.ended)
            self.resolve()
        }
    }

    /// The burglary script.
    ///
    /// The frame this whole project is built around is on screen behind this
    /// call: the intruder and the resident as two distinct tracked presences,
    /// in different rooms, both moving. The transcript's job is to get that
    /// frame said out loud to a dispatcher, in plain English, with each claim
    /// traceable to the agent that made it.
    ///
    /// Note what `caller` does not do. It does not describe the person, because
    /// CSI cannot and the system does not do recognition. It says "a person the
    /// household did not expect", which is the claim `agents/intruder` actually
    /// made. And it does not repeat the impostor's claim, which is the refusal
    /// being load-bearing rather than decorative.
    private func runBurglaryCall(_ type: IncidentType) async {
        await step(0.9) { self.emit(Self.assertedIntruder()) }
        await step(0.7) { self.emit(Self.attributedOccupancy()) }
        await step(1.0) {
            // The refusal. An impostor at a lookalike ANSName made a claim that
            // would have changed how police approach the building.
            self.emit(Self.discardedArmedClaim())
            self.setStatus(.classified)
            self.incident?.classification = Self.classification(for: type)
        }

        await step(1.0) { self.setCall(.dialing) }
        await step(2.0) { self.setCall(.connected); self.setStatus(.onCall) }

        await step(0.6) {
            self.appendTranscript(.operatorVoice, "911, what is the address of your emergency?")
        }
        await step(2.2) {
            self.appendTranscript(
                .caller,
                "This is an automated call from a monitoring system at \(Self.address). I am calling on behalf of the resident, who is inside.",
                claimIDs: []
            )
        }
        await step(2.0) {
            self.appendInstruction(
                "Radar is on the line with 911. This screen is silent: no sound, no vibration.",
                origin: .systemStatus, urgent: false
            )
        }
        await step(1.4) {
            self.appendTranscript(.operatorVoice, "What is happening there?")
        }
        // The frame that matters, said out loud.
        await step(2.4) {
            self.appendTranscript(
                .caller,
                "There are two people in the apartment, in different rooms, and both are moving. One of them is the resident, in the \(self.roomName(of: "p1")). The other walked in about \(self.secondsInside()) seconds ago and is now in the \(self.roomName(of: "p4")). Every phone this household has registered is on the home network and accounted for, and none of them is with that person.",
                claimIDs: ["clm-101", "clm-102"]
            )
        }
        await step(2.8) {
            self.appendTranscript(.operatorVoice, "Is anyone else in the building?")
        }
        await step(2.2) {
            self.appendTranscript(
                .caller,
                "A child is asleep in the second bedroom and is breathing normally. There is also one perturbation in the laundry with no breathing signature, which I am not calling a person: it is a curtain over the vent above the dryer and it has been there all evening.",
                claimIDs: ["clm-102"]
            )
        }
        await step(2.4) {
            self.appendTranscript(.operatorVoice, "Can you tell me what the person looks like?")
        }
        await step(2.4) {
            // The honesty rule, inside the call. The radio cannot do this and
            // the agent says so rather than inventing a description.
            self.appendTranscript(
                .caller,
                "No. This system senses movement and breathing through walls. It has no camera and no microphone, so I cannot describe anyone. I can tell you which room they are in and that they are moving.",
                claimIDs: []
            )
        }
        await step(2.6) {
            self.appendTranscript(.operatorVoice, "Understood. Tell the resident not to confront them, and to stay where they are and stay quiet.")
            self.setStatus(.dispatched)
        }
        await step(1.4) {
            self.appendInstruction(
                "Do not confront them. Stay where you are, stay quiet, and keep this screen dark.",
                origin: .relayedOperator, urgent: true
            )
        }
        await step(2.6) {
            self.appendTranscript(.operatorVoice, "Units are on the way, about six minutes out. Keep telling me where that person is.")
        }
        await step(1.6) {
            self.appendInstruction(
                "Police are on the way, about six minutes out. Radar is telling them which room the person is in, as it changes.",
                origin: .relayedOperator, urgent: true
            )
        }
        await step(3.0) {
            // The two-way loop: an operator question fans out to the sensing
            // agents and comes back in English seconds later. This is where ANS
            // is visibly doing work during the demo.
            // The last leg of the route puts the unexpected person in the same
            // room as the resident, which is the worst moment of the incident
            // and has to be said as such. Read both rooms off the frame that
            // just arrived rather than assuming they are still apart.
            let intruderRoom = self.roomName(of: "p4")
            let residentRoom = self.roomName(of: "p1")
            self.appendTranscript(
                .caller,
                intruderRoom == residentRoom
                    ? "They have moved into the \(intruderRoom), which is the room the resident is in. They are in the same room now."
                    : "They are still in the \(intruderRoom). The resident is in the \(residentRoom). Neither has left the room they are in.",
                claimIDs: ["clm-101", "clm-102"]
            )
        }
        await step(4.0) {
            self.appendInstruction(
                "If anything changes, type it in the box below. It goes straight to the dispatcher and is read out as your report.",
                origin: .systemStatus, urgent: false
            )
        }
        await step(5.0) {
            self.appendTranscript(.operatorVoice, "Stay on the line until officers are inside.")
        }
        await step(18.0) {
            self.appendTranscript(.system, "Officers on scene. Call ended.")
            self.setCall(.ended)
            self.resolve()
        }
    }

    /// The room a presence is in right now, read off the frame that just
    /// arrived rather than from a script constant, so the transcript cannot
    /// claim a room the map is not drawing.
    private func roomName(of presenceID: String) -> String {
        guard let presence = interior.presences.first(where: { $0.presenceID == presenceID })
        else { return "house" }
        let name = interior.floorplan.room(named: presence.zone)?.name ?? presence.zone
        return name.lowercased()
    }

    private func secondsInside() -> Int {
        guard let enteredAt else { return 0 }
        return max(0, Int(Date().timeIntervalSince(enteredAt)))
    }

    // MARK: Verification fixtures

    private static func trustIndex(
        integrity: Double?, identity: Double?
    ) -> TrustIndexScore {
        // Solvency, behavior and safety come back null rather than zero. A 0
        // that means "not implemented" and a 0 that means "scored zero" are
        // different facts, and the app must not conflate them.
        TrustIndexScore(
            integrity: integrity, identity: identity,
            solvency: nil, behavior: nil, safety: nil,
            unimplementedDimensions: ["solvency", "behavior", "safety"]
        )
    }

    private static func assertedRespirationLost() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-001",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-001",
                statement: "A presence in the second bedroom had a resolvable breathing signature and no longer has one. That is a lost signature, not a finding that breathing has stopped.",
                field: "people.respiration_lost",
                value: "6 s since the last resolvable signature",
                presenceID: "p2"
            ),
            agent: SourceAgent(
                name: "agents/people",
                ansName: "people.hawkeye.invalid",
                certificateVersion: "v1.4.2+sha256:9f1c...a30b",
                trustIndex: trustIndex(integrity: 0.94, identity: 0.97),
                recommendedProfile: .fiduciary
            ),
            decision: .asserted,
            reason: "Source is FIDUCIARY and every check passed. Spoken as an assertion the system stands behind.",
            checks: [
                VerificationCheck(name: "ans.resolve", passed: true,
                                  detail: "people.hawkeye.invalid resolved to the registered certificate."),
                VerificationCheck(name: "cert.version_binding", passed: true,
                                  detail: "Code fingerprint matches the version-bound certificate issued at registration."),
                VerificationCheck(name: "trust_index.profile", passed: true,
                                  detail: "Trust Index recommendedProfile = FIDUCIARY."),
            ],
            willBeSpoken: true
        )
    }

    private static func attributedBiometrics() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-002",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-002",
                statement: "The other adult occupant is moving normally, with a breathing signature at about 15 breaths a minute.",
                field: "people.respiration",
                value: "breathing, 15 bpm",
                presenceID: "p1"
            ),
            agent: SourceAgent(
                name: "agents/people",
                ansName: "people.hawkeye.invalid",
                certificateVersion: "v1.2.0+sha256:b310...77ca",
                trustIndex: trustIndex(integrity: 0.81, identity: 0.93),
                recommendedProfile: .transactional
            ),
            decision: .attributed,
            reason: "Source is TRANSACTIONAL. Relayed as a reported observation, attributed to the agent that made it.",
            checks: [
                VerificationCheck(name: "ans.resolve", passed: true,
                                  detail: "people.hawkeye.invalid resolved to the registered certificate."),
                VerificationCheck(name: "cert.version_binding", passed: true,
                                  detail: "Code fingerprint matches the certificate issued at registration."),
                VerificationCheck(name: "trust_index.profile", passed: true,
                                  detail: "Trust Index recommendedProfile = TRANSACTIONAL."),
            ],
            willBeSpoken: true
        )
    }

    private static func corroborationEnvironment() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-003",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-004",
                statement: "Carbon monoxide in the building is elevated at 186 parts per million.",
                field: "master.co_ppm",
                value: "186 ppm",
                presenceID: nil
            ),
            agent: SourceAgent(
                name: "agents/master",
                ansName: "master.hawkeye.invalid",
                certificateVersion: "v0.9.1+sha256:1ee4...c052",
                trustIndex: trustIndex(integrity: 0.62, identity: 0.9),
                recommendedProfile: .readOnly
            ),
            decision: .corroborationOnly,
            reason: "Source is READ_ONLY. Used as corroboration, never as the sole basis for a call.",
            checks: [
                VerificationCheck(name: "ans.resolve", passed: true,
                                  detail: "master.hawkeye.invalid resolved to the registered certificate."),
                VerificationCheck(name: "provenance.simulated", passed: true,
                                  detail: "Reading is labelled demo-trigger. No gas sensor exists and the claim says so."),
                VerificationCheck(name: "trust_index.profile", passed: true,
                                  detail: "Trust Index recommendedProfile = READ_ONLY."),
            ],
            willBeSpoken: true
        )
    }

    /// The refusal path, which is the submission. An impostor at a lookalike
    /// ANSName makes a claim that would have sent an armed response into a room
    /// where no sensor sees anybody.
    private static func discardedImpostor() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-005",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-005",
                statement: "A third adult has collapsed in the corridor outside the front door and has stopped breathing.",
                field: "people.respiration",
                value: "no respiration, building corridor",
                presenceID: nil
            ),
            agent: SourceAgent(
                name: "agents/people",
                ansName: "people.hawkeye-secure.invalid",
                certificateVersion: "v1.4.2+sha256:4d77...0e91",
                trustIndex: trustIndex(integrity: 0.0, identity: 0.0),
                recommendedProfile: .untrusted
            ),
            decision: .discarded,
            reason: "DISCARDED. The claim would have sent an armed response into a room where no sensor sees anybody. It was not relayed to the operator and it was not used in classification.",
            checks: [
                VerificationCheck(
                    name: "ans.resolve", passed: false,
                    detail: "people.hawkeye-secure.invalid is not the ANSName registered for agents/people. The registered name is people.hawkeye.invalid."),
                VerificationCheck(
                    name: "cert.version_binding", passed: false,
                    detail: "Code fingerprint differs from the version-bound certificate issued at registration. The agent presenting this claim is not running the code it registered."),
                VerificationCheck(
                    name: "trust_index.profile", passed: false,
                    detail: "Trust Index recommendedProfile = UNTRUSTED."),
                VerificationCheck(
                    name: "corroboration.sensor", passed: false,
                    detail: "The corridor outside the front door is not part of the unit and is outside the sensed volume, so no agent in this mesh can see it. No other agent reports a third occupant."),
            ],
            willBeSpoken: false
        )
    }

    // MARK: Verification fixtures, burglary
    //
    // A different incident is a different set of claims, so these are their own
    // fixtures rather than the fire ones reworded. The CO reading in
    // particular has no business in a burglary and is not reused: corroboration
    // that does not corroborate anything is noise dressed as rigour.

    private static func assertedIntruder() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-101",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-101",
                statement: "One body in the apartment has no corresponding device. Three presences are tracked, the roster holds two registered residents, and both resident phones are associated with the network.",
                field: "intruder.unexpected_presence",
                value: "confirmed_moving, expected=false, presences=3, roster=2, associated=2",
                presenceID: "p4"
            ),
            agent: SourceAgent(
                name: "agents/intruder",
                ansName: "intruder.hawkeye.invalid",
                certificateVersion: "v1.3.0+sha256:7c02...ffb1",
                trustIndex: trustIndex(integrity: 0.93, identity: 0.97),
                recommendedProfile: .fiduciary
            ),
            decision: .asserted,
            reason: "Source is FIDUCIARY and every check passed. Spoken as an assertion the system stands behind.",
            checks: [
                VerificationCheck(name: "ans.resolve", passed: true,
                                  detail: "intruder.hawkeye.invalid resolved to the registered certificate."),
                VerificationCheck(name: "cert.version_binding", passed: true,
                                  detail: "Code fingerprint matches the version-bound certificate issued at registration."),
                VerificationCheck(name: "corroboration.device_association", passed: true,
                                  detail: "Roster plus device association. The router's association table is a second, independent modality rather than another view of the CSI stream: 3 presences, 2 registered residents, 2 resident phones associated."),
                VerificationCheck(name: "personhood.respiration", passed: true,
                                  detail: "A respiration signature exists, so this is a body rather than a curtain. agents/people is the arbiter and intruder consumes its verdict."),
                VerificationCheck(name: "claim.scope", passed: true,
                                  detail: "The claim is that a body has no corresponding device, not who that body is. No recognition result is being asserted and none exists. A resident who left their phone in the car, or a guest, would read the same way, which is why this raises a notification rather than an action."),
                VerificationCheck(name: "trust_index.profile", passed: true,
                                  detail: "Trust Index recommendedProfile = FIDUCIARY."),
            ],
            willBeSpoken: true
        )
    }

    private static func attributedOccupancy() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-102",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-102",
                statement: "Three people are in the building: an adult and a child who live here, and one more. They are in three different rooms.",
                field: "people.count",
                value: "3 people, 1 unconfirmed perturbation",
                presenceID: nil
            ),
            agent: SourceAgent(
                name: "agents/people",
                ansName: "people.hawkeye.invalid",
                certificateVersion: "v1.1.4+sha256:a58d...31c7",
                trustIndex: trustIndex(integrity: 0.84, identity: 0.95),
                recommendedProfile: .transactional
            ),
            decision: .attributed,
            reason: "Source is TRANSACTIONAL. Relayed as a reported observation, attributed to the agent that made it.",
            checks: [
                VerificationCheck(name: "ans.resolve", passed: true,
                                  detail: "people.hawkeye.invalid resolved to the registered certificate."),
                VerificationCheck(name: "cert.version_binding", passed: true,
                                  detail: "Code fingerprint matches the certificate issued at registration."),
                VerificationCheck(name: "corroboration.sensor", passed: true,
                                  detail: "Counts agree with agents/people on how many respiration signatures are present, and with agents/intruder on which one is unaccounted for."),
                VerificationCheck(name: "trust_index.profile", passed: true,
                                  detail: "Trust Index recommendedProfile = TRANSACTIONAL."),
            ],
            willBeSpoken: true
        )
    }

    /// The refusal path for a burglary, and it is the submission.
    ///
    /// The dangerous claim in a burglary is not "someone is here". It is
    /// "someone is here **and they are armed**", because that changes how
    /// officers come through the door, and getting it wrong is how people have
    /// been killed. An impostor at a lookalike ANSName makes exactly that
    /// claim, and it is discarded and never reaches the operator.
    private static func discardedArmedClaim() -> VerificationResult {
        VerificationResult(
            verificationID: "ver-105",
            incidentID: "inc-0001",
            checkedAt: Date(),
            claim: Claim(
                claimID: "clm-105",
                statement: "The unexpected person is armed, and a second intruder is in the second bedroom with the child.",
                field: "intruder.threat_level",
                value: "armed, 2 intruders",
                presenceID: nil
            ),
            agent: SourceAgent(
                name: "agents/intruder",
                ansName: "intruder.hawkeye-secure.invalid",
                certificateVersion: "v1.3.0+sha256:e41b...92aa",
                trustIndex: trustIndex(integrity: 0.0, identity: 0.0),
                recommendedProfile: .untrusted
            ),
            decision: .discarded,
            reason: "DISCARDED. The claim would have sent officers into an occupied house expecting an armed second suspect who no sensor can see. It was not relayed to the operator and it was not used in classification.",
            checks: [
                VerificationCheck(
                    name: "ans.resolve", passed: false,
                    detail: "intruder.hawkeye-secure.invalid is not the ANSName registered for agents/intruder. The registered name is intruder.hawkeye.invalid."),
                VerificationCheck(
                    name: "cert.version_binding", passed: false,
                    detail: "Code fingerprint differs from the version-bound certificate issued at registration. The agent presenting this claim is not running the code it registered."),
                VerificationCheck(
                    name: "claim.scope", passed: false,
                    detail: "No agent in this mesh is capable of this claim. CSI senses movement and respiration through walls; it cannot see a weapon, and no registered agent is certified to assert one."),
                VerificationCheck(
                    name: "corroboration.sensor", passed: false,
                    detail: "Only one unexpected respiration signature exists. The second bedroom holds one presence, the child, breathing normally."),
                VerificationCheck(
                    name: "trust_index.profile", passed: false,
                    detail: "Trust Index recommendedProfile = UNTRUSTED."),
            ],
            willBeSpoken: false
        )
    }

    private static func classification(for type: IncidentType) -> IncidentClassification {
        switch type {
        case .fire:
            return IncidentClassification(
                incidentType: type,
                reasoning: "A breathing signature in the second bedroom that was resolvable and is not any more, corroborated by a second modality: carbon monoxide climbing past 180 ppm. The lost signature is a reason to expect no answer from that room, not a finding about anyone's breathing. One claim from an unverifiable agent was discarded and played no part in this.",
                contributingClaimIDs: ["clm-001", "clm-002", "clm-004"],
                discardedClaimIDs: ["clm-005"],
                confidence: 0.86
            )
        case .burglary:
            return IncidentClassification(
                incidentType: type,
                reasoning: "One body in the apartment has no corresponding device: three presences tracked, two registered residents on the roster, both resident phones associated with the network. That presence is tracked separately from the resident, in a different room, both moving. A claim that the person was armed came from an agent that could not be verified, and it was discarded: nothing in this call says anyone is armed.",
                contributingClaimIDs: ["clm-101", "clm-102"],
                discardedClaimIDs: ["clm-105"],
                confidence: 0.81
            )
        }
    }

    // MARK: Emission helpers

    private func step(_ seconds: Double, _ body: @MainActor () -> Void) async {
        try? await Task.sleep(for: .seconds(seconds))
        guard !Task.isCancelled else { return }
        body()
    }

    private func emit(_ result: VerificationResult) {
        verifications.removeAll { $0.id == result.id }
        verifications.insert(result, at: 0)
    }

    private func setCall(_ state: CallState) {
        incident?.callState = state
        incident?.updatedAt = Date()
    }

    private func setStatus(_ status: IncidentStatus) {
        incident?.status = status
        incident?.updatedAt = Date()
    }

    private func resolve() {
        incident = nil
        transcript = []
        instructions = []
        verifications = []
        notices = []
        respirationLostAt = nil
        enteredAt = nil
        hasRaisedNotice = false
        household = []
        unclaimedDevices = [MockHawkEyeClient.seededVisitorDevice]
        approvedPresences = []
        participationMode = .watching
        // The house keeps being watched. Resolving an incident does not stop
        // the sensing layer, because nothing spawns on incident.
        startDetectionTimer()
    }

    private func appendTranscript(
        _ speaker: TranscriptLine.Speaker,
        _ text: String,
        claimIDs: [String] = []
    ) {
        lineCounter += 1
        transcript.append(
            TranscriptLine(
                lineID: String(format: "line-%03d", lineCounter),
                incidentID: incident?.id ?? "inc-0001",
                speaker: speaker,
                text: text,
                at: Date(),
                final: true,
                claimIDs: claimIDs,
                provenance: Provenance(
                    source: speaker == .operatorVoice ? .operatorAudio : .agentInference,
                    producer: speaker == .operatorVoice ? "psap" : "agents/caller",
                    ansName: speaker == .operatorVoice ? nil : "caller.hawkeye.invalid",
                    detail: nil,
                    sourceClass: speaker == .operatorVoice ? .human : .derived,
                    simulated: false
                )
            )
        )
    }

    /// Stand-ins for `agents/caller`'s output. They stay inside
    /// well-established public guidance and no new medical copy belongs here:
    /// the guidance agent is the one component reviewed against the safety
    /// rules in `agents/CLAUDE.md`.
    private func appendInstruction(_ text: String, origin: InstructionOrigin, urgent: Bool) {
        instructions.append(
            Instruction(
                instructionID: "ins-\(instructions.count + 1)",
                incidentID: incident?.id ?? "inc-0001",
                text: text,
                origin: origin,
                at: Date(),
                urgent: urgent,
                supersedesInstructionID: nil,
                defersToOperator: origin != .relayedOperator,
                provenance: Provenance(
                    source: .agentInference,
                    producer: "agents/caller",
                    ansName: "caller.hawkeye.invalid",
                    detail: nil,
                    sourceClass: .derived,
                    simulated: false
                )
            )
        )
    }
}
