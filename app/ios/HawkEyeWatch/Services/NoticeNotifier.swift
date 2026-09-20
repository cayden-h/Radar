import Foundation
import UserNotifications
import os

/// The wrist buzz, and the only thing in this app that makes one.
///
/// **These are local notifications, not push.** The phone relays the notice
/// over WatchConnectivity and the watch raises the notification itself, which
/// needs no APNs, no push server and no paid account. `app/CLAUDE.md` says push
/// was considered and not shipped, and that is still true: nothing here talks to
/// Apple's push service.
///
/// The notification is the product. It is the thing that wakes someone who is
/// asleep or in another room, about three seconds after a person walks in, and
/// **it carries the camera's own sentence** rather than "motion detected".
@MainActor
final class NoticeNotifier {

    /// Presents the notice even when the app is already open.
    ///
    /// watchOS suppresses a notification whose app is in the foreground, on the
    /// reasonable assumption that the app is already saying it. Here the
    /// assumption does not hold: the resident may be looking at Idle when the
    /// notice lands, and the notification is the primary path rather than a
    /// duplicate of one. It is also the only way to see the long look without
    /// first putting the watch to sleep.
    private final class ForegroundPresenter: NSObject, UNUserNotificationCenterDelegate {
        func userNotificationCenter(
            _ center: UNUserNotificationCenter,
            willPresent notification: UNNotification
        ) async -> UNNotificationPresentationOptions {
            [.banner, .list]
        }
    }

    private let presenter = ForegroundPresenter()

    /// The category the custom long-look is registered against, in
    /// `HawkEyeWatchApp`'s `WKNotificationScene`. A notification without this
    /// category renders as the plain system look instead.
    static let category = "hawkeye.notice"

    /// The still frames this process has seen, by notice id.
    ///
    /// The long-look controller runs in this same process on watchOS, so it can
    /// read the frame from here rather than having it re-encoded into the
    /// notification payload. That matters for a pushed notification too: a real
    /// APNs payload is capped at 4KB and a usable JPEG is not going to fit.
    private(set) static var frames: [String: Data] = [:]

    static func frame(for noticeID: String) -> Data? { frames[noticeID] }

    private let log = Logger(subsystem: "ai.hawkeye", category: "notifier")

    /// Ask once, at launch. Declined is a legitimate answer and the in-app
    /// Notice screen still works without it.
    func requestAuthorization() async {
        let centre = UNUserNotificationCenter.current()
        centre.delegate = presenter
        centre.setNotificationCategories([
            UNNotificationCategory(
                identifier: Self.category,
                // No action buttons, deliberately. A one-tap "Start Incident"
                // on a notification would bypass the 1.5 second hold, and the
                // hold exists precisely because a wrist is the easiest surface
                // in the world to press by accident. Tapping the notification
                // opens the app, where both controls live with the right
                // protection on each.
                actions: [],
                intentIdentifiers: [],
                options: []
            )
        ])
        do {
            let granted = try await centre.requestAuthorization(options: [.alert, .sound])
            log.info("notification authorization granted=\(granted)")
        } catch {
            log.error("notification authorization failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Raise the notice on the wrist.
    func post(_ notice: WatchNotice) async {
        Self.frames[notice.noticeID] = notice.stillFrame

        let content = UNMutableNotificationContent()
        content.title = "Unexpected person"
        if let room = notice.room { content.subtitle = room }
        // The camera's sentence, verbatim. The whole point of the pivot is that
        // this line is specific, so it is never replaced with a summary.
        content.body = notice.narration
        content.categoryIdentifier = Self.category
        content.userInfo = [
            "notice_id": notice.noticeID,
            "room": notice.room ?? "",
            "simulated": notice.simulated,
        ]
        // Time-sensitive breaks through a Focus. It does not break through
        // silent mode, and it should not: an intrusion is exactly the situation
        // where noise may be unsafe, and the haptic is the part that matters.
        content.interruptionLevel = .timeSensitive

        if let attachment = attachment(for: notice) {
            content.attachments = [attachment]
        }

        let request = UNNotificationRequest(
            identifier: notice.noticeID,
            content: content,
            trigger: nil
        )
        do {
            try await UNUserNotificationCenter.current().add(request)
            log.info("posted notice \(notice.noticeID, privacy: .public)")
        } catch {
            log.error("could not post notice: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// Write the frame somewhere the notification system can read it.
    ///
    /// The custom long-look reads `frames` instead, but the attachment is what
    /// the *system* look shows, and the system look is what appears if the
    /// custom scene ever fails to load.
    private func attachment(for notice: WatchNotice) -> UNNotificationAttachment? {
        guard let jpeg = notice.stillFrame else { return nil }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(notice.noticeID).jpg")
        do {
            try jpeg.write(to: url, options: .atomic)
            return try UNNotificationAttachment(identifier: notice.noticeID, url: url)
        } catch {
            log.error("could not attach frame: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }
}
