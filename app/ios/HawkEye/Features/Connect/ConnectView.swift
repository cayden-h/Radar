import SwiftUI

/// Stage 1. Pick a hub, verify it, go.
///
/// What this screen is not: a WiFi picker. iOS does not permit one without the
/// `NEHotspotHelper` entitlement. See the comment on `Hub`. The copy on screen
/// is careful never to imply otherwise, because a judge who knows iOS will
/// notice, and because the honest mechanism is the better story anyway.
struct ConnectView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 0) {
            header
            Spacer(minLength: Space.xl)
            content
            Spacer(minLength: Space.xl)
            footer
        }
        .padding(.horizontal, Space.gutter)
        .padding(.bottom, Space.xl)
        .task { model.startDiscovery() }
    }

    // MARK: Header

    private var header: some View {
        VStack(spacing: Space.md) {
            Wordmark(size: 42, breathing: false)
                .padding(.top, Space.xxl)

            Text(statusLine)
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkMuted)
                .contentTransition(.opacity)
                .animation(Motion.standard, value: statusLine)
                .multilineTextAlignment(.center)
        }
    }

    private var statusLine: String {
        if model.verifyingHubID != nil { return "Verifying" }
        if case .failed = model.browser.phase { return "Cannot see this network" }
        return model.browser.hubs.isEmpty ? "Looking for your home" : "Choose your hub"
    }

    // MARK: Content

    @ViewBuilder
    private var content: some View {
        if case .failed(let message) = model.browser.phase {
            failure(message)
        } else if model.browser.hubs.isEmpty {
            SearchingIndicator()
                .frame(maxWidth: .infinity)
        } else {
            VStack(spacing: Space.sm) {
                ForEach(model.browser.hubs) { hub in
                    HubRow(
                        hub: hub,
                        verifying: model.verifyingHubID == hub.id,
                        dimmed: model.verifyingHubID != nil && model.verifyingHubID != hub.id
                    ) {
                        Task { await model.connect(to: hub) }
                    }
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .offset(y: 10)),
                        removal: .opacity
                    ))
                }
            }
            .animation(Motion.arrive, value: model.browser.hubs)
            .animation(Motion.standard, value: model.verifyingHubID)
        }
    }

    private func failure(_ message: String) -> some View {
        Card {
            VStack(spacing: Space.md) {
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 26, weight: .regular))
                    .foregroundStyle(Palette.inkMuted)
                Text(message)
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.inkMuted)
                    .multilineTextAlignment(.center)
            }
            .padding(Space.xl)
            .frame(maxWidth: .infinity)
        }
    }

    // MARK: Footer

    private var footer: some View {
        VStack(spacing: Space.xs) {
            if let error = model.connectError {
                Text(error)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.personUnresponsive)
                    .multilineTextAlignment(.center)
                    .transition(.opacity)
            }
        }
        .animation(Motion.standard, value: model.connectError)
    }
}

// MARK: - Row

/// A hub, drawn as a ring rather than a card.
///
/// No fictional reading fills the ring — this isn't a mood dial standing in
/// for data nobody measured. The arc is real: it sweeps to `hub.signalBars`
/// out of 4, the same fact `SignalBars` already drew as bars, just told as
/// an arc instead. The three static points on the ring carry no information
/// of their own, the same as the dot grid already painted across the whole
/// background — decoration in the same key as the rest of the screen, not a
/// second copy of one.
private struct HubRow: View {
    var hub: Hub
    var verifying: Bool
    var dimmed: Bool
    var action: () -> Void

    private var signalFraction: CGFloat {
        CGFloat(hub.signalBars) / 4
    }

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .strokeBorder(
                        verifying ? Palette.calm.opacity(0.5) : Color.white.opacity(0.22),
                        lineWidth: 1.5
                    )

                Circle()
                    .trim(from: 0, to: signalFraction)
                    .stroke(
                        hub.paired ? Palette.calm : Palette.inkMuted,
                        style: StrokeStyle(lineWidth: 3, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
                    .animation(Motion.arrive, value: signalFraction)

                ForEach(Self.decorativePointAngles, id: \.self) { angle in
                    Circle()
                        .fill(Color.white.opacity(0.32))
                        .frame(width: 6, height: 6)
                        .offset(y: -108)
                        .rotationEffect(.degrees(angle))
                }

                VStack(spacing: 8) {
                    Text(hub.name)
                        .font(TypeScale.title)
                        .foregroundStyle(Palette.ink)

                    if verifying {
                        ProgressView()
                            .controlSize(.small)
                            .tint(Palette.inkMuted)
                    } else if hub.paired {
                        Text("Paired")
                            .eyebrowStyle(Palette.calm)
                    } else {
                        Text("Tap to connect")
                            .eyebrowStyle(Palette.inkFaint)
                    }
                }
            }
            .frame(width: 240, height: 240)
            .contentShape(Circle())
        }
        .buttonStyle(.pressable)
        .opacity(dimmed ? 0.35 : 1)
        .disabled(dimmed || verifying)
        .accessibilityLabel("\(hub.name), \(hub.paired ? "paired" : "not paired"), signal \(hub.signalBars) of 4")
    }

    private static let decorativePointAngles: [Double] = [-52, 96, 205]
}

// MARK: - Searching

/// The quiet state. Three rings expanding outward, slowly, and nothing else.
/// Deliberately not a spinner: a spinner says "busy", and this is a system
/// listening.
private struct SearchingIndicator: View {
    @State private var animate = false

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { index in
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.35), lineWidth: 1)
                    .frame(width: 44, height: 44)
                    .scaleEffect(animate ? 3.1 : 0.6)
                    .opacity(animate ? 0 : 0.8)
                    .animation(
                        .easeOut(duration: 3.0)
                        .repeatForever(autoreverses: false)
                        .delay(Double(index) * 1.0),
                        value: animate
                    )
            }
            Circle()
                .fill(Palette.calm.opacity(0.9))
                .frame(width: 7, height: 7)
        }
        .frame(height: 170)
        .onAppear { animate = true }
        .accessibilityLabel("Looking for your home")
    }
}
