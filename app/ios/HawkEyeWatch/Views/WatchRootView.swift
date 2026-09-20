import SwiftUI

/// Picks one of three screens from the snapshot, and does nothing else.
///
/// The choice is `WatchRouter`'s, which is a pure function tested without a
/// device. There is no navigation stack and no way to browse: a wrist during an
/// intrusion shows the one thing that matters now, and the resident never has
/// to find their way back.
struct WatchRootView: View {

    @State private var model = WatchModel()

    var body: some View {
        Group {
            switch model.screen {
            case .idle:
                IdleScreen(snapshot: model.snapshot, link: model.link, now: model.now)

            case .notice(let notice):
                NoticeScreen(
                    notice: notice,
                    isSending: model.isSending && !model.deliveryFailed,
                    deliveryFailed: model.deliveryFailed,
                    now: model.now,
                    act: { model.send($0, for: notice) },
                    dismissFailure: { model.clearFailedDelivery() }
                )

            case .saved(let outcome):
                SavedScreen(outcome: outcome, now: model.now)
            }
        }
        .animation(Motion.standard, value: model.screen)
        .containerBackground(for: .navigation) { AmbientBackground() }
        .tint(Palette.calm)
        .onAppear { model.start() }
    }
}
