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
/// 2. `.personUnresponsive` - a person who is not responding. Red, pulsing
///    hard, with an alarm ring around it. **The loudest thing on screen.**
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
struct InteriorView: View {
    var state: InteriorState

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: false)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            Canvas(opaque: false, rendersAsynchronously: false) { context, size in
                let plan = Self.planRect(in: size, aspect: Self.aspect(of: state.floorplan))
                drawGrid(&context, plan: plan)
                drawRooms(&context, plan: plan)
                drawPresences(&context, plan: plan, t: t)
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
        .accessibilityElement()
        .accessibilityLabel(accessibilitySummary)
    }

    private var accessibilitySummary: String {
        guard !state.presences.isEmpty else { return "Nothing detected inside." }
        return state.presences.map { p in
            let room = state.floorplan.room(named: p.zone)?.name ?? p.zone
            let headline = p.isUnexpected ? "Unexpected person, \(p.state.headline.lowercased())," : p.state.headline
            return "\(headline) in the \(room)."
        }.joined(separator: " ")
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
        let inset: CGFloat = 5
        let maxSize = CGSize(width: rect.width - inset * 2, height: rect.height - inset * 2)
        guard maxSize.width > 8, maxSize.height > 7 else { return }
        let text = room.name.uppercased()
        let words = text.split(separator: " ").map(String.init)
        let unbounded = CGSize(width: CGFloat.greatestFiniteMagnitude,
                               height: CGFloat.greatestFiniteMagnitude)

        for size in [8.0, 7.0] as [CGFloat] {
            let tracking: CGFloat = size >= 8 ? 0.7 : 0.4
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

    private func drawPresences(_ context: inout GraphicsContext, plan: CGRect, t: Double) {
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

            switch presence.state {
            case .personMoving, .personUnresponsive:
                let unresponsive = presence.state == .personUnresponsive
                // `expected` is an orthogonal axis, so it swaps the tint rather
                // than adding a case. An unexpected person who is also
                // unresponsive keeps the alarm ring and turns violet.
                let tint: Color = presence.isUnexpected
                    ? Palette.personUnexpected
                    : (unresponsive ? Palette.personUnresponsive : Palette.personMoving)
                drawPerson(&context, at: center, presence: presence, t: t,
                           tint: tint, alarm: unresponsive)
                if presence.isUnexpected {
                    drawTrackingBrackets(&context, at: center, presence: presence, t: t)
                }
            case .unconfirmed, .unresolved:
                drawUnconfirmed(&context, at: center, presence: presence, t: t)
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

        let baseRadius: CGFloat = alarm ? 26 : 22
        let radius = baseRadius * (1 + 0.05 * breath)

        // Halo. Blurred proportionally to uncertainty: a 0.4 presence is a
        // smear, a 0.95 presence is nearly a disc.
        var halo = context
        halo.addFilter(.blur(radius: CGFloat(10 + (1 - c) * 26)))
        halo.opacity = 0.34 + 0.4 * c
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
            // The alarm ring. Expands and fades on a fast cycle, so an
            // unresponsive person is the only thing on this canvas that moves
            // with urgency. Two rings out of phase, so there is always one
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
        core.opacity = 0.55 + 0.45 * c
        core.fill(
            Path(ellipseIn: CGRect(
                x: center.x + jx - radius * 0.44,
                y: center.y + jy - radius * 0.44,
                width: radius * 0.88, height: radius * 0.88
            )),
            with: .color(tint)
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

        // One slow sweep, an order of magnitude calmer than the unresponsive
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
        ctx.opacity = 0.35 + 0.35 * presence.confidence

        ctx.stroke(
            Path(roundedRect: box, cornerRadius: r * 0.72, style: .continuous),
            with: .color(Palette.unconfirmed),
            style: StrokeStyle(lineWidth: 1.2, dash: [3, 3],
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
}
