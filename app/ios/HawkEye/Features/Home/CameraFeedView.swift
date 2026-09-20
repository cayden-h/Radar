import SwiftUI

/// The live camera feed on Home, where the floor plan used to be.
///
/// Wired to the real camera on 2026-09-20. It was a static placeholder until
/// then, drawing a `video.fill` glyph while `HawkEyeClienting.cameraFrame` was
/// already being populated from the event stream and thrown away.
///
/// ## Two sources, and the order matters
///
/// The full-rate MJPEG at `GET /v1/camera/live` is the phone's path, per the
/// root `CLAUDE.md`. The 1 Hz thumbnail on the event stream is the watch's, and
/// it is the fallback here: while MJPEG is connecting, or after it drops, one
/// frame a second is still a true picture of the room and a blank panel is not.
///
/// ## What it refuses to draw
///
/// **A stale frame is never presented as the room now.** `CameraFrame.live` is
/// false when the hub's newest frame is older than
/// `HAWKEYE_CAMERA_STALE_AFTER_S`, and a frozen picture of an empty room is the
/// most dangerous thing this app can show. It is dimmed, labelled with its age,
/// and said out loud rather than hidden - hiding it would leave a resident
/// looking at nothing with no idea why.
///
/// **A simulated frame is always marked**, off `Provenance.simulated` in the
/// data rather than off `Config.useMocks`, so a frame that came from a script
/// cannot be presented as one that came from a lens by accident.
struct CameraFeedView: View {

    @Environment(AppModel.self) private var model

    @State private var selectedCamera = 1
    @State private var stream = MJPEGStream()

    /// Re-evaluated on every tick so the "seconds ago" label on a stale frame
    /// counts up rather than freezing at whatever it said on arrival.
    @State private var now = Date()

    private var client: any HawkEyeClienting { model.client }

    private static let staleTick = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        // The panel sizes itself and the picture is laid *over* it.
        //
        // This was a ZStack, and that is what shifted the screen: a ZStack
        // sizes to its largest child, and a `resizable()` image has no
        // intrinsic size, so the feed grew the tile and pushed Call 911 down
        // and across. An `overlay` can never influence its parent's size, so
        // the panel now measures exactly as it did when it was an empty glyph,
        // whatever resolution the camera sends.
        Color.clear
            .glassPanel()
            .overlay { content }
            .clipShape(RoundedRectangle(cornerRadius: Radius.lg, style: .continuous))
        .accessibilityElement()
        .accessibilityLabel(accessibilityDescription)
        .overlay(alignment: .topTrailing) {
            cameraSwitch
                .padding(10)
        }
        .overlay(alignment: .bottomLeading) {
            provenanceMarker
                .padding(10)
        }
        .aspectRatio(4.0 / 3.0, contentMode: .fit)
        .onReceive(Self.staleTick) { now = $0 }
        .task(id: streamIdentity) { openOrCloseStream() }
        .onDisappear { stream.stop() }
    }

    // MARK: What is on screen

    @ViewBuilder
    private var content: some View {
        if let image = currentImage {
            Image(uiImage: image)
                .resizable()
                // Fit, never fill. The camera is 16:9 and this panel is 4:3,
                // so filling would crop the sides off the room - and the edges
                // of a room are exactly where someone walks in. Letterboxing
                // inside the existing panel keeps the whole frame visible and
                // changes nothing about the panel's size or position.
                .aspectRatio(contentMode: .fit)
                // A stale frame is dimmed rather than hidden. The resident can
                // still see what the camera last saw, and cannot mistake it
                // for what the camera sees.
                .opacity(isStale ? 0.45 : 1)
                .overlay(alignment: .top) {
                    if isStale { staleBanner }
                }
        } else {
            placeholder
        }
    }

    /// MJPEG first, thumbnail second. Only camera 1 exists; the second slot is
    /// a real selection with nothing behind it and says so.
    private var currentImage: UIImage? {
        guard selectedCamera == 1 else { return nil }
        if stream.failed == nil, let jpeg = stream.frame, let image = UIImage(data: jpeg) {
            return image
        }
        guard let frame = client.cameraFrame else { return nil }
        return UIImage(data: frame.jpeg)
    }

    /// True when the newest thing we have is not current.
    ///
    /// An MJPEG frame in hand is live by construction: the hub only writes to
    /// that stream as frames arrive. So staleness is a question about the
    /// thumbnail, and about a dropped stream.
    private var isStale: Bool {
        if stream.failed != nil { return true }
        if stream.frame != nil { return false }
        guard let frame = client.cameraFrame else { return false }
        return !frame.live
    }

    /// Unchanged from before this view was wired: one centred glyph, same size,
    /// same colour. The empty state is existing UI and the camera work has no
    /// business redesigning it.
    ///
    /// `placeholderMessage` below is still built, but it goes to VoiceOver
    /// rather than on screen - so the reason there is no picture is available
    /// to anyone who asks for it without a sighted user seeing the layout move.
    private var placeholder: some View {
        Image(systemName: "video.fill")
            .font(.system(size: 40, weight: .regular))
            .foregroundStyle(Palette.ink.opacity(0.7))
    }

    /// Never "no signal". Each of these is a different thing to do about it.
    private var placeholderMessage: String {
        if selectedCamera != 1 { return "No second camera on this hub." }
        if let failed = stream.failed, client.cameraFrame == nil { return failed }
        if stream.connecting { return "Opening the camera…" }
        if client.link != .live { return "Not connected to your hub." }
        // The shield is the interesting case: there is no picture because the
        // lens is physically covered, which is the product working rather than
        // failing, so it reads as a statement and not as an error.
        //
        // Nil is deliberately not folded into `.closed`. Per `InteriorState`,
        // nil means the shutter has not reported yet, and drawing the resting
        // state for it would imply an attestation nobody made.
        switch client.interior.shield?.state {
        case .closed: return "The shield is closed. The camera cannot see."
        case .none: return "The shutter has not reported where the shield is."
        default: return "No camera is attached to this hub."
        }
    }

    private var staleBanner: some View {
        Text(staleDescription)
            .font(.system(size: 11, weight: .bold, design: .rounded))
            .foregroundStyle(Palette.ink)
            .padding(.horizontal, 10)
            .frame(height: 24)
            .background(Capsule().fill(Palette.ground.opacity(0.75)))
            .padding(.top, 10)
    }

    private var staleDescription: String {
        guard let captured = client.cameraFrame?.capturedAt else { return "NOT LIVE" }
        let age = max(0, Int(now.timeIntervalSince(captured).rounded()))
        return age < 120 ? "NOT LIVE · \(age)s AGO" : "NOT LIVE · \(age / 60)m AGO"
    }

    /// Drawn off the frame's own `source`, never off `Config.useMocks`, so a
    /// frame that came from a script or from recorded footage cannot be
    /// presented as one that came from a lens.
    ///
    /// The badge is derived from the thumbnail's provenance even while the
    /// MJPEG stream is what is on screen: raw JPEG carries no provenance, and
    /// both come from the same camera on the same hub.
    @ViewBuilder
    private var provenanceMarker: some View {
        if let badge = client.cameraFrame?.originBadge, currentImage != nil {
            Text(badge)
                .font(.system(size: 10, weight: .heavy, design: .rounded))
                .foregroundStyle(Palette.ink)
                .padding(.horizontal, 8)
                .frame(height: 20)
                .background(Capsule().fill(Palette.personUnexpected.opacity(0.85)))
        }
    }

    private var accessibilityDescription: String {
        guard currentImage != nil else {
            return "Camera \(selectedCamera). \(placeholderMessage)"
        }
        let room = client.cameraFrame?.room ?? Config.cameraRoom
        return isStale
            ? "Camera \(selectedCamera), \(room). \(staleDescription)."
            : "Camera \(selectedCamera), \(room), live."
    }

    // MARK: The stream

    /// Changing this restarts the stream: a new hub, or a different camera.
    private var streamIdentity: String {
        "\(selectedCamera)|\(client.cameraStreamURL?.absoluteString ?? "none")"
    }

    private func openOrCloseStream() {
        guard selectedCamera == 1, let url = client.cameraStreamURL else {
            stream.stop()
            return
        }
        stream.start(url: url)
    }

    // MARK: The switch

    /// A native pop-out rather than an inline segmented toggle: one button
    /// that reads which camera is active, and a menu of every camera when
    /// tapped. Scales to more than two without redesigning the overlay.
    private var cameraSwitch: some View {
        Menu {
            Picker("Camera", selection: $selectedCamera.animation(Motion.snappy)) {
                Text("Camera 1").tag(1)
                Text("Camera 2").tag(2)
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "video.fill")
                    .font(.system(size: 11, weight: .semibold))
                Text("\(selectedCamera)")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .bold))
            }
            .foregroundStyle(Palette.ink)
            .padding(.horizontal, 10)
            .frame(height: 30)
            .background(Capsule().fill(Palette.ground.opacity(0.6)))
        }
        .accessibilityLabel("Camera \(selectedCamera), choose camera")
    }
}
