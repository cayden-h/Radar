import SwiftUI
import UserNotifications
import WatchKit
#if canImport(UIKit)
import UIKit
#endif

/// What the notice actually looks like on the wrist before you tap it.
///
/// This is the long look, and it is the most important screen in the watch app
/// even though it is not one of the three: it is what the resident sees at 3am
/// without touching anything. **It carries the photograph and the camera's
/// sentence**, which is the whole difference the camera pivot bought.
///
/// There are no action buttons. A one-tap Start Incident here would bypass the
/// 1.5 second hold that exists because a wrist is trivially easy to press by
/// accident; tapping the notification opens the app, where the controls live
/// with the right protection on each.
struct NoticeNotificationView: View {

    var payload: NoticeNotificationPayload

    var body: some View {
        ZStack {
            AmbientBackground()

            ScrollView {
                VStack(alignment: .leading, spacing: Space.sm) {

                    HStack(spacing: Space.xs) {
                        Circle()
                            .fill(Palette.personUnexpected)
                            .frame(width: 7, height: 7)
                        Text("Unexpected")
                            .eyebrowStyle(Palette.personUnexpected)
                        Spacer(minLength: 0)
                    }

                    frame

                    Text(payload.narration)
                        .font(.system(size: 14, weight: .medium, design: .rounded))
                        .foregroundStyle(Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(Space.sm)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassPanel(cornerRadius: Radius.sm)

                    Text("Open to answer this.")
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(Palette.inkFaint)
                }
                .padding(.horizontal, Space.sm)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    @ViewBuilder
    private var frame: some View {
        ZStack(alignment: .bottomTrailing) {
            #if canImport(UIKit)
            if let data = payload.stillFrame, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                noFrame
            }
            #else
            noFrame
            #endif

            if payload.simulated {
                Text("SIMULATED")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(Palette.ink.opacity(0.85))
                    .padding(.horizontal, 4)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Palette.ground.opacity(0.75)))
                    .padding(4)
            }
        }
        .aspectRatio(16.0 / 9.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.glassBorder, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.35), radius: 12, y: 6)
    }

    /// No frame means the shield never opened, and saying so is more useful
    /// than a grey rectangle.
    private var noFrame: some View {
        ZStack {
            Rectangle().fill(.ultraThinMaterial.opacity(0.12))
            Rectangle().fill(Palette.glassTint)
            Text("The shield stayed closed.\nThere is no picture.")
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(Palette.inkMuted)
                .multilineTextAlignment(.center)
        }
    }
}

/// One notification, unpacked into what the long look draws.
struct NoticeNotificationPayload: Sendable, Hashable {

    var noticeID: String
    var narration: String
    var room: String?
    var stillFrame: Data?
    var simulated: Bool

    init(
        noticeID: String,
        narration: String,
        room: String? = nil,
        stillFrame: Data? = nil,
        simulated: Bool = false
    ) {
        self.noticeID = noticeID
        self.narration = narration
        self.room = room
        self.stillFrame = stillFrame
        self.simulated = simulated
    }

    @MainActor
    init(notification: UNNotification) {
        let content = notification.request.content
        let info = content.userInfo

        noticeID = info["notice_id"] as? String ?? notification.request.identifier
        narration = content.body
        let room = info["room"] as? String
        self.room = (room?.isEmpty == false) ? room : (content.subtitle.isEmpty ? nil : content.subtitle)
        simulated = info["simulated"] as? Bool ?? false

        // The frame comes from this process first. The long look runs in the
        // app on watchOS, so a notice the relay already delivered has its frame
        // in hand and nothing has to be re-encoded into the payload. The
        // attachment is the fallback, and it is the only path that works for a
        // notification this process did not raise itself, such as one pushed in
        // with `simctl push` while testing.
        if let cached = NoticeNotifier.frame(for: noticeID) {
            stillFrame = cached
        } else {
            stillFrame = Self.attachedFrame(in: content)
        }
    }

    private static func attachedFrame(in content: UNNotificationContent) -> Data? {
        guard let attachment = content.attachments.first else { return nil }
        guard attachment.url.startAccessingSecurityScopedResource() else { return nil }
        defer { attachment.url.stopAccessingSecurityScopedResource() }
        return try? Data(contentsOf: attachment.url)
    }

    /// Shown only in the moment before `didReceive` supplies the real thing.
    static let placeholder = NoticeNotificationPayload(
        noticeID: "",
        narration: "Loading the camera's description."
    )
}

/// Hosts the long look. Registered in `HawkEyeWatchApp`'s `WKNotificationScene`
/// against `NoticeNotifier.category`.
final class NoticeNotificationController: WKUserNotificationHostingController<NoticeNotificationView> {

    private var payload: NoticeNotificationPayload = .placeholder

    override var body: NoticeNotificationView {
        NoticeNotificationView(payload: payload)
    }

    @MainActor
    override func didReceive(_ notification: UNNotification) {
        payload = NoticeNotificationPayload(notification: notification)
    }
}
