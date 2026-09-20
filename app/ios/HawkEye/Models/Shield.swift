import Foundation

/// Where the lens shield is, as the app draws it.
///
/// Four states, per `TASKS.md` T32, and **the shutter itself only reports two
/// of them.** `agents/shutter` answers `open` or `closed` and nothing else;
/// `opening` is the transit the hub reports while the servo is moving, and
/// `refused` is `closed` plus a refusal code. Keeping the app's four and the
/// agent's two straight matters, because a reader who thinks the servo reports
/// four things will go looking for a `refused` position that does not exist.
///
/// `refused` is not an error and must not be drawn as one: it is
/// `agents/shutter` declining to move because something asked it to uncover the
/// camera and could not prove it was allowed to. That is the state this whole
/// project exists to show.
enum ShieldState: String, Codable, Sendable, Hashable, CaseIterable {
    case closed
    case opening
    case open
    case refused

    /// Two or three words. The headline on a wrist.
    var label: String {
        switch self {
        case .closed: "Shield closed"
        case .opening: "Shield opening"
        case .open: "Shield open"
        case .refused: "Shield held closed"
        }
    }

    /// One sentence a non-technical person reads correctly the first time.
    ///
    /// The client never authors safety instructions, but it does own the words
    /// for its own hardware state, and these four sentences are the product.
    var detail: String {
        switch self {
        case .closed: "The camera cannot see. There is an object in front of the lens."
        case .opening: "The shield is moving off the lens."
        case .open: "The camera can see and is recording."
        case .refused: "Something asked to open the camera and could not prove it was allowed to."
        }
    }

    /// True while the camera physically cannot see. Drives whether any view is
    /// allowed to show a frame at all.
    var lensIsCovered: Bool { self != .open }
}

/// How a position was arrived at.
///
/// There is one value today and it is the honest one. The SG92R is open-loop
/// and has no position feedback, so a shutter position is the angle that was
/// **commanded** and never the angle the shield reached. A shield that jammed
/// would attest open while still covering the lens, and the only thing that
/// catches that is the frame itself being dark.
///
/// It is a named field rather than a comment because `shutter/CLAUDE.md`
/// requires it to be: a consumer must not be able to read a commanded angle as
/// a measurement by accident.
enum PositionBasis: String, Codable, Sendable, Hashable, CaseIterable {
    case commanded

    var label: String { "Commanded, not measured" }
}

/// The shutter's own report of where the shield is, and what moved it.
///
/// Matched field for field against the attestation `agents/shutter` signs, in
/// `agents/agents/shutter/shutter.py`. This is a physical position attested by
/// the agent that holds the GPIO pin, not a UI flag, and nothing in the app may
/// set it locally.
struct ShieldStatus: Codable, Sendable, Hashable {
    var state: ShieldState = .closed
    /// When the shield last moved, or last refused to.
    var changedAt: Date = .distantPast
    /// The angle the servo was told to go to. 0 covers the lens, 90 clears it.
    var commandedAngle: Int?
    /// Always `commanded`. Carried so the limit travels in the data.
    var positionBasis: PositionBasis = .commanded
    /// The nonce `shutter` issued for the grant it acted on or refused.
    /// Present so a refusal can be tied to one specific attempt in the sealed
    /// record; an unbound refusal says only that a refusal happened somewhere.
    var grantNonce: String?
    /// The machine-readable refusal, e.g. `lookalike_ansname`. Set only when
    /// `state` is `refused`. Kept alongside the sentence rather than instead of
    /// it, because the resident reads one and an investigator reads the other.
    var refusalCode: String?
    /// Set only when `state` is `refused`. Plain English, shown as is.
    var refusalReason: String?
    var provenance: Provenance?

    enum CodingKeys: String, CodingKey {
        case state, provenance
        case changedAt = "changed_at"
        case commandedAngle = "commanded_angle"
        case positionBasis = "position_basis"
        case grantNonce = "grant_nonce"
        case refusalCode = "refusal_code"
        case refusalReason = "refusal_reason"
    }
}
