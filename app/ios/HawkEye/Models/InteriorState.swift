import Foundation
import CoreGraphics

/// The states the interior view exists to distinguish.
///
/// This enum is the whole point of the system, so it lives in one place and
/// everything downstream switches on it rather than re-deriving the rule.
///
/// The difference between `.personUnresponsive` and `.unconfirmed` is the
/// difference between dispatching an ambulance and reporting a curtain.
///
/// **The raw values are the backend's `presence_state` enum, verbatim.**
/// The hub decides this now, and the client trusts its answer rather than
/// re-deriving it from a pile of booleans. See `PresenceState.derive` for the
/// fallback, which is used only when the server omits the field.
enum PresenceState: String, Codable, Sendable, Hashable, CaseIterable {

    /// Moving and breathing. A person, confirmed, and nothing is wrong.
    case personMoving = "confirmed_moving"

    /// Still but breathing. A person who is not responding.
    /// This is the one the whole system exists for.
    case personUnresponsive = "confirmed_still"

    /// A perturbation with no respiration signature. Not a person: a fan, a
    /// curtain, a cart, a swinging door. Rendered as clearly not-a-person.
    ///
    /// Absence of respiration is not proof of absence of a person. Shallow
    /// breathing and range limits both degrade toward invisible, which is why
    /// `agents/collapse` is cross-checked before this verdict is trusted, and
    /// why the UI never says "nobody there".
    case unconfirmed

    /// Not resolved yet. The backend keeps this separate from `.unconfirmed`
    /// precisely because absence of respiration is not proof of absence of a
    /// person, and the UI must not flatten the two into one word.
    case unresolved = "unknown"

    /// Derives the state from the raw signals.
    ///
    /// **This is the fallback, not the primary path.** The hub sends
    /// `presence.state` on every frame and the client trusts it. This runs only
    /// when a frame omits the field, so the app degrades to a defensible answer
    /// instead of drawing nothing.
    ///
    /// Respiration is the arbiter of personhood, per `agents/biometrics`.
    /// Movement alone cannot tell these states apart.
    static func derive(
        moving: Bool,
        respiration: RespirationStatus,
        stillDownS: Double?
    ) -> PresenceState {
        // Someone who went down and has not got up is unresponsive even if the
        // respiration estimate is currently marginal.
        if let stillDownS, stillDownS > 0 { return .personUnresponsive }
        switch respiration {
        case .breathing: return moving ? .personMoving : .personUnresponsive
        case .noSignature: return .unconfirmed
        case .unknown: return .unresolved
        }
    }

    var isPerson: Bool { self == .personMoving || self == .personUnresponsive }

    /// The line the interior view puts under the presence. Short, plain, and
    /// never more certain than the signal.
    var headline: String {
        switch self {
        case .personMoving: "Moving"
        case .personUnresponsive: "Not responding"
        case .unconfirmed: "Unconfirmed"
        case .unresolved: "Not resolved"
        }
    }

    var detail: String {
        switch self {
        case .personMoving: "Breathing, moving normally"
        case .personUnresponsive: "Breathing, has not moved"
        case .unconfirmed: "Movement with no breathing signature"
        case .unresolved: "Not enough signal to say yet"
        }
    }
}

/// Respiration is the personhood test. Never heart rate.
enum RespirationStatus: String, Codable, Sendable, Hashable, CaseIterable {
    case breathing
    case noSignature = "no_signature"
    case unknown
}

/// Coarse class, decided from respiration rate rather than signal amplitude.
enum PresenceClass: String, Codable, Sendable, Hashable, CaseIterable {
    case adult, child, pet, unknown

    /// Respiration rate does not cleanly separate a dog from a child, so the
    /// UI says the honest thing rather than the confident one.
    var label: String {
        switch self {
        case .adult: "Adult"
        case .child: "Child"
        case .pet: "Pet"
        case .unknown: "Unclassified"
        }
    }
}

/// Respiration and heart rate. Respiration carries the personhood verdict.
struct Vitals: Codable, Sendable, Hashable {
    var respiration: RespirationStatus = .unknown
    /// Reported only inside 6-30. Outside that range the hub sends null.
    var breathingBpm: Double?
    /// Reported only inside 40-120. Never the personhood test.
    var heartBpm: Double?
    /// Confidence that this perturbation is a living body.
    var personConfidence: Double = 0

    enum CodingKeys: String, CodingKey {
        case respiration
        case breathingBpm = "breathing_bpm"
        case heartBpm = "heart_bpm"
        case personConfidence = "person_confidence"
    }
}

/// Coarse position inside the floorplan.
///
/// `zone` is the honest answer and is what the agents reason over. `x` and `y`
/// exist only so the view has somewhere to draw; they are a zone centroid, not
/// a localization claim. Do not promise coordinates.
struct Position: Codable, Sendable, Hashable {
    var zone: String = ""
    /// Metres from the floorplan origin.
    var x: Double = 0
    /// Metres from the floorplan origin.
    var y: Double = 0
    var zoneConfidence: Double = 0

    enum CodingKeys: String, CodingKey {
        case zone, x, y
        case zoneConfidence = "zone_confidence"
    }
}

/// Rolling-baseline health. When `healthy` is false the baseline is stale,
/// escalation is suppressed upstream, and the UI must say so rather than
/// drawing confident nonsense.
struct Calibration: Codable, Sendable, Hashable {
    var baselineAgeS: Double = 0
    var healthy: Bool = true
    var note: String?

    enum CodingKeys: String, CodingKey {
        case baselineAgeS = "baseline_age_s"
        case healthy, note
    }
}

/// Air quality. Carbon monoxide, and deliberately not from CSI: two independent
/// modalities agreeing is real corroboration, two views of one CSI stream is
/// not. No gas sensor was purchased, so `provenance.source` is `demo-trigger`.
struct EnvironmentReading: Codable, Sendable, Hashable {
    var coPpm: Double = 0
    var smokeDetected: Bool = false
    var confidence: Double = 0
    var provenance: Provenance

    /// Read off the provenance the server computed. The client never decides
    /// this for itself.
    var isSimulated: Bool { provenance.simulated }

    enum CodingKeys: String, CodingKey {
        case coPpm = "co_ppm"
        case smokeDetected = "smoke_detected"
        case confidence, provenance
    }
}

/// One tracked presence.
///
/// `presenceID` is stable within a session only. We do not do person
/// re-identification and must not claim to.
struct Presence: Codable, Sendable, Hashable, Identifiable {
    var presenceID: String
    /// The server's verdict. Trusted as sent.
    var state: PresenceState
    var position: Position
    var moving: Bool
    /// Confidence the presence exists at all. Rendered as coherence, never as a
    /// number floating in space.
    var confidence: Double
    var vitals: Vitals
    var presenceClass: PresenceClass
    /// What the class decision was made from. `respiration_rate` is the
    /// defensible one.
    var classBasis: String?
    /// `agents/intruder`'s inference from context. Never a recognition result.
    var expected: Bool?
    /// Seconds down and not moving. The clinical variable: a long lie is over an
    /// hour, and half of those die within six months absent any injury.
    var stillDownS: Double?
    var provenance: Provenance?

    var id: String { presenceID }
    var zone: String { position.zone }
    var breathingBpm: Double? { vitals.breathingBpm }
    var heartBpm: Double? { vitals.heartBpm }

    /// A deterministic per-presence phase so several blobs do not breathe in
    /// lockstep, which looks synthetic.
    var phase: Double {
        var h: UInt64 = 5381
        for byte in presenceID.utf8 { h = (h &* 33) &+ UInt64(byte) }
        return Double(h % 1000) / 1000.0 * 2 * .pi
    }

    enum CodingKeys: String, CodingKey {
        case state, position, moving, confidence, vitals, expected, provenance
        case presenceID = "presence_id"
        case presenceClass = "presence_class"
        case classBasis = "class_basis"
        case stillDownS = "still_down_s"
    }

    init(
        presenceID: String,
        state: PresenceState,
        position: Position,
        moving: Bool,
        confidence: Double,
        vitals: Vitals = Vitals(),
        presenceClass: PresenceClass = .unknown,
        classBasis: String? = nil,
        expected: Bool? = nil,
        stillDownS: Double? = nil,
        provenance: Provenance? = nil
    ) {
        self.presenceID = presenceID
        self.state = state
        self.position = position
        self.moving = moving
        self.confidence = confidence
        self.vitals = vitals
        self.presenceClass = presenceClass
        self.classBasis = classBasis
        self.expected = expected
        self.stillDownS = stillDownS
        self.provenance = provenance
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        presenceID = try c.decode(String.self, forKey: .presenceID)
        position = try c.decodeIfPresent(Position.self, forKey: .position) ?? Position()
        moving = try c.decodeIfPresent(Bool.self, forKey: .moving) ?? false
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        vitals = try c.decodeIfPresent(Vitals.self, forKey: .vitals) ?? Vitals()
        presenceClass = try c.decodeIfPresent(PresenceClass.self, forKey: .presenceClass) ?? .unknown
        classBasis = try c.decodeIfPresent(String.self, forKey: .classBasis)
        expected = try c.decodeIfPresent(Bool.self, forKey: .expected)
        stillDownS = try c.decodeIfPresent(Double.self, forKey: .stillDownS)
        provenance = try c.decodeIfPresent(Provenance.self, forKey: .provenance)
        // Trust the server's verdict. `derive` is the fallback for a frame that
        // omits it, and nothing else in the app re-derives this.
        state = try c.decodeIfPresent(PresenceState.self, forKey: .state)
            ?? PresenceState.derive(
                moving: moving,
                respiration: vitals.respiration,
                stillDownS: stillDownS
            )
    }
}

/// The floorplan the presences are drawn into.
///
/// **Authored, not sensed.** The system does not map walls and cannot; walls are
/// the static baseline it subtracts to see people. The hub sends the plan it was
/// enrolled with, in metres, and the view normalises it.
struct Floorplan: Codable, Sendable, Hashable {

    struct Room: Codable, Sendable, Hashable, Identifiable {
        var zone: String
        var name: String
        /// Polygon in metres, floorplan origin at (0,0).
        var polygon: [[Double]] = []

        var id: String { zone }

        /// Axis-aligned bounds of the polygon, in metres.
        func bounds() -> CGRect {
            guard let first = polygon.first, first.count >= 2 else { return .zero }
            var minX = first[0], maxX = first[0], minY = first[1], maxY = first[1]
            for point in polygon where point.count >= 2 {
                minX = Swift.min(minX, point[0]); maxX = Swift.max(maxX, point[0])
                minY = Swift.min(minY, point[1]); maxY = Swift.max(maxY, point[1])
            }
            return CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
        }
    }

    var siteID: String = ""
    var name: String = ""
    var units: String = "m"
    var widthM: Double = 12
    var depthM: Double = 9
    var wallHeightM: Double = 2.5
    var rooms: [Room] = []

    enum CodingKeys: String, CodingKey {
        case name, units, rooms
        case siteID = "site_id"
        case widthM = "width_m"
        case depthM = "depth_m"
        case wallHeightM = "wall_height_m"
    }

    func room(named zone: String) -> Room? {
        let key = zone.lowercased().replacingOccurrences(of: " ", with: "_")
        return rooms.first { $0.zone == key }
    }

    /// A room's bounds normalised into 0...1 of the plan, for drawing.
    func normalizedRect(_ room: Room) -> CGRect {
        let b = room.bounds()
        guard widthM > 0, depthM > 0 else { return .zero }
        return CGRect(
            x: b.minX / widthM,
            y: b.minY / depthM,
            width: b.width / widthM,
            height: b.height / depthM
        )
    }

    /// A metre position normalised into 0...1 of the plan.
    func normalizedPoint(_ position: Position) -> CGPoint {
        guard widthM > 0, depthM > 0 else { return CGPoint(x: 0.5, y: 0.5) }
        return CGPoint(x: position.x / widthM, y: position.y / depthM)
    }

    /// The demo house, used before the first frame arrives and in previews.
    /// The hub's own plan replaces it the moment one is received.
    static let home = Floorplan(
        siteID: "site-demo-01",
        name: "Ridgeview Lane",
        units: "m",
        widthM: 12, depthM: 9, wallHeightM: 2.5,
        rooms: [
            Room(zone: "living_room", name: "Living room",
                 polygon: [[0, 0], [6, 0], [6, 5], [0, 5]]),
            Room(zone: "kitchen", name: "Kitchen",
                 polygon: [[6, 0], [12, 0], [12, 4], [6, 4]]),
            Room(zone: "hallway", name: "Hallway",
                 polygon: [[0, 5], [12, 5], [12, 6.5], [0, 6.5]]),
            Room(zone: "west_bedroom", name: "West bedroom",
                 polygon: [[0, 6.5], [5, 6.5], [5, 9], [0, 9]]),
            Room(zone: "east_bedroom", name: "East bedroom",
                 polygon: [[5, 6.5], [9, 6.5], [9, 9], [5, 9]]),
            Room(zone: "garage", name: "Garage",
                 polygon: [[9, 6.5], [12, 6.5], [12, 9], [9, 9]]),
        ]
    )
}

/// Everything the app needs to draw the house right now.
///
/// This is `GET /v1/state` and the `state` event payload, field for field.
struct InteriorState: Codable, Sendable, Hashable {
    var siteID: String = ""
    var capturedAt: Date = .distantPast
    /// ANSName of the sensing device.
    var sensorIdentity: String = ""
    var calibration: Calibration = Calibration()
    var presences: [Presence] = []
    /// Null when `agents/environment` has not reported.
    var environment: EnvironmentReading?
    var floorplan: Floorplan = .home
    var activeIncidentID: String?

    var peopleCount: Int { presences.filter(\.state.isPerson).count }
    var hasUnresponsive: Bool { presences.contains { $0.state == .personUnresponsive } }

    /// False means the baseline is stale. Escalation is suppressed upstream and
    /// the view says so rather than drawing confident nonsense.
    var calibrationHealthy: Bool { calibration.healthy }
    var coPpm: Double? { environment?.coPpm }
    var coSourceIsSimulated: Bool { environment?.isSimulated ?? false }

    enum CodingKeys: String, CodingKey {
        case calibration, presences, environment, floorplan
        case siteID = "site_id"
        case capturedAt = "captured_at"
        case sensorIdentity = "sensor_identity"
        case activeIncidentID = "active_incident_id"
    }

    init() {}

    init(
        siteID: String,
        capturedAt: Date,
        sensorIdentity: String,
        calibration: Calibration,
        presences: [Presence],
        environment: EnvironmentReading? = nil,
        floorplan: Floorplan = .home,
        activeIncidentID: String? = nil
    ) {
        self.siteID = siteID
        self.capturedAt = capturedAt
        self.sensorIdentity = sensorIdentity
        self.calibration = calibration
        self.presences = presences
        self.environment = environment
        self.floorplan = floorplan
        self.activeIncidentID = activeIncidentID
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        siteID = try c.decodeIfPresent(String.self, forKey: .siteID) ?? ""
        capturedAt = try c.decodeIfPresent(Date.self, forKey: .capturedAt) ?? Date()
        sensorIdentity = try c.decodeIfPresent(String.self, forKey: .sensorIdentity) ?? ""
        calibration = try c.decodeIfPresent(Calibration.self, forKey: .calibration) ?? Calibration()
        presences = try c.decodeIfPresent([Presence].self, forKey: .presences) ?? []
        environment = try c.decodeIfPresent(EnvironmentReading.self, forKey: .environment)
        floorplan = try c.decodeIfPresent(Floorplan.self, forKey: .floorplan) ?? .home
        activeIncidentID = try c.decodeIfPresent(String.self, forKey: .activeIncidentID)
    }
}
