import Foundation

/// Who the house is not surprised by, and what they carry.
///
/// This is the backend's `HouseholdMember`, field for field, checked against
/// `app/backend/schema/household.json`. A roster entry is always a human
/// declaration: either the resident approving a presence that just showed up,
/// or naming a visitor from the notice banner. There is no path that infers a
/// member from CSI alone, and `Kind`/`AddedBy` exist to say so on screen.
///
/// `identifier_hash` is deliberately not modelled here. It is an HMAC digest
/// the backend keeps so a leaked roster does not double as a device-tracking
/// list, and the app has no use for it: a value the UI never holds cannot leak
/// from the UI.
struct HouseholdMember: Codable, Sendable, Hashable, Identifiable {

    /// Whether someone lives here or is a visitor. Two words, and the label is
    /// what the roster prints, not the raw case name.
    enum Kind: String, Codable, Sendable, Hashable, CaseIterable {
        case resident
        case guest

        var label: String {
            switch self {
            case .resident: "Lives here"
            case .guest: "Visitor"
            }
        }
    }

    /// How this member joined the roster. Approving a live detection is a
    /// different kind of fact from naming someone during the remember flow
    /// (there is no separate enrollment screen in this app, but the backend's
    /// enum still distinguishes the two, and the client mirrors it rather than
    /// collapsing it).
    enum AddedBy: String, Codable, Sendable, Hashable, CaseIterable {
        case approval
        case enrollment
    }

    var memberID: String
    var name: String
    var kind: Kind
    var devices: [KnownDevice]
    var addedAt: Date
    var addedBy: AddedBy
    var provenance: Provenance
    /// **Computed on the server**, not here. A named guest with no device is
    /// legal, and this is false in that case: present, but invisible to the
    /// roster next time. The client reads this rather than checking
    /// `devices.isEmpty` itself, for the same reason `Provenance.sourceClass`
    /// is server-computed: one source of truth for a fact that decides what
    /// the UI may claim about the system's ability to recognise someone.
    var isRecognisable: Bool

    var id: String { memberID }

    enum CodingKeys: String, CodingKey {
        case name, kind, devices, provenance
        case memberID = "member_id"
        case addedAt = "added_at"
        case addedBy = "added_by"
        case isRecognisable = "recognisable"
    }
}

/// A device the roster recognises, hanging off a `HouseholdMember`.
struct KnownDevice: Codable, Sendable, Hashable, Identifiable {
    var deviceID: String
    var fingerprint: String
    /// What the resident calls it, e.g. "iPhone". Optional: nothing on the
    /// remember sheet collects this yet.
    var label: String?
    var addedAt: Date
    var lastSeenAt: Date?

    var id: String { deviceID }

    enum CodingKeys: String, CodingKey {
        case fingerprint, label
        case deviceID = "device_id"
        case addedAt = "added_at"
        case lastSeenAt = "last_seen_at"
    }
}

/// A device seen associated to the network that nobody has claimed yet.
///
/// This is the binding candidate the remember sheet offers: "this phone joined
/// just now, is it theirs?" It carries `Provenance` like any other reading, so
/// the mock path's simulated device is labelled as such rather than presented
/// as a real association.
struct ObservedDevice: Codable, Sendable, Hashable, Identifiable {
    var deviceID: String
    var fingerprint: String
    var firstSeenAt: Date
    var provenance: Provenance

    var id: String { deviceID }

    enum CodingKeys: String, CodingKey {
        case fingerprint, provenance
        case deviceID = "device_id"
        case firstSeenAt = "first_seen_at"
    }
}

/// `POST /v1/household/remember` request body.
struct RememberRequest: Codable, Sendable, Hashable {
    var name: String
    var kind: HouseholdMember.Kind
    var deviceID: String?

    enum CodingKeys: String, CodingKey {
        case name, kind
        case deviceID = "device_id"
    }
}
