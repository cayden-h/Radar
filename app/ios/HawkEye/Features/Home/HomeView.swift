import SwiftUI

/// Stage 2. The product.
///
/// A persistent bottom tab bar (`RadarTabBar`) switches between Camera and
/// People without tearing either down, so the resident can add a family
/// member mid-call without losing anything. Videos and Household used to be
/// reachable from here too — Videos as a third tab, Household as a fourth
/// side button — and both are gone now: Videos' own page did nothing but
/// point at the desktop replay console, and Household had no remaining
/// entry point once its button left the bar, so both the pages and their
/// files were removed rather than left reachable by nothing.
///
/// A live 911 call is deliberately **not** a tab. It is the one screen in
/// this app that still bleeds full-screen with nothing competing with it,
/// exactly as before — see `IncidentView`. The bar's own Back button leaves
/// the call screen without ending the call (typing to the operator and the
/// transcript both keep running underneath), and `LiveCallBanner` is how the
/// resident gets back to it: a thin bar, the same idea as iOS's own "tap to
/// return to call," shown on every tab whenever a call is live but not on
/// screen.
///
/// Notices are a separate axis from all of that: the sensing layer flagging
/// an unexpected presence, reached from the bell rather than a tab, and it
/// never raises an incident on its own — a human tap still does that, on the
/// Camera page, same as ever.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    var hubName: String

    @State private var selectedTab: RadarTab = .camera
    @State private var showingCall = false
    @State private var locallyEndedIncidentID: String?
    /// The notice whose "Remember this visitor" was tapped. Presenting the
    /// sheet off the notice itself, rather than a bare `Bool`, is what lets
    /// the save action know which presence to approve alongside naming it.
    @State private var rememberingNotice: Notice?
    @State private var showingNotices = false

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
            // No extending background here on purpose: the bar is a floating
            // glass pill now, not a shelf docked to the edge, so the ambient
            // gradient behind the whole screen (`RootView`) is meant to show
            // through around it rather than being papered over.
            RadarTabBar(
                selection: $selectedTab,
                onBack: { model.disconnectAndForget() }
            )
        }
        .task { await client.refreshHousehold() }
        .sheet(item: $rememberingNotice) { notice in
            RememberVisitorSheet(unclaimedDevices: client.unclaimedDevices) { name, kind, deviceID in
                Task {
                    try? await client.rememberVisitor(name: name, kind: kind, deviceID: deviceID)
                    // The resident has just said who this is, which answers the
                    // question the banner exists to raise. Approving and
                    // dismissing here, rather than making them also tap
                    // "This is expected", is the point: remembering someone is
                    // a stronger fact than merely vouching for them.
                    if let presenceID = notice.presenceID {
                        try? await client.approvePresence(presenceID)
                    }
                    withAnimation(Motion.standard) {
                        client.dismissNotice(notice.id)
                    }
                }
            }
        }
        .sheet(isPresented: $showingNotices) {
            NoticesPanel(
                notices: client.notices,
                onDismiss: { notice in
                    withAnimation(Motion.standard) { client.dismissNotice(notice.id) }
                },
                onApprove: { notice in
                    guard let presenceID = notice.presenceID else { return }
                    Task { try? await client.approvePresence(presenceID) }
                    withAnimation(Motion.standard) { client.dismissNotice(notice.id) }
                },
                onRemember: { notice in
                    guard notice.presenceID != nil else { return }
                    rememberingNotice = notice
                }
            )
        }
        .onChange(of: client.incident?.id) { _, newID in
            guard let newID else {
                // The backend has caught up and actually cleared the incident,
                // so the local override that was standing in for a stand-down
                // route is no longer needed. Clearing it here is what lets the
                // next incident register as new even when it reuses the same
                // ID (the mock always raises "inc-0001"); leaving it set would
                // make every call after the first look like the one just ended.
                locallyEndedIncidentID = nil
                return
            }
            guard newID != locallyEndedIncidentID else { return }
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
            .padding(.top, Space.md)

            // Two flexible spacers, so the button centers in whatever room
            // is actually left between the camera panel and the tab bar.
            Spacer(minLength: Space.xl)

            IncidentBar(client: client)

            Spacer(minLength: Space.xl)
        }
        .padding(.horizontal, Space.gutter)
        .padding(.top, Space.sm)
    }

    // MARK: Header

    /// Who's home, whether the hub is live, and whether anything's waiting
    /// for them — the three facts worth a glance before anything else loads.
    /// The wordmark moved off this screen entirely: it already did its job
    /// on Connect, and repeating it here just to fill space was the reason
    /// there was no room left for the resident's own name.
    private var header: some View {
        HStack(alignment: .center, spacing: Space.md) {
            avatarBadge

            VStack(alignment: .leading, spacing: 3) {
                Text("Hello, \(Config.residentName)")
                    .font(TypeScale.heading)
                    .foregroundStyle(Palette.ink)

                HStack(spacing: 6) {
                    Circle()
                        .fill(client.link == .live ? Palette.calm : Palette.inkFaint)
                        .frame(width: 6, height: 6)
                    Text(hubName)
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }
            }

            Spacer(minLength: Space.sm)

            notificationButton
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

    private var avatarBadge: some View {
        Circle()
            .fill(
                LinearGradient(
                    colors: [Palette.calm, Palette.collapse],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .frame(width: 44, height: 44)
            .overlay(
                Text(Config.residentName.prefix(1))
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(Palette.ground)
            )
            .accessibilityHidden(true)
    }

    /// Opens `NoticesPanel`. The badge says whether anything's waiting;
    /// tapping is now the only way to see notices at all — they no longer
    /// render inline on Camera, so nothing sits between the header and the
    /// feed uninvited.
    private var notificationButton: some View {
        Button {
            showingNotices = true
        } label: {
            ZStack(alignment: .topTrailing) {
                Image(systemName: "bell.fill")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Palette.ink.opacity(0.85))
                    .frame(width: 42, height: 42)
                    .glassPanel(cornerRadius: Radius.pill)

                if !client.notices.isEmpty {
                    Circle()
                        .fill(Palette.personUnexpected)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().strokeBorder(Palette.duskBase, lineWidth: 1.5))
                        .offset(x: 1, y: -1)
                }
            }
        }
        .buttonStyle(.pressable)
        .accessibilityLabel(client.notices.isEmpty ? "No notices" : "\(client.notices.count) notices waiting")
    }
}

// MARK: - Notices panel

/// Every open notice, reached by tapping the bell rather than shown inline —
/// see `HomeView.notificationButton`. Reuses `NoticeBanner` as-is; only where
/// it renders changed; what each notice can do about it (approve, remember,
/// dismiss) did not.
private struct NoticesPanel: View {
    var notices: [Notice]
    var onDismiss: (Notice) -> Void
    var onApprove: (Notice) -> Void
    var onRemember: (Notice) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.md) {
                Text("Notices")
                    .font(TypeScale.title)
                    .foregroundStyle(Palette.ink)
                    .padding(.top, Space.xxl)

                if notices.isEmpty {
                    Text("Nothing waiting on you.")
                        .font(TypeScale.body)
                        .foregroundStyle(Palette.inkMuted)
                        .padding(.top, Space.xxl)
                } else {
                    VStack(spacing: Space.sm) {
                        ForEach(notices) { notice in
                            NoticeBanner(
                                notice: notice,
                                onDismiss: { onDismiss(notice) },
                                onApprove: { onApprove(notice) },
                                onRemember: { onRemember(notice) }
                            )
                        }
                    }
                }

                Spacer(minLength: 0)
            }
            .padding(.horizontal, Space.xl)
            .padding(.bottom, Space.xl)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.groundGradient.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .preferredColorScheme(.dark)
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
            HStack(spacing: Space.sm) {
                Circle()
                    .fill(Color.white)
                    .frame(width: 7, height: 7)
                Text("Return to Call")
                    .font(.system(size: 15, weight: .semibold))
            }
            .foregroundStyle(Palette.ink)
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background(
                Capsule().fill(
                    LinearGradient(
                        colors: [Palette.live, Palette.live.opacity(0.82)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
            )
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.32), lineWidth: 1))
            .shadow(color: Palette.live.opacity(0.4), radius: 18, y: 8)
        }
        .buttonStyle(.pressable)
        // Same floating-pill language as the tab bar directly below it —
        // a rounded capsule inset from both edges, not a flat rectangle
        // butting against the bar's rounded corners.
        .padding(.horizontal, Space.gutter)
        .padding(.bottom, Space.sm)
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

/// One button, held rather than tapped, because a misfired 911 call is a
/// real-world harm and a hold is release-to-cancel on the target the resident
/// already found — see `HoldToConfirmButton`. Raising it presents the
/// full-screen call automatically — see `HomeView.body`'s `onChange` and
/// `.fullScreenCover`.
///
/// Drawn with the same recipe as the rest of the app's raised, glowing
/// controls (the tab bar's mascot button, `glassPanel`'s rim highlight) —
/// a gradient instead of a flat fill, a light catching the top edge, a glow
/// under it — so it reads as *this app's* button and not a bare SF Symbol on
/// a circle. It stays fully opaque on purpose, unlike a `glassPanel`: this is
/// the one control that must never look transparent or ambiguous.
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
                    Image(systemName: "phone.fill")
                        .font(.system(size: 40, weight: .semibold))
                        .foregroundStyle(Palette.ink)
                        .frame(width: 122, height: 122)
                        .background(
                            Circle().fill(
                                RadialGradient(
                                    colors: [
                                        IncidentType.burglary.tint.opacity(0.88),
                                        IncidentType.burglary.tint,
                                    ],
                                    center: UnitPoint(x: 0.32, y: 0.28),
                                    startRadius: 4,
                                    endRadius: 102
                                )
                            )
                        )
                        .overlay(
                            Circle().strokeBorder(
                                LinearGradient(
                                    colors: [Color.white.opacity(0.55), Color.white.opacity(0)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                ),
                                lineWidth: 1.5
                            )
                        )
                        .shadow(color: IncidentType.burglary.tint.opacity(0.5), radius: 24, y: 12)
                }

                Text("Call 911")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(IncidentType.burglary.tint)
            }
        }
    }
}
