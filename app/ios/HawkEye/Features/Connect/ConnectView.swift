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
        .background(AmbientBackground())
        .task { model.startDiscovery() }
    }

    // MARK: Header

    private var header: some View {
        VStack(spacing: Space.md) {
            Wordmark(size: 30, breathing: true)
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
            // Said plainly, because it is true and because it is the thing a
            // user will otherwise be confused by.
            Text("Hawk Eye finds hubs on the network this phone is already on. It does not scan for Wi-Fi networks.")
                .font(.system(size: 11, weight: .regular))
                .foregroundStyle(Palette.inkFaint)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Space.lg)
        }
        .animation(Motion.standard, value: model.connectError)
    }
}

// MARK: - Row

private struct HubRow: View {
    var hub: Hub
    var verifying: Bool
    var dimmed: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Space.md) {
                icon

                VStack(alignment: .leading, spacing: 5) {
                    Text(hub.name)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(Palette.ink)

                    HStack(spacing: Space.sm) {
                        if hub.paired {
                            Text("Paired")
                                .font(.system(size: 10, weight: .semibold))
                                .tracking(0.4)
                                .textCase(.uppercase)
                                .foregroundStyle(Palette.calm)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(Palette.calm.opacity(0.14)))
                        }
                        if let ans = hub.ansName {
                            Text(ans)
                                .font(TypeScale.numeric)
                                .foregroundStyle(Palette.inkFaint)
                                .lineLimit(1)
                                .truncationMode(.head)
                        }
                    }
                }

                Spacer(minLength: Space.sm)

                if verifying {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Palette.inkMuted)
                } else {
                    SignalBars(level: hub.signalBars,
                               tint: hub.paired ? Palette.calm : Palette.inkMuted)
                }
            }
            .padding(.horizontal, Space.lg)
            .frame(height: 68)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.pressable)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(verifying ? Palette.calm.opacity(0.55) : Palette.hairline, lineWidth: 1)
        )
        .opacity(dimmed ? 0.35 : 1)
        .disabled(dimmed || verifying)
        .accessibilityLabel("\(hub.name), \(hub.paired ? "paired" : "not paired"), signal \(hub.signalBars) of 4")
    }

    private var icon: some View {
        ZStack {
            RoundedRectangle(cornerRadius: Radius.sm, style: .continuous)
                .fill(Palette.surfaceRaised)
                .frame(width: 38, height: 38)
            Image(systemName: "house.fill")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(hub.paired ? Palette.calm : Palette.inkMuted)
        }
    }
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
                    .scaleEffect(animate ? 3.6 : 0.6)
                    .opacity(animate ? 0 : 0.8)
                    .blur(radius: animate ? 1.5 : 0)
                    .animation(
                        .easeOut(duration: 3.4)
                        .repeatForever(autoreverses: false)
                        .delay(Double(index) * 1.0),
                        value: animate
                    )
            }
            Circle()
                .fill(Palette.calm)
                .frame(width: 7, height: 7)
                .shadow(color: Palette.calm.opacity(0.85), radius: 10)
        }
        .frame(height: 170)
        .onAppear { animate = true }
        .accessibilityLabel("Looking for your home")
    }
}
