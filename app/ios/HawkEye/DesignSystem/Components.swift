import SwiftUI

/// The Hawk Eye wordmark. An aperture glyph and the name.
///
/// Drawn rather than shipped as an asset so it stays crisp at any size and can
/// pulse with the connection state without a second asset.
struct Wordmark: View {
    var size: CGFloat = 30
    var breathing: Bool = false

    @State private var phase: Double = 0

    var body: some View {
        HStack(spacing: size * 0.36) {
            ZStack {
                Circle()
                    .strokeBorder(Palette.ink.opacity(0.9), lineWidth: size * 0.055)
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.55), lineWidth: size * 0.05)
                    .padding(size * 0.17)
                    .scaleEffect(breathing ? 1 + 0.08 * phase : 1)
                Circle()
                    .fill(Palette.calm)
                    .frame(width: size * 0.16, height: size * 0.16)
                    .opacity(breathing ? 0.55 + 0.45 * phase : 1)
            }
            .frame(width: size, height: size)

            Text("Hawk Eye")
                .font(.system(size: size * 0.82, weight: .semibold, design: .rounded))
                .foregroundStyle(Palette.ink)
                .kerning(-0.2)
        }
        .onAppear {
            guard breathing else { return }
            withAnimation(Motion.ambient) { phase = 1 }
        }
        .accessibilityElement()
        .accessibilityLabel("Hawk Eye")
    }
}

/// A near-black backdrop with a faint radial glow seeded from two fixed
/// points, echoing the aperture motif in `Wordmark`. Used in place of a flat
/// `Palette.ground` fill so idle screens read as atmospheric rather than a
/// blank void.
///
/// Attach via `.background(AmbientBackground())` on the screen's content,
/// **not** as a `ZStack` sibling. It ignores the safe area itself, so a
/// sibling placement inflates the whole `ZStack`'s reported size to the full
/// device bounds and centers non-flexible content inside that oversized
/// frame instead of pinning it under the status bar — a large dead band top
/// and bottom. `.background()` sizes this to the content's already-resolved
/// frame instead, so the content lays out normally and the glow just bleeds
/// behind it to the true screen edges.
struct AmbientBackground: View {
    var tint: Color = Palette.calm

    var body: some View {
        ZStack {
            Palette.ground
            RadialGradient(
                colors: [tint.opacity(0.10), Color.clear],
                center: UnitPoint(x: 0.5, y: 0.06),
                startRadius: 0,
                endRadius: 520
            )
            RadialGradient(
                colors: [Palette.surfaceRaised.opacity(0.45), Color.clear],
                center: UnitPoint(x: 0.88, y: 0.96),
                startRadius: 0,
                endRadius: 420
            )
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
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
/// `glow: true` adds a soft outer shadow in the card's tint (or
/// `Palette.calm` when no tint is given). Reserved for the small number of
/// elements on a screen that should draw the eye — most cards leave it at the
/// default `false`, or nothing would stand out.
struct Card<Content: View>: View {
    var tint: Color = .clear
    var glow: Bool = false
    @ViewBuilder var content: Content

    private var glowTint: Color { tint == .clear ? Palette.calm : tint }

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
            .shadow(color: glow ? glowTint.opacity(0.22) : .clear, radius: 22, x: 0, y: 10)
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
