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
///
/// Notices and the household are a separate axis from all of that: a notice
/// is the sensing layer flagging an unexpected presence, and it never raises
/// an incident on its own — a human tap still does that, on the Camera page,
/// same as ever.
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
    @State private var showingHousehold = false

    private var client: any HawkEyeClienting { model.client }

    /// `nil` once the resident has locally dismissed this incident, even if
    /// the backend hasn't sent `resolved` yet — see `IncidentView`'s note on
    /// why ending a call is front-end-only for now.
    private var activeIncident: Incident? {
        guard let incident = client.incident, incident.id != locallyEndedIncidentID else { return nil }
        return incident
    }

    /// Set while `RememberVisitorSheet` is up, so the notice card's own sheet
    /// steps aside rather than trying to present underneath another sheet.
    /// The notice itself is untouched in `client.notices` while this is true;
    /// only the card's visibility is suppressed. See `onRemember` below and
    /// the `onChange(of: rememberingNotice)` that clears this once that sheet
    /// closes, saved or cancelled.
    @State private var suppressNoticeCard = false

    /// The newest notice, presented as a modal card. Both clients insert new
    /// notices at index 0 (see `MockHawkEyeClient.notices` and
    /// `LiveHawkEyeClient.notices`), so `.first` is the most recent.
    private var latestNoticeBinding: Binding<Notice?> {
        Binding(
            get: { suppressNoticeCard ? nil : client.notices.first },
            set: { newValue in
                guard newValue == nil else { return }
                // This only fires for an interactive (swipe-to-dismiss)
                // close. The card's own Dismiss/Approve controls call
                // `client.dismissNotice` directly, and hiding the card for
                // the "Remember this visitor" flow sets `suppressNoticeCard`
                // instead of clearing the notice — see `onRemember` below.
                if let id = client.notices.first?.id {
                    withAnimation(Motion.standard) { client.dismissNotice(id) }
                }
            }
        )
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
        .task { await client.refreshHousehold() }
        .sheet(item: latestNoticeBinding) { notice in
            NoticeCard(
                notice: notice,
                onDismiss: {
                    withAnimation(Motion.standard) {
                        client.dismissNotice(notice.id)
                    }
                },
                onApprove: {
                    guard let presenceID = notice.presenceID else { return }
                    Task { try? await client.approvePresence(presenceID) }
                    withAnimation(Motion.standard) {
                        client.dismissNotice(notice.id)
                    }
                },
                onRemember: {
                    guard notice.presenceID != nil else { return }
                    // Step the notice card's sheet aside rather than stacking
                    // a second sheet on top of it; `onChange` below restores
                    // it once `RememberVisitorSheet` closes, if the notice is
                    // still around.
                    suppressNoticeCard = true
                    rememberingNotice = notice
                }
            )
        }
        .onChange(of: rememberingNotice) { oldValue, newValue in
            if oldValue != nil && newValue == nil {
                suppressNoticeCard = false
            }
        }
        .sheet(item: $rememberingNotice) { notice in
            RememberVisitorSheet(unclaimedDevices: client.unclaimedDevices) { name, kind, deviceID in
                Task {
                    try? await client.rememberVisitor(name: name, kind: kind, deviceID: deviceID)
                    // The resident has just said who this is, which answers the
                    // question the card exists to raise. Approving and
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
        .sheet(isPresented: $showingHousehold) {
            HouseholdList(members: client.household) { memberID in
                Task { try? await client.forgetMember(memberID) }
            }
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

            Button { showingHousehold = true } label: {
                Image(systemName: "person.2.fill")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Palette.inkMuted)
                    .frame(width: Hit.min * 0.5, height: Hit.min * 0.5)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Household")
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

/// One button, held rather than tapped, because a misfired 911 call is a
/// real-world harm and a hold is release-to-cancel on the target the resident
/// already found — see `HoldToConfirmButton`. Raising it presents the
/// full-screen call automatically — see `HomeView.body`'s `onChange` and
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
                    Image(systemName: "phone.fill")
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
