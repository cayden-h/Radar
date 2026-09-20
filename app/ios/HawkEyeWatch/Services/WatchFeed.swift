import Foundation

/// Where the watch's snapshots come from.
///
/// Two implementations, chosen once in `WatchModel.init` from
/// `WatchConfig.useMockLink`, and nothing downstream knows which it got. Same
/// rule as `Config.useMocks` on the phone: there is no demo branch inside a
/// view.
@MainActor
protocol WatchFeed: AnyObject {

    /// Begin. Both callbacks are delivered on the main actor.
    func start(
        onSnapshot: @escaping @MainActor (WatchSnapshot) -> Void,
        onReachability: @escaping @MainActor (Bool) -> Void
    )

    /// Send one thing the resident did. Delivery is at-least-once and the
    /// phone deduplicates on `commandID`.
    func send(_ command: WatchCommand)
}
