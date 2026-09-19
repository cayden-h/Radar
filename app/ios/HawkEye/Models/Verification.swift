import Foundation

/// One assertion a sensing agent made about the building.
struct Claim: Codable, Sendable, Hashable, Identifiable {
    var claimID: String
    /// Plain English, as `caller` would say it out loud.
    var statement: String
    /// Which part of interior state it asserts, e.g. `biometrics.respiration`.
    var field: String
    /// The asserted value, rendered as a string for display.
    var value: String
    var presenceID: String?

    var id: String { claimID }

    enum CodingKeys: String, CodingKey {
        case statement, field, value
        case claimID = "claim_id"
        case presenceID = "presence_id"
    }
}

/// Trust Index `recommendedProfile` policy hint.
///
/// Consumed rather than reinvented: using the track's own policy vocabulary is
/// free credibility, and the mapping to what a claim may trigger is the table in
/// `agents/CLAUDE.md`.
enum TrustProfile: String, Codable, Sendable, Hashable, CaseIterable {
    case untrusted = "UNTRUSTED"
    case readOnly = "READ_ONLY"
    case transactional = "TRANSACTIONAL"
    case fiduciary = "FIDUCIARY"

    var label: String {
        switch self {
        case .untrusted: "Untrusted"
        case .readOnly: "Read only"
        case .transactional: "Transactional"
        case .fiduciary: "Fiduciary"
        }
    }
}

/// Trust Index scores at the instant the claim was verified.
///
/// Only integrity and identity are implemented upstream. Solvency, behavior and
/// safety come back **null, not zero**, with `unimplementedDimensions` naming
/// them: a 0 that means "not implemented" and a 0 that means "scored zero" are
/// different facts and the app must never conflate them.
struct TrustIndexScore: Codable, Sendable, Hashable {
    var integrity: Double?
    var identity: Double?
    var solvency: Double?
    var behavior: Double?
    var safety: Double?
    /// Dimensions the Trust Index does not yet score. Null above, named here.
    var unimplementedDimensions: [String] = []

    /// The dimensions that actually carry a number, in display order.
    var scored: [(name: String, value: Double)] {
        var out: [(String, Double)] = []
        if let integrity { out.append(("Integrity", integrity)) }
        if let identity { out.append(("Identity", identity)) }
        if let solvency { out.append(("Solvency", solvency)) }
        if let behavior { out.append(("Behavior", behavior)) }
        if let safety { out.append(("Safety", safety)) }
        return out
    }

    enum CodingKeys: String, CodingKey {
        case integrity, identity, solvency, behavior, safety
        case unimplementedDimensions = "unimplemented_dimensions"
    }
}

/// The agent that made the claim.
struct SourceAgent: Codable, Sendable, Hashable {
    /// Agent directory name, e.g. `agents/people`.
    var name: String
    /// The ANSName the claim was presented under.
    var ansName: String
    /// Version-bound certificate recording the code running at registration.
    /// A fingerprint that drifted mid-run is how code drift becomes detectable.
    var certificateVersion: String?
    var trustIndex: TrustIndexScore?
    var recommendedProfile: TrustProfile

    enum CodingKeys: String, CodingKey {
        case name
        case ansName = "ansname"
        case certificateVersion = "certificate_version"
        case trustIndex = "trust_index"
        case recommendedProfile = "recommended_profile"
    }
}

/// What `master` did with a claim, given the source's profile.
///
/// A failing check outranks a good profile: any failed check produces
/// `.discarded` whatever the profile, and that ordering is the point.
enum VerificationDecision: String, Codable, Sendable, Hashable, CaseIterable {
    case asserted = "ASSERTED"
    case attributed = "ATTRIBUTED"
    case corroborationOnly = "CORROBORATION_ONLY"
    case discarded = "DISCARDED"

    var label: String {
        switch self {
        case .asserted: "Verified"
        case .attributed: "Attributed"
        case .corroborationOnly: "Corroboration only"
        case .discarded: "Discarded"
        }
    }

    /// One line explaining what the decision permits. Plain English, because a
    /// verdict without a consequence is not legible to anyone.
    var consequence: String {
        switch self {
        case .asserted: "Spoken to the operator as an assertion the system stands behind."
        case .attributed: "Spoken to the operator, attributed to the agent that reported it."
        case .corroborationOnly: "Used as corroboration only. Never the sole basis for a call."
        case .discarded: "Not spoken to the operator. Not used in classification."
        }
    }

    var isRefusal: Bool { self == .discarded }
}

/// One check performed, and whether it passed.
///
/// These are what make a discard legible on screen. "Untrusted" is a verdict;
/// "certificate fingerprint differs from the one registered" is a reason.
struct VerificationCheck: Codable, Sendable, Hashable, Identifiable {
    var name: String
    var passed: Bool
    var detail: String

    var id: String { name }
}

/// A claim, who made it, what was checked, and what was decided.
///
/// **This event is the submission.** A demo that escalates is unremarkable; one
/// that correctly refuses an impostor is the point, and the app renders that
/// refusal off this type.
struct VerificationResult: Codable, Sendable, Hashable, Identifiable {
    var verificationID: String
    var incidentID: String?
    var checkedAt: Date = .distantPast
    var claim: Claim
    var agent: SourceAgent
    var decision: VerificationDecision
    /// Why this decision. Present even on `.asserted`, so the stream reads the
    /// same both ways.
    var reason: String
    var checks: [VerificationCheck] = []
    /// Whether `agents/caller` is permitted to repeat this claim to the operator.
    var willBeSpoken: Bool = false

    var id: String { verificationID }

    /// The checks that failed. The whole reason a discard is legible.
    var failedChecks: [VerificationCheck] { checks.filter { !$0.passed } }

    enum CodingKeys: String, CodingKey {
        case claim, agent, decision, reason, checks
        case verificationID = "verification_id"
        case incidentID = "incident_id"
        case checkedAt = "checked_at"
        case willBeSpoken = "will_be_spoken"
    }

    init(
        verificationID: String,
        incidentID: String?,
        checkedAt: Date,
        claim: Claim,
        agent: SourceAgent,
        decision: VerificationDecision,
        reason: String,
        checks: [VerificationCheck] = [],
        willBeSpoken: Bool = false
    ) {
        self.verificationID = verificationID
        self.incidentID = incidentID
        self.checkedAt = checkedAt
        self.claim = claim
        self.agent = agent
        self.decision = decision
        self.reason = reason
        self.checks = checks
        self.willBeSpoken = willBeSpoken
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        verificationID = try c.decode(String.self, forKey: .verificationID)
        incidentID = try c.decodeIfPresent(String.self, forKey: .incidentID)
        checkedAt = try c.decodeIfPresent(Date.self, forKey: .checkedAt) ?? Date()
        claim = try c.decode(Claim.self, forKey: .claim)
        agent = try c.decode(SourceAgent.self, forKey: .agent)
        decision = try c.decode(VerificationDecision.self, forKey: .decision)
        reason = try c.decode(String.self, forKey: .reason)
        checks = try c.decodeIfPresent([VerificationCheck].self, forKey: .checks) ?? []
        willBeSpoken = try c.decodeIfPresent(Bool.self, forKey: .willBeSpoken) ?? false
    }
}
