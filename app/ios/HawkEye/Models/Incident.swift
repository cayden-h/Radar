import Foundation
import SwiftUI

/// The two incident types. Fixed set, per the root `CLAUDE.md`.
enum IncidentType: String, Codable, Sendable, Hashable, CaseIterable, Identifiable {
    case burglary, fire

    var id: String { rawValue }

    var title: String {
        switch self {
        case .burglary: "Burglary"
        case .fire: "Fire"
        }
    }

    var symbol: String {
        switch self {
        case .burglary: "figure.run"
        case .fire: "flame.fill"
        }
    }

    var tint: Color {
        switch self {
        case .burglary: Palette.burglary
        case .fire: Palette.fire
        }
    }
}

extension IncidentType {

    /// The one incident type the pivot left.
    ///
    /// Fire went with the simulated gas sensor on 2026-09-19 and fall detection
    /// went earlier the same day, so there is nothing for a resident to choose,
    /// which is the right shape for a control someone uses while frightened.
    ///
    /// The wire enum still spells it `burglary` until T01 renames it. Every
    /// caller that raises an incident goes through this one name instead, so the
    /// rename is a one-line change here rather than a search across the app, and
    /// nothing user-facing says the old word.
    static var intrusion: IncidentType { .burglary }
}

/// How the incident was raised. The autonomous path is the one that matters,
/// because the person who would have pressed the button may not be in a state
/// to press it.
enum IncidentOrigin: String, Codable, Sendable, Hashable, CaseIterable {
    case user
    case system

    var label: String {
        switch self {
        case .user: "Raised by you"
        case .system: "Raised by Hawk Eye"
        }
    }
}

/// Where the incident is in its lifecycle, as `master` reports it.
enum IncidentStatus: String, Codable, Sendable, Hashable, CaseIterable {
    case raised, classified, calling
    case onCall = "on_call"
    case dispatched, resolved, refused
}

/// Which transition the `incident` event is reporting.
enum IncidentPhase: String, Codable, Sendable, Hashable, CaseIterable {
    case raised, classified, updated, resolved, refused
}

/// State of the phone call to the 911 operator.
enum CallState: String, Codable, Sendable, Hashable, CaseIterable {
    case notStarted = "not_started"
    case dialing
    case connected
    case ended
    case notPlaced = "not_placed"

    var label: String {
        switch self {
        case .notStarted: "Preparing to call"
        case .dialing: "Dialing 911"
        case .connected: "On the line with 911"
        case .ended: "Call ended"
        case .notPlaced: "No call placed"
        }
    }
}

/// Why `master` called it what it called it.
///
/// Classification is the interesting part and should be visible.
/// Elevated CO plus a breathing signature that has gone missing is a fire with
/// an occupant who may not be able to respond, not two separate incidents.
struct IncidentClassification: Codable, Sendable, Hashable {
    var incidentType: IncidentType
    /// Plain English, shown to the resident.
    var reasoning: String
    var contributingClaimIDs: [String] = []
    /// Claims that did not survive verification. Named, not hidden.
    var discardedClaimIDs: [String] = []
    var confidence: Double = 0

    enum CodingKeys: String, CodingKey {
        case reasoning, confidence
        case incidentType = "incident_type"
        case contributingClaimIDs = "contributing_claim_ids"
        case discardedClaimIDs = "discarded_claim_ids"
    }
}

/// One line the resident typed into the "what is happening" box, echoed back so
/// the app can confirm delivery.
///
/// Provenance is `user-input`: it is a human statement, not a measurement, and
/// `caller` attributes it as one rather than asserting it as sensed fact.
struct ContextNote: Codable, Sendable, Hashable, Identifiable {
    var noteID: String
    var incidentID: String
    var text: String
    var at: Date = .distantPast
    var provenance: Provenance
    var deliveredToCaller: Bool = false

    var id: String { noteID }

    enum CodingKeys: String, CodingKey {
        case text, at, provenance
        case noteID = "note_id"
        case incidentID = "incident_id"
        case deliveredToCaller = "delivered_to_caller"
    }
}

/// One incident, from raised to resolved. The backend's `Incident`, field for
/// field.
struct Incident: Codable, Sendable, Hashable, Identifiable {
    var incidentID: String
    var siteID: String
    var incidentType: IncidentType
    var status: IncidentStatus
    var raisedBy: IncidentOrigin
    var raisedAt: Date = .distantPast
    var updatedAt: Date = .distantPast
    var resolvedAt: Date?
    /// What `caller` will read to the dispatcher.
    var address: String = ""
    var classification: IncidentClassification?
    var callState: CallState = .notStarted
    var contextNotes: [ContextNote] = []
    /// Set when status is `refused`: why the system declined to escalate.
    var refusalReason: String?

    var id: String { incidentID }
    var type: IncidentType { incidentType }
    var origin: IncidentOrigin { raisedBy }
    var openedAt: Date { raisedAt }
    /// `master`'s reasoning, in plain English, or the refusal when it declined.
    var summary: String? { refusalReason ?? classification?.reasoning }

    enum CodingKeys: String, CodingKey {
        case status, address, classification
        case incidentID = "incident_id"
        case siteID = "site_id"
        case incidentType = "incident_type"
        case raisedBy = "raised_by"
        case raisedAt = "raised_at"
        case updatedAt = "updated_at"
        case resolvedAt = "resolved_at"
        case callState = "call_state"
        case contextNotes = "context_notes"
        case refusalReason = "refusal_reason"
    }

    init(
        incidentID: String,
        siteID: String,
        incidentType: IncidentType,
        status: IncidentStatus,
        raisedBy: IncidentOrigin,
        raisedAt: Date,
        updatedAt: Date,
        resolvedAt: Date? = nil,
        address: String,
        classification: IncidentClassification? = nil,
        callState: CallState = .notStarted,
        contextNotes: [ContextNote] = [],
        refusalReason: String? = nil
    ) {
        self.incidentID = incidentID
        self.siteID = siteID
        self.incidentType = incidentType
        self.status = status
        self.raisedBy = raisedBy
        self.raisedAt = raisedAt
        self.updatedAt = updatedAt
        self.resolvedAt = resolvedAt
        self.address = address
        self.classification = classification
        self.callState = callState
        self.contextNotes = contextNotes
        self.refusalReason = refusalReason
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        incidentID = try c.decode(String.self, forKey: .incidentID)
        siteID = try c.decodeIfPresent(String.self, forKey: .siteID) ?? ""
        incidentType = try c.decode(IncidentType.self, forKey: .incidentType)
        status = try c.decode(IncidentStatus.self, forKey: .status)
        raisedBy = try c.decode(IncidentOrigin.self, forKey: .raisedBy)
        raisedAt = try c.decodeIfPresent(Date.self, forKey: .raisedAt) ?? Date()
        updatedAt = try c.decodeIfPresent(Date.self, forKey: .updatedAt) ?? raisedAt
        resolvedAt = try c.decodeIfPresent(Date.self, forKey: .resolvedAt)
        address = try c.decodeIfPresent(String.self, forKey: .address) ?? ""
        classification = try c.decodeIfPresent(IncidentClassification.self, forKey: .classification)
        callState = try c.decodeIfPresent(CallState.self, forKey: .callState) ?? .notStarted
        contextNotes = try c.decodeIfPresent([ContextNote].self, forKey: .contextNotes) ?? []
        refusalReason = try c.decodeIfPresent(String.self, forKey: .refusalReason)
    }
}

/// `POST /v1/incident` request and its 202 acknowledgement.
struct RaiseIncidentRequest: Codable, Sendable, Hashable {
    var incidentType: IncidentType
    var note: String?

    enum CodingKeys: String, CodingKey {
        case note
        case incidentType = "incident_type"
    }
}

struct IncidentAck: Codable, Sendable, Hashable {
    var incidentID: String
    var status: IncidentStatus
    var acceptedAt: Date = .distantPast

    enum CodingKeys: String, CodingKey {
        case status
        case incidentID = "incident_id"
        case acceptedAt = "accepted_at"
    }
}

/// `POST /v1/incident/{id}/context` request body.
struct ContextRequest: Codable, Sendable, Hashable {
    var text: String
}

/// One line of the caller to 911 conversation, shown to the resident.
///
/// The operator does not see this. It exists so the resident is not left in
/// silence while a synthetic voice speaks on their behalf.
struct TranscriptLine: Codable, Sendable, Hashable, Identifiable {

    enum Speaker: String, Codable, Sendable, Hashable, CaseIterable {
        /// `agents/caller`, speaking on the resident's behalf.
        case caller
        /// The human 911 operator.
        case operatorVoice = "operator"
        /// The resident, speaking on the line directly.
        case resident
        /// A non-speech annotation, e.g. "call connected".
        case system

        var label: String {
            switch self {
            case .caller: "Hawk Eye"
            case .operatorVoice: "911 Operator"
            case .resident: "You"
            case .system: "Call"
            }
        }
    }

    var lineID: String
    var incidentID: String
    var speaker: Speaker
    var text: String
    var at: Date = .distantPast
    /// False for a partial transcription being revised in place.
    var final: Bool = true
    /// Verified claims this line repeats, so a spoken sentence can be linked to
    /// its proof.
    var claimIDs: [String] = []
    var provenance: Provenance?

    var id: String { lineID }
    /// The view reads this. A line still being revised is drawn dimmer.
    var partial: Bool { !final }

    enum CodingKeys: String, CodingKey {
        case speaker, text, at, final, provenance
        case lineID = "line_id"
        case incidentID = "incident_id"
        case claimIDs = "claim_ids"
    }

    init(
        lineID: String,
        incidentID: String,
        speaker: Speaker,
        text: String,
        at: Date,
        final: Bool = true,
        claimIDs: [String] = [],
        provenance: Provenance? = nil
    ) {
        self.lineID = lineID
        self.incidentID = incidentID
        self.speaker = speaker
        self.text = text
        self.at = at
        self.final = final
        self.claimIDs = claimIDs
        self.provenance = provenance
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        lineID = try c.decode(String.self, forKey: .lineID)
        incidentID = try c.decodeIfPresent(String.self, forKey: .incidentID) ?? ""
        speaker = try c.decode(Speaker.self, forKey: .speaker)
        text = try c.decode(String.self, forKey: .text)
        at = try c.decodeIfPresent(Date.self, forKey: .at) ?? Date()
        final = try c.decodeIfPresent(Bool.self, forKey: .final) ?? true
        claimIDs = try c.decodeIfPresent([String].self, forKey: .claimIDs) ?? []
        provenance = try c.decodeIfPresent(Provenance.self, forKey: .provenance)
    }
}

/// Where an instruction came from.
///
/// The UI deliberately does not distinguish these, because the user does not
/// care. The API does, because the safety rules differ: relayed operator
/// instructions always win over generated first aid.
enum InstructionOrigin: String, Codable, Sendable, Hashable, CaseIterable {
    case relayedOperator = "relayed_operator"
    case firstAid = "first_aid"
    case systemStatus = "system_status"
}

/// One thing `agents/caller` is telling the resident to do.
///
/// **The client never authors this text.** Everything shown comes from the
/// guidance agent, which is the component that owns the safety rules in
/// `agents/CLAUDE.md`. Hardcoding first-aid copy in the client would put
/// medical instructions outside the one place reviewed for them.
struct Instruction: Codable, Sendable, Hashable, Identifiable {
    var instructionID: String
    var incidentID: String
    var text: String
    var origin: InstructionOrigin
    var at: Date = .distantPast
    /// Guidance marks the small number of instructions that are time-critical.
    /// This changes weight and nothing else; it never reveals the source.
    var urgent: Bool = false
    var supersedesInstructionID: String?
    /// True when this instruction must be dropped the moment the dispatcher
    /// gives a competing one. Dispatchers are trained for this; the agent is not.
    var defersToOperator: Bool = true
    var provenance: Provenance?

    var id: String { instructionID }

    enum CodingKeys: String, CodingKey {
        case text, origin, at, urgent, provenance
        case instructionID = "instruction_id"
        case incidentID = "incident_id"
        case supersedesInstructionID = "supersedes_instruction_id"
        case defersToOperator = "defers_to_operator"
    }

    init(
        instructionID: String,
        incidentID: String,
        text: String,
        origin: InstructionOrigin,
        at: Date,
        urgent: Bool = false,
        supersedesInstructionID: String? = nil,
        defersToOperator: Bool = true,
        provenance: Provenance? = nil
    ) {
        self.instructionID = instructionID
        self.incidentID = incidentID
        self.text = text
        self.origin = origin
        self.at = at
        self.urgent = urgent
        self.supersedesInstructionID = supersedesInstructionID
        self.defersToOperator = defersToOperator
        self.provenance = provenance
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        instructionID = try c.decode(String.self, forKey: .instructionID)
        incidentID = try c.decodeIfPresent(String.self, forKey: .incidentID) ?? ""
        text = try c.decode(String.self, forKey: .text)
        origin = try c.decode(InstructionOrigin.self, forKey: .origin)
        at = try c.decodeIfPresent(Date.self, forKey: .at) ?? Date()
        urgent = try c.decodeIfPresent(Bool.self, forKey: .urgent) ?? false
        supersedesInstructionID = try c.decodeIfPresent(String.self, forKey: .supersedesInstructionID)
        defersToOperator = try c.decodeIfPresent(Bool.self, forKey: .defersToOperator) ?? true
        provenance = try c.decodeIfPresent(Provenance.self, forKey: .provenance)
    }
}
