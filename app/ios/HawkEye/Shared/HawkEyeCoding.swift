import Foundation

/// The one JSON coder configuration in the app.
///
/// Lives in `Shared/` rather than beside the hub client because the watch
/// target encodes the same types over WatchConnectivity and two copies of a
/// date strategy is how they drift.
enum HawkEyeCoding {

    /// The hub emits RFC 3339 UTC with microsecond precision, e.g.
    /// `2026-09-20T04:12:33.843012Z`. `JSONDecoder.iso8601` rejects fractional
    /// seconds outright, so both shapes are parsed here rather than discovering
    /// it at 3am against a live hub.
    static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            if let date = try? fractional.parse(text) { return date }
            if let date = try? plain.parse(text) { return date }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Not an ISO 8601 timestamp: \(text)"
            )
        }
        return d
    }

    static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(fractional.format(date))
        }
        return e
    }

    /// `Date.ISO8601FormatStyle` is a value type and `Sendable`, unlike
    /// `ISO8601DateFormatter`, so these can be shared across isolation domains
    /// under strict concurrency.
    private static let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
    private static let plain = Date.ISO8601FormatStyle()
}
