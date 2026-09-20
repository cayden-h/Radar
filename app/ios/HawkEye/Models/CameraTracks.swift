import CoreGraphics
import Foundation

/// The detector's boxes, and who the resident has vouched for.
///
/// Mirrors `app/backend/hawkeye_backend/models/camera.py` field for field; that
/// file is the authority and this follows it.
///
/// **Polled, not pushed, and deliberately so.** The hub's own note on
/// `POST /camera/tracks` is the reason: boxes arrive at camera rate, and
/// putting them on `WS /v1/stream` would bury an incident under several hundred
/// geometry messages a minute. The phone asks for these only while it is
/// actually drawing the camera panel.

/// One person the tracker is holding, normalised to 0..1 of the frame.
///
/// Normalised rather than in pixels, so the same numbers draw correctly on a
/// watch thumbnail, a phone and a browser, and so this camera's resolution is
/// not a hidden assumption in the app.
struct TrackBox: Decodable, Sendable, Hashable, Identifiable {
    var trackID: Int
    var x1: Double
    var y1: Double
    var x2: Double
    var y2: Double
    var confidence: Double

    var id: Int { trackID }

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case x1, y1, x2, y2, confidence
    }
}

/// A resident vouching for the person inside one box.
///
/// **Not recognition, and the app must never draw it as recognition.** `name`
/// is what a human typed. Nothing matched a face, a voice or a device against
/// anything: see `app/backend/hawkeye_backend/edge/vouch.py`.
struct PersonVouch: Decodable, Sendable, Hashable, Identifiable {
    var trackID: Int
    var name: String
    var vouchedAt: Date
    var lastSeenAt: Date

    /// True while the tracker still holds this id. False means the person is
    /// out of frame and the vouch is inside its grace window, which the overlay
    /// draws differently because it is a different statement about the room.
    var held: Bool

    var id: Int { trackID }

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case vouchedAt = "vouched_at"
        case lastSeenAt = "last_seen_at"
        case name, held
    }
}

/// One poll of `GET /v1/camera/tracks`.
struct TracksSnapshot: Decodable, Sendable, Hashable {
    var tracks: [TrackBox] = []
    var vouches: [PersonVouch] = []
    var at: Date = .distantPast

    static let empty = TracksSnapshot()

    /// The vouch on a given box, if there is one.
    func vouch(for trackID: Int) -> PersonVouch? {
        vouches.first { $0.trackID == trackID }
    }
}

// MARK: - Where a box lands on screen

extension TrackBox {

    /// Map this box onto the rect the *image* occupies inside a view.
    ///
    /// **This is the one piece of real geometry in the feature and it is the
    /// easy thing to get wrong.** The camera is 16:9, the panel is 4:3, and
    /// `CameraFeedView` draws with `.aspectRatio(contentMode: .fit)`, so the
    /// picture is letterboxed inside its bounds. Multiplying a normalised
    /// coordinate by the *view's* size puts every box in the wrong place, off
    /// by the size of the letterbox bars, and it does so subtly enough to look
    /// like tracker drift rather than a bug in this file.
    ///
    /// So it is `imageRect` that matters, not the view's bounds, and
    /// `TrackBox.fittedRect(for:in:)` below is what computes it.
    func rect(in imageRect: CGRect) -> CGRect {
        CGRect(
            x: imageRect.minX + x1 * imageRect.width,
            y: imageRect.minY + y1 * imageRect.height,
            width: (x2 - x1) * imageRect.width,
            height: (y2 - y1) * imageRect.height
        )
    }

    /// Where a `.fit` image of `imageSize` actually sits inside `bounds`.
    ///
    /// Pure, and tested as such. Returns `.zero` for a degenerate size rather
    /// than dividing by it: a view laid out at zero height for one frame during
    /// a transition must not produce NaN coordinates that then propagate into
    /// every box's geometry.
    static func fittedRect(for imageSize: CGSize, in bounds: CGSize) -> CGRect {
        guard imageSize.width > 0, imageSize.height > 0,
              bounds.width > 0, bounds.height > 0
        else { return .zero }

        let scale = min(bounds.width / imageSize.width, bounds.height / imageSize.height)
        let size = CGSize(width: imageSize.width * scale, height: imageSize.height * scale)
        return CGRect(
            x: (bounds.width - size.width) / 2,
            y: (bounds.height - size.height) / 2,
            width: size.width,
            height: size.height
        )
    }
}

/// `POST /v1/camera/vouch` body.
struct VouchRequest: Encodable, Sendable, Hashable {
    var trackID: Int
    var name: String

    enum CodingKeys: String, CodingKey {
        case trackID = "track_id"
        case name
    }
}
