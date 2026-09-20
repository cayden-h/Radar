import Foundation
import Observation
#if canImport(WatchKit)
import WatchKit
#endif

/// The watch's only piece of state.
///
/// It holds one snapshot, which the phone authored, and a clock. **It derives,
/// it never decides.** The rule that turns a snapshot into a screen is
/// `WatchRouter`, which is a pure function and is tested as one.
///
/// `app/CLAUDE.md`: the watch must not hold state the phone does not have. The
/// two exceptions here are both about the link rather than about the house:
/// whether the phone is reachable, and whether a command this watch sent has
/// been reflected back yet.
@MainActor
@Observable
final class WatchModel {

    private(set) var snapshot: WatchSnapshot = .unknown
    private(set) var phoneReachable = false

    /// False until the first snapshot lands. Distinguishes "the phone has not
    /// spoken yet" from "the phone says the house is quiet", which look the
    /// same on screen and are not the same fact.
    private(set) var hasHeardFromPhone = false

    /// Ticks once a second so the confirmation screen expires on its own and
    /// the elapsed lines stay honest.
    private(set) var now = Date()

    /// A command this watch sent that the phone has not reflected yet.
    @ObservationIgnored private var inFlight: WatchCommand?
    @ObservationIgnored private var inFlightSentAt: Date?

    @ObservationIgnored private let feed: any WatchFeed
    @ObservationIgnored private let notifier = NoticeNotifier()
    @ObservationIgnored private var clock: Task<Void, Never>?

    init(feed: (any WatchFeed)? = nil) {
        self.feed = feed ?? (WatchConfig.useMockLink ? MockWatchFeed() : LiveWatchFeed())
    }

    func start() {
        Task { await notifier.requestAuthorization() }
        feed.start(
            onSnapshot: { [weak self] snapshot in self?.apply(snapshot) },
            onReachability: { [weak self] reachable in self?.phoneReachable = reachable }
        )
        clock = Task { [weak self] in
            while !Task.isCancelled {
                self?.tick()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    // MARK: Derived

    var screen: WatchScreen { WatchRouter.screen(for: snapshot, now: now) }

    /// What the watch is allowed to say about its own link.
    ///
    /// The phone wins every disagreement, so anything other than `live` means
    /// the watch says it is reconnecting rather than drawing a house it cannot
    /// refresh.
    var link: LinkState {
        if !hasHeardFromPhone { return .connecting }
        if !phoneReachable { return .reconnecting }
        if now.timeIntervalSince(snapshot.generatedAt) > WatchConfig.snapshotStaleAfter {
            return .reconnecting
        }
        return snapshot.hubLinked ? .live : .reconnecting
    }

    /// True while a command is on its way and the phone has not answered.
    /// Purely a link fact: the phone still authors the outcome itself.
    var isSending: Bool { inFlight != nil }

    /// Set when a command was sent and nothing came back in time.
    var deliveryFailed: Bool {
        guard let sentAt = inFlightSentAt else { return false }
        return now.timeIntervalSince(sentAt) > WatchConfig.commandAcknowledgementTimeout
    }

    // MARK: Acting

    func send(_ action: WatchAction, for notice: WatchNotice) {
        guard inFlight == nil else { return }
        let command = WatchCommand(
            commandID: UUID().uuidString,
            noticeID: notice.noticeID,
            action: action,
            issuedAt: Date()
        )
        inFlight = command
        inFlightSentAt = Date()
        feed.send(command)
    }

    /// Give up on a command that never landed, so the control comes back and
    /// the resident can try again. The watch never retries on its own: a second
    /// incident nobody asked for is worse than a button that did nothing.
    func clearFailedDelivery() {
        inFlight = nil
        inFlightSentAt = nil
    }

    /// Raise the notice on the wrist. **It is the only thing that buzzes.**
    ///
    /// That is the whole reason the watch is the notification surface: it wakes
    /// someone who is asleep or in another room. The hold confirmation is
    /// deliberately silent by contrast, because the resident is already looking
    /// at the screen by then and an intrusion is a situation where noise may be
    /// unsafe. See the silent-mode rules in `app/CLAUDE.md`.
    ///
    /// The haptic fires alongside the notification rather than instead of it,
    /// so the wrist still moves when the app happens to be open and the system
    /// therefore suppresses the banner.
    private func announceNotice(_ notice: WatchNotice) {
        #if canImport(WatchKit)
        WKInterfaceDevice.current().play(.notification)
        #endif
        Task { await notifier.post(notice) }
    }

    // MARK: Inbound

    private func apply(_ snapshot: WatchSnapshot) {
        let previousNoticeID = self.snapshot.notice?.noticeID
        self.snapshot = snapshot
        hasHeardFromPhone = true
        now = Date()

        // The phone has reflected the command, so the outcome on screen is now
        // the phone's rather than this watch's guess about it.
        if let inFlight, snapshot.outcome?.commandID == inFlight.commandID {
            self.inFlight = nil
            self.inFlightSentAt = nil
        }

        if let notice = snapshot.notice, notice.noticeID != previousNoticeID {
            announceNotice(notice)
        }
    }

    private func tick() { now = Date() }
}
