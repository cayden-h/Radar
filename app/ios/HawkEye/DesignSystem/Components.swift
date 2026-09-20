import SwiftUI

/// The Hawk Eye wordmark. The mascot and the name.
///
/// The glyph is `Assets.xcassets/Mascot`, sized off the same `size` parameter
/// every call site already passes, so swapping the drawn aperture glyph for
/// the mascot image changed nothing about how any screen lays out around it.
struct Wordmark: View {
    var size: CGFloat = 30
    var breathing: Bool = false

    @State private var phase: Double = 0

    var body: some View {
        HStack(spacing: size * 0.36) {
            Image("Mascot")
                .resizable()
                .scaledToFit()
                .frame(width: size, height: size)
                .scaleEffect(breathing ? 1 + 0.05 * phase : 1)

            Text("Radar")
                .font(.system(size: size * 0.82, weight: .semibold, design: .rounded))
                .foregroundStyle(Palette.ink)
                .kerning(-0.2)
        }
        .onAppear {
            guard breathing else { return }
            withAnimation(Motion.ambient) { phase = 1 }
        }
        .accessibilityElement()
        .accessibilityLabel("Radar")
    }
}

/// Four bars. Empty bars are drawn rather than omitted, so rows do not change
/// width as signal changes.
struct SignalBars: View {
    var level: Int
    var tint: Color = Palette.ink

    var body: some View {
        HStack(alignment: .bottom, spacing: 2.5) {
            ForEach(1...4, id: \.self) { index in
                Capsule(style: .continuous)
                    .fill(index <= level ? tint : Palette.inkFaint.opacity(0.28))
                    .frame(width: 3, height: 5 + CGFloat(index) * 3.5)
            }
        }
        .accessibilityLabel("Signal \(level) of 4")
    }
}

/// A card. One corner radius, one border, used everywhere so nothing drifts.
///
/// Backed by `View.glassPanel` — a frosted material over the ambient
/// gradient, rather than an opaque fill, so a card reads as a pane held up
/// to the dusk behind it instead of a solid slab dropped on top of it.
struct Card<Content: View>: View {
    var tint: Color = .clear
    @ViewBuilder var content: Content

    var body: some View {
        content.glassPanel(tint: tint)
    }
}

extension View {
    /// The frosted-glass panel every surface in Radar now shares: a blurred
    /// material tinted faintly with the brand purple, bordered with
    /// `Palette.glassBorder` instead of a flat fill bordered with
    /// `Palette.hairline`. One corner radius and one border recipe, applied
    /// everywhere a `RoundedRectangle` used to just fill `Palette.surface`,
    /// so no panel in the app quietly reverts to the old opaque look.
    func glassPanel(cornerRadius: CGFloat = Radius.lg, tint: Color = .clear) -> some View {
        self
            // `.ultraThinMaterial` at full strength is still a fairly opaque
            // dark-grey fill in dark mode — cut further so the gradient
            // behind a panel actually shows through it. The tradeoff this
            // buys is real transparency for real legibility: content drawn
            // on top now has to carry its own brightness (closer to
            // `Palette.ink`) rather than leaning on an opaque backing.
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(.ultraThinMaterial.opacity(0.12))
            )
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(Palette.glassTint)
            )
            .overlay(
                // A brighter hairline along the top edge only, under the full
                // border below — the "light catching the rim of the glass"
                // cue that a single flat-opacity stroke can't give, and the
                // detail that most reads as "glass" rather than "dark card."
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(
                            colors: [Color.white.opacity(0.28), Color.white.opacity(0)],
                            startPoint: .top,
                            endPoint: .bottom
                        ),
                        lineWidth: 1
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        tint == .clear ? Palette.glassBorder : tint.opacity(0.5),
                        lineWidth: 1
                    )
            )
            .shadow(color: .black.opacity(0.35), radius: 18, y: 10)
    }
}

/// Scale-and-dim press feedback. Used on everything tappable so the app has one
/// touch response rather than five.
struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.975

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .opacity(configuration.isPressed ? 0.86 : 1)
            .animation(Motion.snappy, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == PressableStyle {
    static var pressable: PressableStyle { PressableStyle() }
}

/// A press-and-hold control for every risky or irreversible action in the
/// app: raising an incident, ending a call. Per `app/CLAUDE.md`, these use a
/// 1.5s hold with continuous visual feedback rather than a modal dialog,
/// because a modal makes a panicking user find and hit a second target, and a
/// hold gives release-to-cancel on the target they already found.
///
/// Feedback is **purely visual** — no haptics, no sound — so it behaves
/// correctly in silent mode, where a confirmation that buzzes would defeat
/// the mode it is confirming inside of.
struct HoldToConfirmButton<Label: View>: View {
    var duration: TimeInterval = 1.5
    var tint: Color
    var cornerRadius: CGFloat = Radius.md
    /// Clips to a circle instead of a rounded rectangle. Used for the
    /// filled, icon-only incident buttons on Home.
    var circular: Bool = false
    var accessibilityLabel: String
    var action: () -> Void
    @ViewBuilder var label: () -> Label

    @State private var progress: CGFloat = 0
    @State private var holdGeneration: Int = 0

    var body: some View {
        label()
            .overlay(alignment: .bottom) {
                GeometryReader { geo in
                    Rectangle()
                        .fill(tint.opacity(0.4))
                        .frame(height: geo.size.height * progress)
                }
                .allowsHitTesting(false)
            }
            .clipShape(circular ? AnyShape(Circle()) : AnyShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)))
            .contentShape(circular ? AnyShape(Circle()) : AnyShape(Rectangle()))
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in beginHoldIfNeeded() }
                    .onEnded { _ in cancelHold() }
            )
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel(accessibilityLabel)
            .accessibilityHint("Double tap and hold for \(Int(duration)) seconds to confirm")
            .accessibilityAction {
                // VoiceOver cannot perform a timed hold gesture, so a double
                // tap fires the action immediately for that audience.
                action()
            }
    }

    private func beginHoldIfNeeded() {
        guard progress == 0 else { return }
        holdGeneration += 1
        let thisHold = holdGeneration
        withAnimation(.linear(duration: duration)) { progress = 1 }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            guard thisHold == holdGeneration else { return }
            progress = 0
            action()
        }
    }

    private func cancelHold() {
        guard progress > 0 else { return }
        holdGeneration += 1
        withAnimation(Motion.snappy) { progress = 0 }
    }
}
