import Foundation

/// The real feed: snapshots relayed from the phone over WatchConnectivity.
///
/// Thin on purpose. `WatchSessionLink` owns the transport and `WatchRouter`
/// owns the rule, so what is left here is decoding and a hop onto the main
/// actor.
@MainActor
final class LiveWatchFeed: WatchFeed {

    private var link: WatchSessionLink?

    func start(
        onSnapshot: @escaping @MainActor (WatchSnapshot) -> Void,
        onReachability: @escaping @MainActor (Bool) -> Void
    ) {
        let link = WatchSessionLink(
            role: .watch,
            onPayload: { data in
                // WatchConnectivity's queue. Decoding is pure; state is not, so
                // it hops before it touches anything.
                guard let snapshot = try? WatchWire.decode(WatchSnapshot.self, from: data) else { return }
                Task { @MainActor in onSnapshot(snapshot) }
            },
            onReachability: { reachable in
                Task { @MainActor in onReachability(reachable) }
            }
        )
        self.link = link
        link.activate()
    }

    func send(_ command: WatchCommand) {
        guard let data = try? WatchWire.encode(command) else { return }
        link?.send(data)
    }
}
