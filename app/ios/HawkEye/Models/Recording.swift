import Foundation

/// A saved recording of an incident: interior activity and the 911 call,
/// timestamped together against one timeline.
///
/// **Front-end only, for now.** There is no camera and no microphone in this
/// system — Hawk Eye senses through CSI, per the root `CLAUDE.md` — so what
/// this screen calls "video" is the interior view's activity plus the call
/// transcript, not a camera feed. Nothing here is wired to a capture
/// pipeline, storage, or a backend yet; `Recording.samples` below is the
/// entire data source. Wiring this to `agents/replay`'s sealed log — the
/// thing that actually seals an incident's record — is future work.
struct Recording: Identifiable, Hashable {
    var id: String
    var incidentType: IncidentType
    var startedAt: Date
    var duration: TimeInterval
    /// One line, factual, no diagnosis: what was classified and how it
    /// resolved. Stands in for the AI summary a real pipeline would produce.
    var summary: String
    var transcript: [TranscriptLine]

    var endedAt: Date { startedAt.addingTimeInterval(duration) }
}

extension Recording {
    /// Placeholder library, shown until a real recording pipeline exists.
    static let samples: [Recording] = [
        Recording(
            id: "rec-burglary-01",
            incidentType: .burglary,
            startedAt: Calendar.current.date(byAdding: .day, value: -2, to: .now) ?? .now,
            duration: 268,
            summary: "An unexpected person was tracked from the living room through the kitchen toward the main bedroom while the resident was confirmed present and moving. Radar placed a verified call to 911; the operator dispatched a unit to the address on file.",
            transcript: [
                TranscriptLine(lineID: "t1", incidentID: "rec-burglary-01", speaker: .system, text: "Call connected.", at: .now),
                TranscriptLine(lineID: "t2", incidentID: "rec-burglary-01", speaker: .operatorVoice, text: "911, what is the address of your emergency?", at: .now),
                TranscriptLine(lineID: "t3", incidentID: "rec-burglary-01", speaker: .caller, text: "This is an automated call from a monitoring system at 1872 Ridgeview Lane, Blacksburg VA 24060. An unexpected person has been tracked inside the home.", at: .now),
                TranscriptLine(lineID: "t4", incidentID: "rec-burglary-01", speaker: .operatorVoice, text: "Is the resident able to get to a safe room?", at: .now),
                TranscriptLine(lineID: "t5", incidentID: "rec-burglary-01", speaker: .caller, text: "The resident is confirmed moving in the main bedroom, on the opposite side of the unit from the unexpected presence.", at: .now),
            ]
        ),
        Recording(
            id: "rec-fire-01",
            incidentType: .fire,
            startedAt: Calendar.current.date(byAdding: .day, value: -9, to: .now) ?? .now,
            duration: 194,
            summary: "Elevated CO was reported while both residents were confirmed present and moving. Radar placed a verified call to 911 and relayed room-by-room status for the duration of the call.",
            transcript: [
                TranscriptLine(lineID: "t1", incidentID: "rec-fire-01", speaker: .system, text: "Call connected.", at: .now),
                TranscriptLine(lineID: "t2", incidentID: "rec-fire-01", speaker: .operatorVoice, text: "911, what is the address of your emergency?", at: .now),
                TranscriptLine(lineID: "t3", incidentID: "rec-fire-01", speaker: .caller, text: "This is an automated call from a monitoring system at 1872 Ridgeview Lane, Blacksburg VA 24060. Elevated carbon monoxide has been detected.", at: .now),
                TranscriptLine(lineID: "t4", incidentID: "rec-fire-01", speaker: .operatorVoice, text: "Are all occupants able to evacuate?", at: .now),
                TranscriptLine(lineID: "t5", incidentID: "rec-fire-01", speaker: .caller, text: "Two residents are confirmed present and moving, in the second bedroom and the hallway.", at: .now),
            ]
        ),
    ]
}
