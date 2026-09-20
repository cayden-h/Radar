import Foundation

/// The watch's one switch, and the mirror of `Config.useMocks` on the phone.
///
/// The watch app is a phone-paired companion, so in principle it has nothing to
/// mock: the phone is the source of everything. In practice pairing a watch
/// simulator to a phone simulator is fiddly and occasionally just refuses, and
/// **the demo must never depend on that working**, which is the same rule the
/// phone's mock flag exists for.
///
/// `true` runs all three screens off a scripted feed with no phone at all.
enum WatchConfig {

    /// Live by default as of 2026-09-20, matching the phone's `Config.useMocks`.
    /// The watch now draws what the phone relays from a real hub.
    ///
    /// Kept rather than deleted, for the reason `Config.useMocks` gives: this
    /// is the fallback when pairing refuses on the day.
    static let useMockLink = false

    /// How long a consequential control is held before it fires. 1.5 seconds,
    /// the same as every other risky control in the project. A wrist is the
    /// easiest surface in the world to press by accident and an accidental
    /// press here calls 911.
    static let holdDuration: Double = 1.5

    /// How long the watch waits for the phone to reflect a command before it
    /// says the command did not land.
    ///
    /// The phone publishes a pending outcome the moment it receives a command,
    /// so anything longer than this means the message never arrived.
    static let commandAcknowledgementTimeout: TimeInterval = 6

    /// A snapshot older than this is not worth drawing. The phone publishes on
    /// change rather than on a heartbeat, so this is generous on purpose: it
    /// catches a dead link, not a quiet house.
    static let snapshotStaleAfter: TimeInterval = 300
}
