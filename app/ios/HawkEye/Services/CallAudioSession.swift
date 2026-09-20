import AVFoundation
import TwilioVoice

/// The resident's own audio leg of the 911 call, per `app/CLAUDE.md`'s "Joining
/// the call" section: in-app WebRTC audio, not a phone call, no CallKit, and the
/// phone must never render the operator's voice by accident.
///
/// This wraps `TwilioVoiceSDK.connect` end to end. It is deliberately the only
/// file in the app that imports `TwilioVoice` — `LiveHawkEyeClient` drives it
/// through the four methods below and never touches the SDK directly, which
/// keeps this the one seam to update if the SDK's surface changes again.
///
/// **Verified against the resolved package.** The exact `CallDelegate` method
/// names/signatures and the `Call.isMuted` / `disconnect()` surface below were
/// checked against `TVOCallDelegate.h`, `TVOCall.h`, `TwilioVoice.h` and
/// `TVOConnectOptions.h` from `twilio-voice-ios` 6.13.7 (the version
/// `project.yml` pins), not guessed from the task brief's sketch. What was not
/// verified is a live device/simulator connect — that needs an actual
/// `access_token` from a configured Twilio project and a running conference,
/// neither of which exists in this environment.
@MainActor
final class CallAudioSession: NSObject {
    private var activeCall: Call?

    /// Joins the conference as a live audio leg. Both switches start off —
    /// muted, and with output silenced — matching "hold the WebRTC leg open
    /// from the start of the call with both switches off" in `app/CLAUDE.md`,
    /// so mode changes afterward are one bit flipped rather than a fresh
    /// connect.
    func join(accessToken: String) async throws {
        setOutputSilenced(true)
        // No `builder.uuid` here on purpose: that property is CallKit's hook,
        // and app/CLAUDE.md is explicit that this leg skips CallKit so it
        // never presents as a phone call with a connect tone and call UI.
        let connectOptions = ConnectOptions(accessToken: accessToken) { _ in }
        activeCall = TwilioVoiceSDK.connect(options: connectOptions, delegate: self)
        activeCall?.isMuted = true
    }

    func leave() {
        activeCall?.disconnect()
        activeCall = nil
        setOutputSilenced(true)
    }

    /// The mic switch. `LiveHawkEyeClient` calls this whenever
    /// `participationMode` changes: muted in `.watching`, open in `.whisper`
    /// and `.fullVoice` — mirroring `Bridge.leg_state(Leg.RESIDENT)`'s send
    /// flag on the Python side.
    func setMuted(_ muted: Bool) {
        activeCall?.isMuted = muted
    }

    /// The output switch, and the redundant one. Per `app/CLAUDE.md`: "Silence
    /// is enforced server-side: if the bridge never transmits audio to the
    /// phone, there is nothing for iOS to play" — but whisper mode's whole
    /// point is that a hiding resident's safety depends on that being true, so
    /// this does not simply trust the bridge's `coaching` flag. Swapping the
    /// audio session's category to `.record` removes the output route at the
    /// OS level: even if a bridge bug transmitted audio, there is no route for
    /// it to play on, the same way there is nothing to render when the app
    /// never subscribes to an inbound track at all.
    ///
    /// Best-effort: if the OS refuses the category change mid-call (it can,
    /// per `AVAudioSession.setCategory`'s documented error cases), the mic
    /// switch and the bridge's own send/receive flags remain the two other
    /// layers of defense; this is not the only one.
    func setOutputSilenced(_ silenced: Bool) {
        let session = AVAudioSession.sharedInstance()
        do {
            if silenced {
                // `.voiceChat` mode is only a valid combination with
                // `.playAndRecord` (Apple's documented category/mode
                // compatibility table), so the silenced branch drops to
                // `.default` — the mode is incidental here; the category is
                // what removes the output route.
                try session.setCategory(.record, mode: .default)
            } else {
                try session.setCategory(
                    .playAndRecord,
                    mode: .voiceChat,
                    options: [.allowBluetoothHFP, .allowBluetoothA2DP]
                )
            }
        } catch {
            NSLog("CallAudioSession: could not set output-silenced=%@: %@", String(silenced), error.localizedDescription)
        }
    }
}

// `TVOCallDelegate`'s methods are declared nonisolated by the (Objective-C,
// unaudited-for-concurrency) SDK, while this whole type is `@MainActor`. The
// docs for `TVOCallOptionsBuilder.delegateQueue` say `nil` (the default, and
// what `join(accessToken:)` uses) means callbacks land on the main queue
// anyway, so `@preconcurrency` here is asserting a guarantee the SDK's own
// documentation already makes, not papering over an actual race.
extension CallAudioSession: @preconcurrency CallDelegate {
    func callDidConnect(call: Call) {}

    func callDidFailToConnect(call: Call, error: Error) {
        NSLog("CallAudioSession: failed to connect: %@", error.localizedDescription)
        activeCall = nil
    }

    func callDidDisconnect(call: Call, error: Error?) {
        activeCall = nil
    }
}
