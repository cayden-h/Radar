import Foundation
import Observation
import os

/// Reads `GET /v1/camera/live`, the hub's `multipart/x-mixed-replace` MJPEG.
///
/// The root `CLAUDE.md` splits the camera three ways on purpose: full-rate
/// MJPEG for the phone and the browser, a 1 Hz thumbnail on the event stream
/// for the watch, and a single still on demand. This is the phone's half. The
/// thumbnail already reaches `HawkEyeClienting.cameraFrame` and stays the
/// fallback, because one frame a second is a true picture of the room and a
/// blank panel is not.
///
/// ## Why a delegate and not `URLSession.bytes`
///
/// `AsyncBytes` yields one `UInt8` at a time. A 720p MJPEG frame is about 40KB
/// and the hub pushes them as fast as the camera produces them, so the
/// per-element overhead turns the decode loop into the bottleneck and the feed
/// falls behind the room it is showing. A data-task delegate hands over whole
/// chunks and the scan below runs over them in one pass.
///
/// ## Why it scans for JPEG markers rather than parsing the boundary
///
/// The multipart boundary is declared in the response's Content-Type and is
/// free to change between hubs and between versions. `0xFFD8` and `0xFFD9` are
/// the JPEG start- and end-of-image markers and are fixed by the format itself.
/// Scanning for them decodes every MJPEG server the same way, and it cannot be
/// broken by a header change on the hub.
@MainActor
@Observable
final class MJPEGStream {

    /// The newest complete frame, or nil before the first one arrives.
    private(set) var frame: Data?

    /// Set when the stream stopped for a reason worth telling the resident
    /// about. **The view must not draw `frame` as current while this is set**:
    /// the last frame received is still the last thing the camera saw, which is
    /// exactly the stale picture this project refuses to present as live.
    private(set) var failed: String?

    /// True between `start` and the first frame, so a view can say it is
    /// connecting rather than implying an empty room.
    private(set) var connecting = false

    @ObservationIgnored private var session: URLSession?
    @ObservationIgnored private var task: URLSessionDataTask?
    @ObservationIgnored private var currentURL: URL?

    private static let log = Logger(subsystem: "ai.hawkeye", category: "mjpeg")

    // MARK: Lifecycle

    /// Idempotent for the same URL, so a SwiftUI body that runs twice does not
    /// open two sockets against one camera.
    func start(url: URL) {
        if currentURL == url, task != nil { return }
        stop()
        currentURL = url
        connecting = true
        failed = nil

        let parser = FrameParser { [weak self] jpeg in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.frame = jpeg
                self.connecting = false
                self.failed = nil
            }
        } onFailure: { [weak self] message in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.connecting = false
                self.failed = message
            }
        }

        // No caching, and a long timeout: this response never completes by
        // design, so the default 60s resource timeout would tear down a
        // perfectly healthy feed once a minute.
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        config.timeoutIntervalForResource = .infinity
        config.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData

        let session = URLSession(configuration: config, delegate: parser, delegateQueue: nil)
        self.session = session
        task = session.dataTask(with: url)
        task?.resume()
        Self.log.info("mjpeg: opening \(url.absoluteString, privacy: .public)")
    }

    func stop() {
        task?.cancel()
        task = nil
        session?.invalidateAndCancel()
        session = nil
        currentURL = nil
        connecting = false
    }

    // MARK: The parser

    /// Lives on `URLSession`'s delegate queue, never on the main actor, and owns
    /// the only mutable buffer. `@unchecked Sendable` is accurate rather than a
    /// shortcut: `URLSession` serializes delegate callbacks for one task onto
    /// one queue, so `buffer` is touched by one thread at a time.
    private final class FrameParser: NSObject, URLSessionDataDelegate, @unchecked Sendable {

        /// Start-of-image and end-of-image, fixed by the JPEG format.
        private static let soi: [UInt8] = [0xFF, 0xD8]
        private static let eoi: [UInt8] = [0xFF, 0xD9]

        /// A frame that never terminates must not grow without bound. 16MB is
        /// far past any plausible 4K JPEG, so hitting it means the stream is
        /// not what it claims to be and the buffer is dropped rather than
        /// grown until the app is killed for memory.
        private static let bufferLimit = 16 * 1024 * 1024

        private var buffer = Data()
        private let onFrame: @Sendable (Data) -> Void
        private let onFailure: @Sendable (String) -> Void

        init(
            onFrame: @escaping @Sendable (Data) -> Void,
            onFailure: @escaping @Sendable (String) -> Void
        ) {
            self.onFrame = onFrame
            self.onFailure = onFailure
        }

        func urlSession(
            _ session: URLSession,
            dataTask: URLSessionDataTask,
            didReceive response: URLResponse,
            completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
        ) {
            guard let http = response as? HTTPURLResponse else {
                completionHandler(.allow)
                return
            }
            // 503 is the hub saying it has no frame and why, which is a real
            // answer and not a failure of this client. Surface its meaning
            // rather than a status code.
            if http.statusCode == 503 {
                onFailure("The hub has no camera attached right now.")
                completionHandler(.cancel)
                return
            }
            guard (200..<300).contains(http.statusCode) else {
                onFailure("The camera feed answered \(http.statusCode).")
                completionHandler(.cancel)
                return
            }
            completionHandler(.allow)
        }

        func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
            buffer.append(data)
            if buffer.count > Self.bufferLimit {
                buffer.removeAll(keepingCapacity: false)
                return
            }
            drainFrames()
        }

        /// Emits every complete JPEG sitting in the buffer and keeps the tail.
        ///
        /// Draining in a loop rather than emitting once matters when a chunk
        /// carries more than one frame: keeping only the first would make the
        /// feed run progressively further behind the room.
        private func drainFrames() {
            while true {
                guard
                    let start = buffer.firstRange(of: Self.soi),
                    let end = buffer.firstRange(of: Self.eoi, in: start.upperBound..<buffer.endIndex)
                else { return }
                onFrame(buffer.subdata(in: start.lowerBound..<end.upperBound))
                buffer.removeSubrange(buffer.startIndex..<end.upperBound)
            }
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
            guard let error else {
                onFailure("The camera feed ended.")
                return
            }
            // A cancel is this app closing the stream on purpose, so it is not
            // something to tell the resident about.
            if (error as NSError).code == NSURLErrorCancelled { return }
            onFailure("The camera feed dropped: \(error.localizedDescription)")
        }
    }
}
