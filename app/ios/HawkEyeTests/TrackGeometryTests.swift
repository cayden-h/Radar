import CoreGraphics
import XCTest

@testable import Radar

/// The letterbox arithmetic behind the tappable boxes.
///
/// This is the piece that fails *quietly*. A box positioned against the view's
/// bounds instead of the picture inside them is off by the size of the
/// letterbox bars, which looks like the tracker drifting rather than like bad
/// arithmetic - and it makes the resident tap the wrong person.
final class TrackGeometryTests: XCTestCase {

    /// The real case: a 16:9 camera in the 4:3 panel `CameraFeedView` draws.
    func testWidePictureLetterboxes() {
        let rect = TrackBox.fittedRect(
            for: CGSize(width: 1920, height: 1080),
            in: CGSize(width: 400, height: 300)
        )

        XCTAssertTrue(rect.width == 400)
        XCTAssertTrue(rect.height == 225)
        // Centred, so the bars are equal. 300 - 225 = 75, half above.
        XCTAssertTrue(rect.minY == 37.5)
        XCTAssertTrue(rect.minX == 0)
    }

    func testTallPicturePillarboxes() {
        let rect = TrackBox.fittedRect(
            for: CGSize(width: 1080, height: 1920),
            in: CGSize(width: 400, height: 300)
        )

        XCTAssertTrue(rect.height == 300)
        XCTAssertTrue(rect.width.rounded() == 169)
        XCTAssertTrue(rect.minY == 0)
        XCTAssertTrue(rect.minX > 0)
    }

    func testMatchingAspectFills() {
        let rect = TrackBox.fittedRect(
            for: CGSize(width: 800, height: 600),
            in: CGSize(width: 400, height: 300)
        )

        XCTAssertTrue(rect == CGRect(x: 0, y: 0, width: 400, height: 300))
    }

    /// SwiftUI lays a view out at zero for a frame during some transitions.
    /// Dividing by it would put NaN into every box's position, and NaN
    /// coordinates propagate silently instead of crashing.
    func testDegenerateSizeIsSafe() {
        let noBounds = TrackBox.fittedRect(for: CGSize(width: 1920, height: 1080), in: .zero)
        let noImage = TrackBox.fittedRect(for: .zero, in: CGSize(width: 400, height: 300))

        XCTAssertTrue(noBounds == .zero)
        XCTAssertTrue(noImage == .zero)
    }

    /// The whole point: a box is placed against the *picture*, not the view.
    func testBoxLandsOnThePicture() {
        let image = TrackBox.fittedRect(
            for: CGSize(width: 1920, height: 1080),
            in: CGSize(width: 400, height: 300)
        )
        let box = TrackBox(trackID: 1, x1: 0, y1: 0, x2: 1, y2: 1, confidence: 1)

        let drawn = box.rect(in: image)

        // A full-frame box covers the picture and neither of the bars.
        XCTAssertTrue(drawn == image)
        XCTAssertTrue(drawn.minY == 37.5)
    }

    func testHalfWidthBox() {
        let image = TrackBox.fittedRect(
            for: CGSize(width: 1920, height: 1080),
            in: CGSize(width: 400, height: 300)
        )
        let box = TrackBox(trackID: 1, x1: 0.5, y1: 0.0, x2: 1.0, y2: 0.5, confidence: 1)

        let drawn = box.rect(in: image)

        XCTAssertTrue(drawn.minX == 200)
        XCTAssertTrue(drawn.width == 200)
        // Offset by the top bar, which is exactly what using the view's bounds
        // would have got wrong.
        XCTAssertTrue(drawn.minY == 37.5)
        XCTAssertTrue(drawn.height == 112.5)
    }

    func testVouchLookupIsPerBox() {
        let snapshot = TracksSnapshot(
            tracks: [],
            vouches: [
                PersonVouch(
                    trackID: 3,
                    name: "Jordan",
                    vouchedAt: .now,
                    lastSeenAt: .now,
                    held: true
                )
            ],
            at: .now
        )

        XCTAssertTrue(snapshot.vouch(for: 3)?.name == "Jordan")
        XCTAssertTrue(snapshot.vouch(for: 7) == nil)
    }
}
