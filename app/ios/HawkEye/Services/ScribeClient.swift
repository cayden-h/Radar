import AVFoundation
import Foundation

/// Speech-to-text for the "what is happening" box's mic button.
///
/// POSTs recorded resident audio to ElevenLabs Scribe and returns the
/// transcribed text. **Voice does not skip review**: the text this returns
/// still lands in the same editable field as anything typed by hand, and
/// still goes through `HawkEyeClienting.injectContext(text:speakOnCall:)`
/// only when the resident taps send. Per `app/CLAUDE.md`'s untrusted-input
/// rules, what reaches `master` is context, never instruction, whether it
/// arrived by keyboard or by voice.
struct ScribeClient {

    enum ScribeError: Error, LocalizedError {
        case missingAPIKey
        case badResponse
        case http(Int, String)

        var errorDescription: String? {
            switch self {
            case .missingAPIKey:
                "No ElevenLabs API key is configured. See `Config.elevenLabsScribeAPIKey`."
            case .badResponse:
                "Scribe returned something this app could not read."
            case .http(let code, let body):
                "Scribe request failed (\(code)): \(body)"
            }
        }
    }

    /// Supplied at runtime — see `Config.elevenLabsScribeAPIKey`. **Never
    /// hardcoded.** This app has no other secret-delivery mechanism to reuse
    /// (no keychain-backed config, no bundled secrets file), so the key is
    /// read from the process environment by default and can be overridden by
    /// passing one explicitly, e.g. from a local, gitignored source.
    var apiKey: String = Config.elevenLabsScribeAPIKey
    var endpoint: URL = Config.scribeEndpoint

    private let session = URLSession(configuration: .default)

    /// POSTs `audio` (m4a/AAC, as produced by `ResidentMicRecorder`) to
    /// ElevenLabs' speech-to-text endpoint and returns the transcribed text,
    /// trimmed.
    func transcribe(_ audio: Data) async throws -> String {
        guard !apiKey.isEmpty else { throw ScribeError.missingAPIKey }

        let boundary = "hawkeye-scribe-\(UUID().uuidString)"
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = Self.multipartBody(audio: audio, boundary: boundary)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw ScribeError.badResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw ScribeError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }

        struct ScribeResponse: Decodable { var text: String }
        let decoded = try JSONDecoder().decode(ScribeResponse.self, from: data)
        return decoded.text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// `multipart/form-data` with one `model_id` field and the audio file,
    /// matching ElevenLabs' speech-to-text upload shape.
    private static func multipartBody(audio: Data, boundary: String) -> Data {
        var body = Data()

        func appendString(_ string: String) {
            body.append(Data(string.utf8))
        }

        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"model_id\"\r\n\r\n")
        appendString("scribe_v1\r\n")

        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"file\"; filename=\"context.m4a\"\r\n")
        appendString("Content-Type: audio/m4a\r\n\r\n")
        body.append(audio)
        appendString("\r\n")

        appendString("--\(boundary)--\r\n")
        return body
    }
}

/// Records the resident's mic input to a temporary m4a file, for
/// `ScribeClient.transcribe(_:)`.
///
/// Owned by the mic button on `IncidentView`'s "what is happening" box, per
/// `app/CLAUDE.md`: this is the box that doubles as typed takeover in silent
/// mode, and its friction is a single tap — being heard, or in this case
/// captured by the app's own mic, is low-harm if triggered by accident,
/// unlike anything that opens the resident's mic to the 911 call itself.
///
/// **Feedback here is visual only, no haptics**, matching the app's silent-
/// mode rule that a confirmation must never buzz.
@MainActor
final class ResidentMicRecorder {
    private var recorder: AVAudioRecorder?
    private var fileURL: URL?

    var isRecording: Bool { recorder?.isRecording ?? false }

    /// Requests microphone permission if needed, then starts recording to a
    /// temporary file. Throws if permission is denied or the recorder could
    /// not be created.
    func start() async throws {
        guard await Self.requestPermission() else {
            throw ScribeClient.ScribeError.http(0, "Microphone access was not granted.")
        }

        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .default)
        try session.setActive(true)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("hawkeye-context-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.record()
        self.recorder = recorder
        self.fileURL = url
    }

    /// Stops the recording and returns the captured audio, deleting the
    /// temporary file. Returns `nil` if nothing was recording.
    @discardableResult
    func stop() -> Data? {
        recorder?.stop()
        recorder = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        guard let fileURL else { return nil }
        defer {
            try? FileManager.default.removeItem(at: fileURL)
            self.fileURL = nil
        }
        return try? Data(contentsOf: fileURL)
    }

    private static func requestPermission() async -> Bool {
        await withCheckedContinuation { continuation in
            AVAudioApplication.requestRecordPermission { granted in
                continuation.resume(returning: granted)
            }
        }
    }
}
