import SwiftUI

/// The live interior view: where people are in the house, right now.
///
/// `app/CLAUDE.md` specifies Three.js because it was written for a web client.
/// This is the native equivalent: a top-down procedural floorplan drawn in a
/// SwiftUI `Canvas`, with presences as soft coherent blobs. No SceneKit, no
/// assets, no model files. Everything on screen is computed from the
/// `sensor/` contract on the frame it arrives.
///
/// **Confidence is rendered as coherence, never as a number floating in
/// space.** A 0.4-confidence presence is blurrier, dimmer, and unstable; a
/// 0.9-confidence presence is tight and still. That is honest, and it also
/// looks better than a percentage label.
///
/// Three visual states, and the distinction between them is the whole system:
///
/// 1. `.personMoving` - a confirmed person. Calm blue, drifting, breathing.
/// 2. `.personUnresponsive` - a person whose breathing signature we had and no
///    longer have. Red, pulsing hard, with an alarm ring around it. **The
///    loudest thing on screen.** The name is the app's internal state; the
///    label shown to a human reads "no breathing signature", because a lost
///    signature is a reason to look and never a finding about a body.
/// 3. `.unconfirmed` - a perturbation with no respiration signature. Drawn as a
///    dashed grey lozenge with jittering ticks: deliberately not a blob, so it
///    cannot be mistaken for a person at a glance.
///
/// The difference between 2 and 3 is the difference between dispatching an
/// ambulance and reporting a curtain.
///
/// Crossing those three states is one orthogonal axis, `Presence.expected`. A
/// confirmed person the system did not expect turns violet and gains tracking
/// brackets, whichever of the two person states they are in. That is not a
/// fourth `PresenceState` and must not become one: what changes is whether
/// their being here is accounted for, not what they are.
///
/// For burglary this is the frame the whole project is built around: the
/// intruder and the resident as two distinct tracked presences, in different
/// rooms, both moving.
///
/// **Every presence is a tap target.** The map used to carry a roster list
/// underneath it that repeated every dot in words. That list does not scale —
/// eleven rooms and a handful of presences already crowd a 6.3" screen — so
/// the detail moved onto the dot itself: tap one and its card appears beside
/// it, tap it again (or the card's close button, or empty floor) to dismiss.
/// Exactly one presence's detail is ever showing, tracked by `selectedID`
/// alone; nothing about the drawing loop needs to know about it beyond a
/// highlight ring.
struct InteriorView: View {
    var state: InteriorState

    @State private var selectedID: String?

    /// The popup's assumed footprint, used only to clamp its position on
    /// screen. The card hugs its actual content, so this is deliberately a
    /// touch generous rather than exact — a few points of slack beats a
    /// clamp computed from a size we do not have yet.
    private static let popupSize = CGSize(width: 232, height: 132)

    var body: some View {
        GeometryReader { geo in
            let plan = Self.planRect(in: geo.size, aspect: Self.aspect(of: state.floorplan))

            ZStack(alignment: .topLeading) {
                TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: false)) { timeline in
                    let t = timeline.date.timeIntervalSinceReferenceDate
                    Canvas(opaque: false, rendersAsynchronously: false) { context, _ in
                        drawGrid(&context, plan: plan)
                        drawRooms(&context, plan: plan)
                        drawPresences(&context, plan: plan, t: t, selectedID: selectedID)
                    }
                    .drawingGroup()
                }
                .background(
                    RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                        .fill(Palette.surface)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                        .strokeBorder(Palette.hairline, lineWidth: 1)
                )
                .contentShape(Rectangle())
                .onTapGesture { dismiss() }

                // One invisible, generously-sized tap target per presence,
                // positioned at the same anchor the drawing wanders around.
                // Hit-testing a blurred, animated blob directly would make
                // low-confidence presences — the ones a person most needs to
                // ask about — the hardest to tap.
                ForEach(state.presences) { presence in
                    let center = Self.anchorPoint(for: presence, plan: plan, floorplan: state.floorplan)
                    Color.clear
                        .frame(width: Hit.min, height: Hit.min)
                        .contentShape(Circle())
                        .position(center)
                        .onTapGesture { toggle(presence.id) }
                        .accessibilityAddTraits(.isButton)
                        .accessibilityLabel(Self.accessibilityLabel(for: presence, floorplan: state.floorplan))
                }

                if let selected = state.presences.first(where: { $0.id == selectedID }) {
                    let anchor = Self.anchorPoint(for: selected, plan: plan, floorplan: state.floorplan)
                    let center = Self.clampedPopupCenter(near: anchor, cardSize: Self.popupSize, in: geo.size)
                    PresenceDetailCard(presence: selected, floorplan: state.floorplan) { dismiss() }
                        .frame(width: Self.popupSize.width, alignment: .leading)
                        .contentShape(Rectangle())
                        .onTapGesture {} // absorb taps so the card never triggers the dismiss-on-empty-floor gesture beneath it
                        .position(center)
                        .transition(.scale(scale: 0.92, anchor: .center).combined(with: .opacity))
                        .zIndex(10)
                }
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func toggle(_ id: String) {
        withAnimation(Motion.snappy) {
            selectedID = (selectedID == id) ? nil : id
        }
    }

    private func dismiss() {
        guard selectedID != nil else { return }
        withAnimation(Motion.snappy) { selectedID = nil }
    }

    private static func accessibilityLabel(for presence: Presence, floorplan: Floorplan) -> String {
        let room = floorplan.room(named: presence.zone)?.name ?? presence.zone
        let headline = presence.isUnexpected ? "Unexpected person, \(presence.state.headline.lowercased())," : presence.state.headline
        return "\(headline) in the \(room). Double tap for details."
    }

    // MARK: Geometry

    /// Aspect-fits the plan into the view with a consistent inset, so the plan
    /// keeps its proportions on every device width.
    private static func planRect(in size: CGSize, aspect: CGFloat) -> CGRect {
        let inset: CGFloat = 22
        let available = CGRect(origin: .zero, size: size).insetBy(dx: inset, dy: inset)
        var w = available.width
        var h = w / aspect
        if h > available.height {
            h = available.height
            w = h * aspect
        }
        return CGRect(
            x: available.midX - w / 2,
            y: available.midY - h / 2,
            width: w,
            height: h
        )
    }

    /// The plan's own proportions, in metres, as the hub enrolled them. The
    /// geometry is authored rather than sensed, and it arrives with the state.
    private static func aspect(of floorplan: Floorplan) -> CGFloat {
        guard floorplan.widthM > 0, floorplan.depthM > 0 else { return 1.18 }
        return CGFloat(floorplan.widthM / floorplan.depthM)
    }

    private static func screenRect(_ normalized: CGRect, in plan: CGRect) -> CGRect {
        CGRect(
            x: plan.minX + normalized.minX * plan.width,
            y: plan.minY + normalized.minY * plan.height,
            width: normalized.width * plan.width,
            height: normalized.height * plan.height
        )
    }

    /// The still point a presence's drawn position wanders around, and what
    /// both the tap target and the detail popup anchor to. Deliberately not
    /// the animated, drifting position `drawPresences` actually paints: a tap
    /// target that chases a sine wave is a tap target nobody can hit.
    private static func anchorPoint(for presence: Presence, plan: CGRect, floorplan: Floorplan) -> CGPoint {
        let anchor = floorplan.normalizedPoint(presence.position)
        return CGPoint(x: plan.minX + anchor.x * plan.width, y: plan.minY + anchor.y * plan.height)
    }

    /// Places the popup beside the tapped dot, preferring above it, flipping
    /// below when there is not enough headroom, and clamped so it never runs
    /// off the card on any edge.
    private static func clampedPopupCenter(near point: CGPoint, cardSize: CGSize, in bounds: CGSize) -> CGPoint {
        let margin: CGFloat = 10
        let gap: CGFloat = 30
        var y = point.y - cardSize.height / 2 - gap
        if y - cardSize.height / 2 < margin {
            y = point.y + cardSize.height / 2 + gap
        }
        let x = min(max(point.x, cardSize.width / 2 + margin), bounds.width - cardSize.width / 2 - margin)
        let clampedY = min(max(y, cardSize.height / 2 + margin), bounds.height - cardSize.height / 2 - margin)
        return CGPoint(x: x, y: clampedY)
    }

    // MARK: Layers

    /// A faint dot grid under the plan. It gives the space a floor without
    /// adding a single readable element, and it makes drift legible: a blob
    /// moving against a plain field is hard to read.
    private func drawGrid(_ context: inout GraphicsContext, plan: CGRect) {
        let spacing: CGFloat = 14
        var path = Path()
        var y = plan.minY
        while y <= plan.maxY {
            var x = plan.minX
            while x <= plan.maxX {
                path.addEllipse(in: CGRect(x: x - 0.6, y: y - 0.6, width: 1.2, height: 1.2))
                x += spacing
            }
            y += spacing
        }
        context.fill(path, with: .color(Palette.inkFaint.opacity(0.13)))
    }

    private func drawRooms(_ context: inout GraphicsContext, plan: CGRect) {
        for room in state.floorplan.rooms {
            let rect = Self.screenRect(state.floorplan.normalizedRect(room), in: plan)
            let shape = Path(roundedRect: rect, cornerRadius: 5, style: .continuous)

            context.fill(shape, with: .color(Palette.surfaceRaised.opacity(0.55)))
            context.stroke(shape, with: .color(Palette.hairline), lineWidth: 1)

            drawRoomLabel(&context, room: room, in: rect)
        }
    }

    /// Eleven rooms on a 6.3 inch screen, several of them narrower than their
    /// own name. A label that spills into the room next door is worse than no
    /// label, because it reads as belonging to the wrong room.
    ///
    /// So the label is fitted rather than assumed: it wraps onto a second line
    /// inside the room, drops a point size if that is what makes it fit, and is
    /// **dropped entirely** if even that will not sit inside the rectangle.
    ///
    /// Every word has to fit on its own line before anything is drawn. Without
    /// that check `Text` will happily break a word in half and truncate it, and
    /// "LINE / N / CL..." in a narrow room is worse than a blank room.
    private func drawRoomLabel(
        _ context: inout GraphicsContext,
        room: Floorplan.Room,
        in rect: CGRect
    ) {
        // 3pt rather than 5pt. At this plan's scale a 2m room is only about
        // 40pt wide, so four points of inset is the difference between a
        // labelled room and a blank rectangle.
        let inset: CGFloat = 3
        let maxSize = CGSize(width: rect.width - inset * 2, height: rect.height - inset * 2)
        guard maxSize.width > 8, maxSize.height > 7 else { return }
        let text = room.name.uppercased()
        let words = text.split(separator: " ").map(String.init)
        let unbounded = CGSize(width: CGFloat.greatestFiniteMagnitude,
                               height: CGFloat.greatestFiniteMagnitude)

        for size in [8.0, 7.0, 6.0] as [CGFloat] {
            let tracking: CGFloat = size >= 8 ? 0.7 : (size >= 7 ? 0.4 : 0.2)
            func resolved(_ string: String) -> GraphicsContext.ResolvedText {
                context.resolve(
                    Text(string)
                        .font(.system(size: size, weight: .semibold))
                        .tracking(tracking)
                )
            }
            // No word may be wider than the room, or it gets broken and elided.
            guard words.allSatisfy({ resolved($0).measure(in: unbounded).width <= maxSize.width })
            else { continue }

            var label = resolved(text)
            label.shading = .color(Palette.inkFaint.opacity(0.85))
            let fitted = label.measure(in: maxSize)
            guard fitted.width <= maxSize.width, fitted.height <= maxSize.height else { continue }
            context.draw(
                label,
                in: CGRect(x: rect.minX + inset, y: rect.minY + inset,
                           width: fitted.width, height: fitted.height)
            )
            return
        }
    }

    private func drawPresences(_ context: inout GraphicsContext, plan: CGRect, t: Double, selectedID: String?) {
        for presence in state.presences {
            // The hub sends a zone centroid in metres. It is not a fix, so the
            // drawing treats it as an anchor and lets uncertainty wander around
            // it rather than pinning a dot to a coordinate.
            let anchor = state.floorplan.normalizedPoint(presence.position)
            let room = state.floorplan.room(named: presence.zone)
            let extent = room.map { state.floorplan.normalizedRect($0) }
                ?? CGRect(x: 0, y: 0, width: 0.25, height: 0.25)
            let center = Self.position(for: presence, anchor: anchor, extent: extent,
                                       in: plan, t: t)
            let selected = presence.id == selectedID

            switch presence.state {
            case .personMoving, .personUnresponsive:
                let signatureLost = presence.state == .personUnresponsive
                // `expected` is an orthogonal axis, so it swaps the tint rather
                // than adding a case. An unexpected person whose signature has
                // gone keeps the alarm ring and turns violet.
                let tint: Color = presence.isUnexpected
                    ? Palette.personUnexpected
                    : (signatureLost ? Palette.personUnresponsive : Palette.personMoving)
                drawPerson(&context, at: center, presence: presence, t: t,
                           tint: tint, alarm: signatureLost)
                if presence.isUnexpected {
                    drawTrackingBrackets(&context, at: center, presence: presence, t: t)
                }
                if selected {
                    drawSelectionRing(&context, at: center, radius: signatureLost ? 28 : 24, tint: tint)
                }
            case .unconfirmed, .unresolved:
                drawUnconfirmed(&context, at: center, presence: presence, t: t)
                if selected {
                    drawSelectionRing(&context, at: center, radius: 22, tint: Palette.unconfirmed)
                }
            }
        }
    }

    /// Drift around the reported centroid. Low confidence wanders further,
    /// which is the positional half of rendering confidence as coherence.
    private static func position(
        for presence: Presence,
        anchor: CGPoint,
        extent: CGRect,
        in plan: CGRect,
        t: Double
    ) -> CGPoint {
        let origin = CGPoint(x: plan.minX + anchor.x * plan.width,
                             y: plan.minY + anchor.y * plan.height)
        let room = Self.screenRect(extent, in: plan)
        let wander = (1 - presence.confidence) * 0.30 + 0.06
        let dx = sin(t * 0.33 + presence.phase) * room.width * wander * 0.5
        let dy = cos(t * 0.27 + presence.phase * 1.7) * room.height * wander * 0.5
        return CGPoint(x: origin.x + dx, y: origin.y + dy)
    }

    // MARK: A person

    /// A confirmed person: a soft coherent blob with a breathing core.
    ///
    /// Coherence is three things at once, all driven by `confidence`:
    /// blur radius, opacity, and how much the core jitters frame to frame.
    private func drawPerson(
        _ context: inout GraphicsContext,
        at center: CGPoint,
        presence: Presence,
        t: Double,
        tint: Color,
        alarm: Bool
    ) {
        let c = presence.confidence
        // Breathing drives the core's scale. When the sensor reports a rate we
        // breathe at that rate; otherwise a plausible resting default, so the
        // blob never sits perfectly still and reads as dead pixels.
        let bpm = presence.breathingBpm ?? 14
        let breath = sin(t * (bpm / 60) * 2 * .pi + presence.phase)

        // A touch larger than before, and a floor on opacity/blur rather than
        // letting either run all the way to "barely there": a dot someone is
        // meant to find and tap needs a visible edge even at low confidence.
        let baseRadius: CGFloat = alarm ? 28 : 24
        let radius = baseRadius * (1 + 0.05 * breath)

        // Halo. Blurred proportionally to uncertainty: a 0.4 presence is a
        // smear, a 0.95 presence is nearly a disc.
        var halo = context
        halo.addFilter(.blur(radius: CGFloat(8 + (1 - c) * 22)))
        halo.opacity = 0.4 + 0.4 * c
        halo.fill(
            Path(ellipseIn: CGRect(
                x: center.x - radius * 2.1, y: center.y - radius * 2.1,
                width: radius * 4.2, height: radius * 4.2
            )),
            with: .radialGradient(
                Gradient(colors: [tint.opacity(0.95), tint.opacity(0)]),
                center: center, startRadius: 0, endRadius: radius * 2.1
            )
        )

        if alarm {
            // The alarm ring. Expands and fades on a fast cycle, so the
            // presence whose signature went missing is the only thing on this
            // canvas that moves with urgency. Two rings out of phase, so there is always one
            // visible.
            for offset in [0.0, 0.5] {
                let cycle = ((t * 1.1 + offset).truncatingRemainder(dividingBy: 1))
                let r = radius * (1.5 + 2.4 * cycle)
                var ring = context
                ring.opacity = (1 - cycle) * 0.85
                ring.stroke(
                    Path(ellipseIn: CGRect(x: center.x - r, y: center.y - r, width: r * 2, height: r * 2)),
                    with: .color(tint),
                    lineWidth: 2
                )
            }
        }

        // Core. Jitters at low confidence and holds still at high confidence.
        let jitter = CGFloat((1 - c) * 2.4)
        let jx = CGFloat(sin(t * 11 + presence.phase)) * jitter
        let jy = CGFloat(cos(t * 13 + presence.phase)) * jitter
        var core = context
        core.addFilter(.blur(radius: CGFloat(1.2 + (1 - c) * 6)))
        core.opacity = 0.65 + 0.35 * c
        let coreRect = CGRect(
            x: center.x + jx - radius * 0.44,
            y: center.y + jy - radius * 0.44,
            width: radius * 0.88, height: radius * 0.88
        )
        core.fill(Path(ellipseIn: coreRect), with: .color(tint))

        // A crisp, unblurred edge at the core's boundary. The halo and core
        // above are deliberately soft — that softness *is* the confidence
        // signal — but a dot with no hard edge anywhere is genuinely difficult
        // to pick out against the grid, especially at low confidence. This
        // ring gives every presence one readable boundary regardless of how
        // uncertain the system is about it.
        var edge = context
        edge.opacity = 0.55 + 0.35 * c
        edge.stroke(
            Path(ellipseIn: coreRect.insetBy(dx: 0.5, dy: 0.5)),
            with: .color(tint),
            style: StrokeStyle(lineWidth: 1.4)
        )
    }

    /// Tracking brackets around a confirmed person the system did not expect.
    ///
    /// Four corner brackets and a slow sweep ring, in the same violet as the
    /// Burglary button. The read is "this one is being followed", which is what
    /// is actually happening, and it is the only thing on the canvas that gets
    /// a hard edge: every other presence is soft. That contrast does the work
    /// without a label, a skull, or an exclamation mark.
    ///
    /// Coherence still governs it, so the brackets sit wider and fainter on a
    /// low-confidence track. The system does not get more certain about who
    /// someone is by deciding it does not like them.
    private func drawTrackingBrackets(
        _ context: inout GraphicsContext,
        at center: CGPoint,
        presence: Presence,
        t: Double
    ) {
        let c = presence.confidence
        // Low confidence stands the box off further, so an uncertain track
        // reads as a loose one.
        let half: CGFloat = 30 + CGFloat(1 - c) * 12
        let arm = half * 0.42

        var ctx = context
        ctx.opacity = 0.45 + 0.5 * c

        var brackets = Path()
        for (sx, sy) in [(-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0)] {
            let corner = CGPoint(x: center.x + CGFloat(sx) * half,
                                 y: center.y + CGFloat(sy) * half)
            brackets.move(to: CGPoint(x: corner.x - CGFloat(sx) * arm, y: corner.y))
            brackets.addLine(to: corner)
            brackets.addLine(to: CGPoint(x: corner.x, y: corner.y - CGFloat(sy) * arm))
        }
        ctx.stroke(brackets, with: .color(Palette.personUnexpected),
                   style: StrokeStyle(lineWidth: 1.4, lineCap: .round, lineJoin: .round))

        // One slow sweep, an order of magnitude calmer than the lost-signature
        // alarm ring. An intruder is not a medical emergency and must not
        // out-shout one.
        let cycle = (t * 0.45).truncatingRemainder(dividingBy: 1)
        var sweep = context
        sweep.opacity = (1 - cycle) * 0.4 * (0.4 + 0.6 * c)
        let r = half * (0.7 + 0.8 * cycle)
        sweep.stroke(
            Path(ellipseIn: CGRect(x: center.x - r, y: center.y - r, width: r * 2, height: r * 2)),
            with: .color(Palette.personUnexpected),
            lineWidth: 1
        )
    }

    /// An unconfirmed perturbation: movement with no respiration signature.
    ///
    /// Deliberately not a blob. A dashed lozenge with jittering ticks around
    /// it, in grey, so it reads as "the radio saw something" rather than as a
    /// person. Calling police on a curtain is the failure mode this drawing
    /// exists to prevent.
    private func drawUnconfirmed(
        _ context: inout GraphicsContext,
        at center: CGPoint,
        presence: Presence,
        t: Double
    ) {
        let r: CGFloat = 15
        let box = CGRect(x: center.x - r, y: center.y - r * 0.72,
                         width: r * 2, height: r * 1.44)

        var ctx = context
        ctx.opacity = 0.45 + 0.35 * presence.confidence

        ctx.stroke(
            Path(roundedRect: box, cornerRadius: r * 0.72, style: .continuous),
            with: .color(Palette.unconfirmed),
            style: StrokeStyle(lineWidth: 1.6, dash: [3, 3],
                               dashPhase: CGFloat(t.truncatingRemainder(dividingBy: 6)) * 6)
        )

        // Ticks that flicker independently. Noise, drawn as noise.
        var ticks = Path()
        for i in 0..<7 {
            let angle = Double(i) / 7 * 2 * .pi + t * 0.4 + presence.phase
            let flicker = sin(t * 7 + Double(i) * 2.1)
            guard flicker > 0 else { continue }
            let inner = r * 1.35
            let outer = inner + CGFloat(3 + 3 * flicker)
            ticks.move(to: CGPoint(x: center.x + cos(angle) * inner,
                                   y: center.y + sin(angle) * inner * 0.8))
            ticks.addLine(to: CGPoint(x: center.x + cos(angle) * outer,
                                      y: center.y + sin(angle) * outer * 0.8))
        }
        ctx.stroke(ticks, with: .color(Palette.unconfirmed), lineWidth: 1)
    }

    /// A static ring around whichever presence's card is currently open, so
    /// the dot the card belongs to stays identifiable even after it has
    /// drifted away from where the tap landed.
    private func drawSelectionRing(_ context: inout GraphicsContext, at center: CGPoint, radius: CGFloat, tint: Color) {
        var ring = context
        ring.opacity = 0.9
        ring.stroke(
            Path(ellipseIn: CGRect(x: center.x - radius * 1.7, y: center.y - radius * 1.7,
                                   width: radius * 3.4, height: radius * 3.4)),
            with: .color(Palette.ink),
            style: StrokeStyle(lineWidth: 1.6, lineCap: .round, dash: [1, 4])
        )
    }
}

// MARK: - Detail popup

/// What used to be one row in the roster underneath the map, now surfaced on
/// demand for exactly the dot someone tapped. Works identically for a
/// confirmed person, an unexpected one, and an unconfirmed perturbation —
/// the same three states the drawing distinguishes, described here in words
/// instead of blur and colour.
private struct PresenceDetailCard: View {
    var presence: Presence
    var floorplan: Floorplan
    var onDismiss: () -> Void

    private var tint: Color {
        if presence.isUnexpected { return Palette.personUnexpected }
        switch presence.state {
        case .personMoving: return Palette.personMoving
        case .personUnresponsive: return Palette.personUnresponsive
        case .unconfirmed, .unresolved: return Palette.unconfirmed
        }
    }

    private var emphasised: Bool {
        presence.state == .personUnresponsive || presence.isUnexpected
    }

    private var headline: String {
        presence.isUnexpected ? "Unexpected person" : presence.state.headline
    }

    private var roomName: String {
        floorplan.room(named: presence.zone)?.name ?? presence.zone
    }

    private var detailText: String {
        var parts: [String] = []
        // First, so it survives truncation. This is a statement that the
        // household has no account of this person, not a claim about who they
        // are: the system does no recognition and must not imply that it does.
        if presence.isUnexpected { parts.append("Not accounted for") }
        parts.append(presence.state.detail)
        if let bpm = presence.breathingBpm { parts.append("\(Int(bpm.rounded())) breaths/min") }
        if presence.state.isPerson, presence.presenceClass != .unknown {
            parts.append(presence.presenceClass.label.lowercased())
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                Circle()
                    .fill(tint)
                    .frame(width: 9, height: 9)
                    .padding(.top, 4)

                VStack(alignment: .leading, spacing: 1) {
                    Text(headline)
                        .font(TypeScale.bodyStrong)
                        .foregroundStyle(presence.isUnexpected ? tint : Palette.ink)
                    Text(roomName)
                        .font(TypeScale.caption)
                        .foregroundStyle(Palette.inkMuted)
                }

                Spacer(minLength: 4)

                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Palette.inkMuted)
                        .frame(width: 22, height: 22)
                        .background(Circle().fill(Palette.surfaceRaised))
                }
                .accessibilityLabel("Close")
            }

            Text(detailText)
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkFaint)
                .fixedSize(horizontal: false, vertical: true)

            if let lost = presence.respirationLostS, lost > 0 {
                // How long since the last resolvable signature is the number a
                // dispatcher acts on, not a diagnostic detail, so it gets its
                // own line rather than folding into the detail sentence above.
                HStack(spacing: 5) {
                    Text(Self.duration(lost))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(Palette.personUnresponsive)
                    Text("no signature")
                        .eyebrowStyle(Palette.inkFaint)
                }
            }
        }
        .padding(Space.md)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.surfaceRaised)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(emphasised ? tint.opacity(0.55) : Palette.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.45), radius: 14, y: 8)
    }

    private static func duration(_ seconds: Double) -> String {
        let s = max(0, Int(seconds))
        return s < 60 ? "\(s)s" : String(format: "%d:%02d", s / 60, s % 60)
    }
}
