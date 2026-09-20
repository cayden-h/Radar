import SwiftUI

/// The call screen. This is the product, per `app/CLAUDE.md`, so it gets the
/// whole display and nothing competes with it.
///
/// Four things, in priority order down the screen:
///
/// 1. What to do, from `agents/guidance`. Nearest the top because it is what
///    the user acts on.
/// 2. A refusal banner whenever a claim was discarded. **A refused claim is
///    never a grey log line.** The refusal path is the submission.
/// 3. The live transcript of `agents/caller` talking to the 911 operator, and
///    the ANS verification feed behind it, on one switch.
/// 4. An always-visible free-text field. Not a disclosure triangle: someone in
///    an emergency will not find one.
struct IncidentView: View {
    @Environment(AppModel.self) private var model
    var incident: Incident

    enum Feed: String, CaseIterable, Identifiable {
        case call, verification
        var id: String { rawValue }
        var title: String {
            switch self {
            case .call: "The call"
            case .verification: "What was verified"
            }
        }
    }

    /// Leaves this screen without ending the call — the transcript, the
    /// operator, and the context field all keep running underneath.
    /// `HomeView` re-presents this same screen via `LiveCallBanner`.
    var onBack: () -> Void
    var onEndCall: () -> Void

    @State private var context: String = ""
    @State private var sending = false
    @State private var feed: Feed = .call
    @FocusState private var fieldFocused: Bool

    private var client: any HawkEyeClienting { model.client }

    private var refusals: [VerificationResult] {
        client.verifications.filter { $0.decision.isRefusal }
    }

    var body: some View {
        GeometryReader { proxy in
        ZStack(alignment: .top) {
            AmbientBackground()

            // One scroll for the whole page, with the context field pinned.
            //
            // The header grows without bound as `guidance` sends instructions,
            // so when the feed had its own inner ScrollView the header squeezed
            // it to a couple of hundred points and the discarded claim, which is
            // the most important thing on this screen, became unreachable.
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: Space.md) {
                            banner
                            guidanceStack
                            if !refusals.isEmpty { refusalBanner }
                            feedSwitch
                            feedBody
                            Color.clear.frame(height: 1).id(Self.bottomAnchor)
                        }
                        .padding(.horizontal, Space.gutter)
                        // Extra top clearance for the fixed back button
                        // overlaid above this scroll content — see `backButton`.
                        .padding(.top, Hit.min + Space.xs)
                        .padding(.bottom, Space.sm)
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: client.transcript.count) {
                        guard feed == .call else { return }
                        withAnimation(Motion.arrive) {
                            proxy.scrollTo(Self.bottomAnchor, anchor: .bottom)
                        }
                    }
                }

                contextField
                    .padding(.horizontal, Space.gutter)
                    .padding(.top, Space.sm)

                endCallButton
                    .padding(.horizontal, Space.gutter)
                    .padding(.top, Space.xl)
                    .padding(.bottom, Space.md)
            }

            // Content scrolls behind the status bar, so cover that strip in
            // the ground colour rather than letting transcript text collide
            // with the clock. The ground is flat, so this reads as seamless.
            Palette.ground
                .frame(height: proxy.safeAreaInsets.top)
                .ignoresSafeArea(edges: .top)
                .allowsHitTesting(false)

            backButton
                .padding(.top, proxy.safeAreaInsets.top + Space.xs)
                .padding(.leading, Space.md)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        }
        .preferredColorScheme(.dark)
        .animation(Motion.arrive, value: refusals.count)
    }

    // MARK: Back

    /// Fixed above the scroll content rather than inside it, so it's always
    /// reachable regardless of scroll position — this is the one way off
    /// this screen that does not end the call.
    private var backButton: some View {
        Button(action: onBack) {
            Image(systemName: "chevron.left")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.ink)
                .frame(width: Hit.min, height: Hit.min)
                .background(Circle().fill(Palette.surface.opacity(0.9)))
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Back, call continues")
    }

    // MARK: Banner

    private var banner: some View {
        VStack(spacing: Space.md) {
            HStack(spacing: Space.md) {
                ZStack {
                    Circle()
                        .fill(incident.type.tint.opacity(0.16))
                        .frame(width: 44, height: 44)
                    Image(systemName: incident.type.symbol)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(incident.type.tint)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(incident.type.title)
                        .font(TypeScale.heading)
                        .foregroundStyle(Palette.ink)
                    Text(incident.origin.label)
                        .font(TypeScale.caption)
                        .foregroundStyle(
                            incident.origin == .system ? Palette.calm : Palette.inkMuted
                        )
                }

                Spacer(minLength: Space.sm)

                CallStateBadge(state: incident.callState, since: incident.openedAt)
            }

            if let summary = incident.summary {
                // `master`'s classification, in plain English. Shown because
                // the reasoning is the interesting part and it makes the system
                // look like it is thinking rather than switching.
                Text(summary)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(incident.type.tint.opacity(0.3), lineWidth: 1)
        )
        .padding(.top, Space.sm)
    }

    // MARK: Guidance

    /// Instructions from `agents/guidance`.
    ///
    /// **The UI does not distinguish relayed-from-the-operator instructions
    /// from first-aid instructions**, because the user does not care which is
    /// which; they care what to do. That is a deliberate decision from
    /// `app/CLAUDE.md`, not an oversight.
    ///
    /// Note also that the client never authors any of this text. Every word
    /// here came from the guidance agent, which is the one component that owns
    /// the safety rules in `agents/CLAUDE.md`. Hardcoding first-aid copy in the
    /// app would put medical instructions outside the place they are reviewed.
    @ViewBuilder
    private var guidanceStack: some View {
        let messages = Array(client.instructions.suffix(2).reversed())
        if !messages.isEmpty {
            VStack(spacing: Space.sm) {
                ForEach(Array(messages.enumerated()), id: \.element.id) { index, message in
                    InstructionCard(instruction: message, latest: index == 0)
                        .transition(.asymmetric(
                            insertion: .opacity.combined(with: .offset(y: -12)),
                            removal: .opacity
                        ))
                }
            }
            .animation(Motion.arrive, value: client.instructions)
        }
    }

    // MARK: The refusal

    /// A discarded claim is a refusal, not a log line.
    ///
    /// It is the loudest thing on this screen after the call state, it is
    /// visible whichever feed is showing, and tapping it goes straight to the
    /// reasons. A dispatch demo that escalates is unremarkable; one that
    /// correctly refuses an impostor is the submission.
    private var refusalBanner: some View {
        Button {
            feed = .verification
        } label: {
            HStack(alignment: .top, spacing: Space.md) {
                Image(systemName: "hand.raised.slash.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Palette.personUnresponsive)
                    .padding(.top, 1)

                VStack(alignment: .leading, spacing: 3) {
                    Text(refusals.count == 1
                         ? "1 claim refused"
                         : "\(refusals.count) claims refused")
                        .font(TypeScale.bodyStrong)
                        .foregroundStyle(Palette.ink)
                    Text(refusals.count == 1
                         ? "It was not spoken to the operator and played no part in the classification."
                         : "None of them was spoken to the operator or used in the classification.")
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Palette.inkFaint)
                    .padding(.top, 3)
            }
            .padding(Space.lg)
            .background(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(Palette.personUnresponsive.opacity(0.12))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .strokeBorder(Palette.personUnresponsive.opacity(0.5), lineWidth: 1)
            )
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("\(refusals.count) refused claims. Open the verification feed.")
    }

    // MARK: Feed

    private var feedSwitch: some View {
        HStack(spacing: Space.sm) {
            ForEach(Feed.allCases) { option in
                Button {
                    feed = option
                } label: {
                    HStack(spacing: 5) {
                        Text(option.title)
                            .font(.system(size: 12, weight: .semibold))
                        if option == .verification, !refusals.isEmpty {
                            Circle()
                                .fill(Palette.personUnresponsive)
                                .frame(width: 5, height: 5)
                        }
                    }
                    .foregroundStyle(feed == option ? Palette.ink : Palette.inkFaint)
                    .padding(.horizontal, Space.md)
                    .padding(.vertical, 7)
                    .background(
                        Capsule().fill(feed == option ? Palette.surfaceRaised : .clear)
                    )
                }
                .buttonStyle(.pressable)
            }

            Spacer()
        }
        .animation(Motion.snappy, value: feed)
    }

    @ViewBuilder
    private var feedBody: some View {
        switch feed {
        case .call: transcript
        case .verification: verificationFeed
        }
    }

    private var transcript: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            if client.transcript.isEmpty {
                Text("Waiting for the operator to pick up.")
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.inkFaint)
                    .padding(.top, Space.lg)
                    .frame(maxWidth: .infinity)
            } else {
                ForEach(client.transcript) { line in
                    TranscriptRow(line: line)
                        .id(line.id)
                }
            }
        }
        .padding(.vertical, Space.sm)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    /// Every claim that reached `master`, verified or refused, newest first.
    ///
    /// The operator cannot check any of this live, and the app never says they
    /// can. This exists so the resident, and anyone reviewing afterwards, can
    /// see what the system was willing to stand behind and what it threw away.
    private var verificationFeed: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            if client.verifications.isEmpty {
                Text("No claims have been checked yet.")
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.inkFaint)
                    .padding(.top, Space.lg)
                    .frame(maxWidth: .infinity)
            } else {
                ForEach(client.verifications) { result in
                    VerificationRow(result: result)
                        .id(result.id)
                }
            }
        }
        .padding(.vertical, Space.sm)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .animation(Motion.arrive, value: client.verifications)
    }

    private static let bottomAnchor = "transcript-bottom"

    // MARK: Context field

    /// The "what is happening" box. Always visible, never collapsed.
    ///
    /// The agents know what the radio can see. They do not know that the
    /// intruder had a knife, that the child is asthmatic, or that the smoke is
    /// coming from the laundry.
    ///
    /// What is typed here is **context, never instruction**. It is carried with
    /// `user-input` provenance, and `caller` attributes it as something the
    /// resident said rather than as something a sensor observed.
    private var contextField: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            HStack(alignment: .bottom, spacing: Space.sm) {
                TextField(
                    "Anything the system cannot see",
                    text: $context,
                    axis: .vertical
                )
                .lineLimit(1...4)
                .font(TypeScale.body)
                .foregroundStyle(Palette.ink)
                .tint(Palette.calm)
                .focused($fieldFocused)
                .submitLabel(.send)
                .padding(.horizontal, Space.md)
                .padding(.vertical, 11)
                .background(
                    RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                        .fill(Palette.surfaceRaised)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                        .strokeBorder(
                            fieldFocused ? Palette.calm.opacity(0.5) : Palette.hairline,
                            lineWidth: 1
                        )
                )
                .animation(Motion.snappy, value: fieldFocused)

                Button(action: send) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(canSend ? Palette.ground : Palette.inkFaint)
                        .frame(width: Hit.min - 8, height: Hit.min - 8)
                        .background(
                            Circle().fill(canSend ? Palette.calm : Palette.surfaceRaised)
                        )
                }
                .buttonStyle(.pressable)
                .disabled(!canSend)
                .animation(Motion.snappy, value: canSend)
                .accessibilityLabel("Send to the dispatcher")
            }
        }
    }

    private var canSend: Bool {
        !sending && !context.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func send() {
        let text = context
        context = ""
        sending = true
        Task {
            try? await client.sendContext(text)
            sending = false
        }
    }

    // MARK: End call

    /// **Front-end only.** The backend has no stand-down route (see
    /// `app/CLAUDE.md`: "the app has no stand-down button... an incident
    /// closes when `master` sends `resolved`"), so this does not tell the
    /// backend anything — it stops showing this incident on this phone. A
    /// real hang-up needs a real stand-down route; this is a placeholder for
    /// that, not a claim that the 911 call itself was ended.
    private var endCallButton: some View {
        VStack(spacing: 8) {
            HoldToConfirmButton(
                tint: Palette.ground,
                circular: true,
                accessibilityLabel: "Hold to end call",
                action: onEndCall
            ) {
                Image(systemName: "phone.down.fill")
                    .font(.system(size: 36, weight: .semibold))
                    .foregroundStyle(Palette.ink)
                    .frame(width: 108, height: 108)
                    .background(Circle().fill(Palette.personUnresponsive))
            }

            Text("End call")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.personUnresponsive)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Call state

private struct CallStateBadge: View {
    var state: CallState
    var since: Date
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .trailing, spacing: 3) {
            HStack(spacing: 5) {
                Circle()
                    .fill(state == .connected ? Palette.live : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                    .opacity(state == .connected ? (pulse ? 1 : 0.2) : 1)
                Text(state.label)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(state == .connected ? Palette.live : Palette.inkMuted)
            }

            if state == .connected {
                TimelineView(.periodic(from: since, by: 1)) { timeline in
                    Text(Self.elapsed(from: since, to: timeline.date))
                        .font(TypeScale.numeric)
                        .foregroundStyle(Palette.inkMuted)
                        .monospacedDigit()
                }
            }
        }
        .onAppear { withAnimation(Motion.urgent) { pulse = true } }
    }

    private static func elapsed(from: Date, to: Date) -> String {
        let s = max(0, Int(to.timeIntervalSince(from)))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

// MARK: - Transcript row

private struct TranscriptRow: View {
    var line: TranscriptLine

    private var rail: Color {
        switch line.speaker {
        case .operatorVoice: Palette.fire
        case .caller: Palette.calm
        case .resident: Palette.personMoving
        case .system: Palette.inkFaint
        }
    }

    /// The operator's label is bold and highlighted red so the one voice the
    /// resident did not choose to be on this call stands out from the other
    /// three speakers, which keep the plain eyebrow treatment.
    @ViewBuilder
    private var speakerLabel: some View {
        if line.speaker == .operatorVoice {
            Text(line.speaker.label)
                .font(.system(size: 11, weight: .bold))
                .tracking(1.0)
                .textCase(.uppercase)
                .foregroundStyle(Palette.ink)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(
                    RoundedRectangle(cornerRadius: Radius.sm, style: .continuous)
                        .fill(Palette.personUnresponsive)
                )
        } else {
            Text(line.speaker.label)
                .eyebrowStyle(rail.opacity(0.9))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                speakerLabel
                Text(line.at, style: .time)
                    .font(.system(size: 10, weight: .regular, design: .monospaced))
                    .foregroundStyle(Palette.inkFaint)
                if !line.claimIDs.isEmpty {
                    // This sentence repeats claims that were verified first.
                    // The link between a spoken line and its proof is the whole
                    // point of the caller being a client of the sensing agents.
                    HStack(spacing: 3) {
                        Image(systemName: "checkmark.seal.fill")
                            .font(.system(size: 9, weight: .semibold))
                        Text("\(line.claimIDs.count) verified")
                            .font(.system(size: 10, weight: .medium))
                    }
                    .foregroundStyle(Palette.calm.opacity(0.9))
                }
            }

            Text(line.text)
                .font(TypeScale.body)
                .foregroundStyle(line.speaker == .operatorVoice ? Palette.ink : Palette.ink.opacity(0.82))
                .fixedSize(horizontal: false, vertical: true)
                .opacity(line.partial ? 0.6 : 1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, Space.md)
        .overlay(alignment: .leading) {
            // A speaker rail rather than chat bubbles. Two voices, one of them
            // a machine speaking for you; bubbles would make it look like a
            // text conversation, which it is not.
            Capsule()
                .fill(rail.opacity(line.speaker == .operatorVoice ? 0.5 : 0.35))
                .frame(width: 2)
        }
    }
}

// MARK: - Instruction card

private struct InstructionCard: View {
    var instruction: Instruction
    var latest: Bool

    var body: some View {
        HStack(alignment: .top, spacing: Space.md) {
            Image(systemName: instruction.urgent ? "exclamationmark.circle.fill" : "info.circle.fill")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(instruction.urgent ? Palette.fire : Palette.calm)
                .padding(.top, 1)

            Text(instruction.text)
                .font(latest ? TypeScale.bodyStrong : TypeScale.body)
                .foregroundStyle(latest ? Palette.ink : Palette.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(latest
                      ? (instruction.urgent ? Palette.fire.opacity(0.12) : Palette.surfaceRaised)
                      : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(
                    latest && instruction.urgent ? Palette.fire.opacity(0.4) : Palette.hairline,
                    lineWidth: 1
                )
        )
        .opacity(latest ? 1 : 0.7)
        .scaleEffect(latest ? 1 : 0.985, anchor: .top)
    }
}

// MARK: - Verification row

/// One ANS verification result, rendered so a refusal is unmistakable.
///
/// A discarded claim gets the red treatment, its failed checks named in full,
/// and the consequence stated in plain English. "Untrusted" is a verdict;
/// "certificate fingerprint differs from the one registered" is a reason, and
/// the reason is what makes the refusal legible to anyone in the room.
private struct VerificationRow: View {
    var result: VerificationResult
    @State private var expanded = false

    private var refused: Bool { result.decision.isRefusal }

    private var tint: Color {
        switch result.decision {
        case .asserted: Palette.calm
        case .attributed: Palette.personMoving
        case .corroborationOnly: Palette.inkMuted
        case .discarded: Palette.personUnresponsive
        }
    }

    /// Failed checks are always shown. Passed ones fold away, because four
    /// green ticks are not what anyone needs to read during a call.
    private var visibleChecks: [VerificationCheck] {
        expanded ? result.checks : result.checks.filter { !$0.passed }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.sm) {
            header
            claim
            if !visibleChecks.isEmpty { checks }
            footer
        }
        .padding(Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(refused ? Palette.personUnresponsive.opacity(0.10) : Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(
                    refused ? Palette.personUnresponsive.opacity(0.55) : Palette.hairline,
                    lineWidth: refused ? 1.5 : 1
                )
        )
        .contentShape(Rectangle())
        .onTapGesture {
            withAnimation(Motion.snappy) { expanded.toggle() }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
    }

    private var header: some View {
        HStack(spacing: Space.sm) {
            HStack(spacing: 5) {
                Image(systemName: refused ? "hand.raised.slash.fill" : "checkmark.seal.fill")
                    .font(.system(size: 10, weight: .bold))
                Text(result.decision.label)
                    .font(.system(size: 11, weight: .bold))
                    .tracking(0.6)
                    .textCase(.uppercase)
            }
            .foregroundStyle(refused ? Palette.ink : tint)
            .padding(.horizontal, Space.sm)
            .padding(.vertical, 4)
            .background(
                Capsule().fill(refused ? Palette.personUnresponsive : tint.opacity(0.16))
            )

            Spacer(minLength: Space.xs)

            Text(result.checkedAt, style: .time)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(Palette.inkFaint)
        }
    }

    private var claim: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(result.claim.statement)
                .font(refused ? TypeScale.bodyStrong : TypeScale.body)
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 6) {
                Text(result.agent.name)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Palette.inkMuted)
                Text(result.agent.ansName)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(refused ? Palette.personUnresponsive : Palette.inkFaint)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            if expanded {
                VStack(alignment: .leading, spacing: 2) {
                    if let version = result.agent.certificateVersion {
                        Text("Certificate \(version)")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(Palette.inkFaint)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    trustIndex
                }
            }
        }
    }

    @ViewBuilder
    private var trustIndex: some View {
        if let index = result.agent.trustIndex {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: Space.sm) {
                    Text("Trust Index")
                        .eyebrowStyle(Palette.inkFaint)
                    ForEach(index.scored, id: \.name) { dimension in
                        Text("\(dimension.name) \(Self.score(dimension.value))")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(Palette.inkMuted)
                    }
                }
                if !index.unimplementedDimensions.isEmpty {
                    // Upstream hardcodes these to 0. A 0 that means "not
                    // scored" and a 0 that means "scored zero" are different
                    // facts, so they arrive null and are named rather than
                    // drawn as a zero bar.
                    Text("Not scored upstream: \(index.unimplementedDimensions.joined(separator: ", "))")
                        .font(.system(size: 10))
                        .foregroundStyle(Palette.inkFaint)
                }
                Text("Profile \(result.agent.recommendedProfile.rawValue)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(refused ? Palette.personUnresponsive : Palette.inkFaint)
            }
        }
    }

    private var checks: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(visibleChecks) { check in
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: check.passed ? "checkmark" : "xmark")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(check.passed ? Palette.calm : Palette.personUnresponsive)
                        .padding(.top, 3)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(check.name)
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(check.passed ? Palette.inkMuted : Palette.ink)
                        Text(check.detail)
                            .font(.system(size: 11))
                            .foregroundStyle(Palette.inkMuted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(Space.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.sm, style: .continuous)
                .fill(Palette.ground.opacity(0.5))
        )
    }

    private var footer: some View {
        HStack(alignment: .top, spacing: Space.sm) {
            Text(refused ? result.reason : result.decision.consequence)
                .font(.system(size: 11))
                .foregroundStyle(refused ? Palette.ink : Palette.inkFaint)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            if !expanded, result.checks.contains(where: \.passed) {
                Text("\(result.checks.filter(\.passed).count) passed")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Palette.inkFaint)
            }
        }
    }

    private var accessibilityText: String {
        var parts = [result.decision.label, result.claim.statement,
                     "Claimed by \(result.agent.name) at \(result.agent.ansName)."]
        if refused {
            parts.append(result.reason)
            parts.append(contentsOf: result.failedChecks.map { "\($0.name) failed. \($0.detail)" })
        }
        return parts.joined(separator: " ")
    }

    private static func score(_ value: Double) -> String {
        String(format: "%.2f", value)
    }
}
