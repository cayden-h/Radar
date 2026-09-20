import SwiftUI

/// Stage 2. The product.
///
/// A persistent bottom tab bar (`RadarTabBar`) switches between three pages —
/// Camera, Videos, and People — without tearing any of them down, so the
/// resident can add a family member or glance at a past recording mid-call
/// without losing anything. Videos and People used to be modal pop-ups
/// reached from header icons; they are real pages now, reached from the bar,
/// and their own content is unchanged.
///
/// A live 911 call is deliberately **not** one of those tabs. It is the one
/// screen in this app that still bleeds full-screen with nothing competing
/// with it, exactly as before — see `IncidentView`. The bar's own Back
/// button leaves the call screen without ending the call (typing to the
/// operator and the transcript both keep running underneath), and
/// `LiveCallBanner` is how the resident gets back to it: a thin bar, the
/// same idea as iOS's own "tap to return to call," shown on every tab
/// whenever a call is live but not on screen.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    var hubName: String

    @State private var selectedTab: RadarTab = .camera
    @State private var showingCall = false
    @State private var locallyEndedIncidentID: String?

    private var client: any HawkEyeClienting { model.client }

    /// `nil` once the resident has locally dismissed this incident, even if
    /// the backend hasn't sent `resolved` yet — see `IncidentView`'s note on
    /// why ending a call is front-end-only for now.
    private var activeIncident: Incident? {
        guard let incident = client.incident, incident.id != locallyEndedIncidentID else { return nil }
        return incident
    }

    var body: some View {
        VStack(spacing: 0) {
            Group {
                switch selectedTab {
                case .camera: cameraPage
                case .videos: VideoLibraryView()
                case .people: AddFamilyMemberView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if let incident = activeIncident, !showingCall {
                LiveCallBanner(incident: incident) {
                    showingCall = true
                }
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            RadarTabBar(
                selection: $selectedTab,
                onBack: { model.disconnectAndForget() }
            )
            // The bar's own background stops at its content frame; this
            // extends the same fill through the home-indicator strip so the
            // bar reads as anchored to the bottom edge, like a native tab bar.
            .background(Palette.surface.ignoresSafeArea(edges: .bottom))
        }
        .onChange(of: client.incident?.id) { _, newID in
            guard let newID, newID != locallyEndedIncidentID else { return }
            showingCall = true
        }
        .fullScreenCover(item: Binding<Incident?>(
            get: { showingCall ? activeIncident : nil },
            set: { newValue in if newValue == nil { showingCall = false } }
        )) { incident in
            IncidentView(
                incident: incident,
                onBack: { showingCall = false },
                onEndCall: {
                    locallyEndedIncidentID = incident.id
                    showingCall = false
                    // Without this, `client.incident` stays set forever (the
                    // backend has no stand-down route to actually clear it),
                    // and `raiseIncident`'s `guard incident == nil` silently
                    // blocks every hold-to-call after the first one.
                    client.dismissIncident()
                }
            )
        }
    }

    // MARK: Camera page

    private var cameraPage: some View {
        VStack(spacing: Space.lg) {
            header

            VStack(spacing: Space.xs) {
                CameraFeedView()
                    .frame(maxWidth: .infinity)

                if let co = client.interior.coPpm, co > 9 {
                    CoAlertRow(coPpm: co, simulated: client.interior.coSourceIsSimulated)
                }
            }

            IncidentBar(client: client)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Space.gutter)
        .padding(.top, Space.sm)
    }

    // MARK: Header

    private var header: some View {
        HStack(alignment: .center, spacing: Space.md) {
            Wordmark(size: 28, breathing: false)

            Spacer(minLength: Space.sm)

            HStack(spacing: 6) {
                Circle()
                    .fill(client.link == .live ? Palette.calm : Palette.inkFaint)
                    .frame(width: 6, height: 6)
                Text(hubName)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }
        }
        .padding(.top, Space.sm)
        .overlay(alignment: .bottom) {
            if client.missedFrames {
                // A gap in the stream's `seq` means a frame was missed. Say so
                // rather than quietly drawing a house that may be behind.
                Text("The stream skipped a frame. This view may be behind.")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
                    .offset(y: 18)
            } else if !client.interior.calibrationHealthy {
                // A stale baseline produces confident nonsense. The system
                // suppresses escalation upstream; the app says so rather than
                // drawing a map it cannot stand behind.
                Text("Baseline is stale. Positions may be wrong.")
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.fire)
                    .offset(y: 18)
            }
        }
    }
}

// MARK: - Live call banner

/// The way back to a call that's still running behind whichever tab is on
/// screen. Tapping it re-presents the same full-screen `IncidentView` —
/// nothing about the call (transcript, typed context, the operator on the
/// line) was ever paused while this bar was showing instead of it.
private struct LiveCallBanner: View {
    var incident: Incident
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Text("Return to Call")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Palette.ink)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .background(Palette.live)
        }
        .buttonStyle(.pressable)
        .accessibilityLabel("Live call in progress, \(incident.type.title). Return to call.")
    }
}

// MARK: - CO alert

/// The one piece of roster-adjacent information that was never about "people
/// and where they are": elevated CO is an environment reading, not a
/// presence, so it keeps its own row rather than living inside a presence's
/// tap card. Shown only when elevated — see `HomeView.body`.
private struct CoAlertRow: View {
    var coPpm: Double
    var simulated: Bool

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: "aqi.medium")
                .font(.system(size: 10, weight: .semibold))
            Text("CO \(Int(coPpm)) ppm")
                .font(TypeScale.numeric)
            if simulated {
                // The honesty rule, enforced in the UI. A simulated reading
                // cannot be shown as a measured one.
                Text("SIM")
                    .font(.system(size: 9, weight: .bold))
                    .padding(.horizontal, 4).padding(.vertical, 1)
                    .background(Capsule().fill(Palette.inkFaint.opacity(0.3)))
            }
        }
        .foregroundStyle(Palette.fire)
    }
}

// MARK: - Incident bar

/// Two buttons. One hold raises an incident, which presents the full-screen
/// call automatically — see `HomeView.body`'s `onChange` and
/// `.fullScreenCover`.
private struct IncidentBar: View {
    var client: any HawkEyeClienting

    var body: some View {
        VStack(spacing: Space.sm) {
            Text("Hold to call")
                .eyebrowStyle(Palette.inkFaint)

            VStack(spacing: 8) {
                HoldToConfirmButton(
                    tint: Palette.ground,
                    circular: true,
                    accessibilityLabel: "Hold to raise incident"
                ) {
                    Task { try? await client.raiseIncident(.burglary) }
                } label: {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 36, weight: .semibold))
                        .foregroundStyle(Palette.ink)
                        .frame(width: 108, height: 108)
                        .background(Circle().fill(IncidentType.burglary.tint))
                }

                Text("Call 911")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(IncidentType.burglary.tint)
            }
        }
    }
}
