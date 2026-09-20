import SwiftUI
import WatchKit

/// Hawk Eye on the wrist.
///
/// The actor, not the record. It gets the notification and it is where an
/// incident is started; the footage, the transcript, the roster and the sealed
/// log all stay on the phone, which has a screen for them.
///
/// It is a phone-paired companion and never speaks to the hub. That is a
/// deployment property rather than an architectural one: a standalone watch app
/// would survive the phone being out of range, and would also need Bonjour
/// discovery, its own socket, and its own connection state machine on a
/// platform with an aggressive background policy.
@main
struct HawkEyeWatchApp: App {
    var body: some Scene {
        WindowGroup {
            WatchRootView()
        }

        // The custom long look. Without this scene a notice still arrives, it
        // just renders as the plain system alert with the sentence as body
        // text and the frame as an attachment thumbnail.
        WKNotificationScene(
            controller: NoticeNotificationController.self,
            category: NoticeNotifier.category
        )
    }
}
