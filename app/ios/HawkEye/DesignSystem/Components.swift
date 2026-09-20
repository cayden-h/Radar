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
struct Card<Content: View>: View {
    var tint: Color = .clear
    @ViewBuilder var content: Content

    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .fill(Palette.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(
                        tint == .clear ? Palette.hairline : tint.opacity(0.35),
                        lineWidth: 1
                    )
            )
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
