import XCTest
@testable import Radar

/// The four camera events, decoded through the app's own types from the
/// backend's own generated examples.
///
/// `app/backend/schema/` is produced by `tools/gen_schema.py` from the live
/// Pydantic models, so it cannot drift from the code that emits these frames.
/// Decoding those exact bytes here is what keeps the two halves of the wire
/// honest with each other.
///
/// This test exists because of a real failure. The app's decoder used to throw
/// on an unknown `kind`, and `LiveHawkEyeClient.apply` turns an undecodable
/// frame into `missedFrames = true`. The moment the hub started publishing a
/// thumbnail once a second, every phone would have sat in a permanent "you may
/// be behind" state, for a reason that was not true.
final class CameraEventDecodingTests: XCTestCase {

    /// Reads a generated example out of `app/backend/schema/`.
    ///
    /// Walks up from this file rather than using a bundle resource, because the
    /// point is to read the backend's real output and not a copy of it that can
    /// go stale.
    private func envelope(_ name: String) throws -> Envelope {
        let here = URL(fileURLWithPath: #filePath)
        let root = here
            .deletingLastPathComponent()   // HawkEyeTests
            .deletingLastPathComponent()   // ios
            .deletingLastPathComponent()   // app
        let url = root
            .appendingPathComponent("backend/schema")
            .appendingPathComponent(name)
        let outer = try JSONSerialization.jsonObject(
            with: Data(contentsOf: url)
        ) as? [String: Any]
        let example = try XCTUnwrap(outer?["example"], "\(name) has no example")
        let data = try JSONSerialization.data(withJSONObject: example)
        return try HawkEyeCoding.decoder.decode(Envelope.self, from: data)
    }

    func testAFrameDecodesAndCarriesItsLiveFlag() throws {
        guard case .frame(let frame) = try envelope("event-frame.json").payload else {
            return XCTFail("expected a frame")
        }
        XCTAssertTrue(frame.live)
        XCTAssertEqual(frame.room, "Living room")
        XCTAssertFalse(frame.jpeg.isEmpty, "base64 must decode to bytes")
    }

    func testNarrationDecodesWithItsScopeAndWindow() throws {
        guard case .narration(let line) = try envelope("event-narration.json").payload else {
            return XCTFail("expected narration")
        }
        // Both limits are required fields rather than comments: one fixed
        // camera sees one room, and the model samples about once a second.
        XCTAssertEqual(line.room, "Living room")
        XCTAssertGreaterThan(line.windowSeconds, 0)
    }

    func testOccupancyDecodes() throws {
        guard case .occupancy(let value) = try envelope("event-occupancy.json").payload else {
            return XCTFail("expected occupancy")
        }
        XCTAssertTrue(value.personPresent)
        XCTAssertEqual(value.people, 1)
    }

    func testAnOpenShieldDecodesAsCommandedNeverMeasured() throws {
        guard case .shield(let shield) = try envelope("event-shield.json").payload else {
            return XCTFail("expected a shield report")
        }
        XCTAssertFalse(shield.refused)
        XCTAssertEqual(shield.state, .open)
        // The SG92R is open-loop. If this ever reads `measured`, something has
        // started claiming a position it cannot know.
        XCTAssertEqual(shield.positionBasis, "commanded")
        XCTAssertEqual(shield.commandedAngle, 90)
    }

    func testARefusedShieldDecodesAsRefusedAndKeepsItsRealPosition() throws {
        guard case .shield(let shield) = try envelope("event-shield-refused.json").payload else {
            return XCTFail("expected a shield report")
        }
        XCTAssertTrue(shield.refused)
        XCTAssertEqual(shield.state, .refused)
        // A refusal means the shield did not move and the shutter still knows
        // where it is. `unknown` there would throw away a true fact.
        XCTAssertEqual(shield.position, "closed")
        XCTAssertTrue(shield.refusalReason.contains("unregistered_issuer"))
    }

    func testAnUnknownKindIsToleratedRatherThanThrown() throws {
        // Forward compatibility. A hub that learns a new event must not degrade
        // every older client, and this is the regression that reaches for.
        let json = """
        {"seq": 9, "at": "2026-09-20T04:12:43Z", "incident_id": null,
         "payload": {"kind": "something_this_build_has_never_heard_of"}}
        """
        let envelope = try HawkEyeCoding.decoder.decode(
            Envelope.self, from: Data(json.utf8)
        )
        guard case .unrecognised(let kind) = envelope.payload else {
            return XCTFail("an unknown kind must decode as .unrecognised, not throw")
        }
        XCTAssertEqual(kind, "something_this_build_has_never_heard_of")
    }

    func testTheKnownKindsListMatchesWhatTheDecoderHandles() throws {
        // The list exists only to tell "newer hub" apart from "broken frame",
        // so it going stale is silent. This is the reminder.
        for kind in HubEvent.knownKinds where kind != "hello" {
            let json = #"{"seq":1,"at":"2026-09-20T04:12:43Z","payload":{"kind":"\#(kind)"}}"#
            let decoded = try? HawkEyeCoding.decoder.decode(
                Envelope.self, from: Data(json.utf8)
            )
            // A known kind either decodes, or fails on its missing body. What it
            // must never do is come back as `.unrecognised`.
            if case .unrecognised = decoded?.payload {
                XCTFail("\(kind) is listed as known but the decoder does not handle it")
            }
        }
    }
}

/// The closed sets on both sides of the wire, checked against each other.
///
/// `Provenance.Source` is a closed set mirrored from `schema/enums.json`, and a
/// mirror nobody checks is a mirror that drifts. It did: the camera pivot added
/// three values on 2026-09-19 and the Swift side did not get them until the day
/// after, so every frame, narration line and occupancy verdict failed to decode
/// with "Cannot initialize Source from invalid String value camera-uvc".
final class EnumMirrorTests: XCTestCase {

    func testEverySourceTheBackendCanEmitDecodesHere() throws {
        let here = URL(fileURLWithPath: #filePath)
        let root = here
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let url = root.appendingPathComponent("backend/schema/enums.json")
        let json = try JSONSerialization.jsonObject(with: Data(contentsOf: url))
        let values = try XCTUnwrap(
            (json as? [String: Any])?["source"] as? [String],
            "enums.json has no source list"
        )
        XCTAssertFalse(values.isEmpty)

        let known = Set(Provenance.Source.allCases.map(\.rawValue))
        let missing = values.filter { !known.contains($0) }
        XCTAssertTrue(
            missing.isEmpty,
            "the backend can emit sources this app cannot decode: \(missing.sorted())"
        )
    }
}
