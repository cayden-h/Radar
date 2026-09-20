import SwiftUI

/// The backdrop behind every screen.
///
/// This used to be the flat `ground` colour under two quiet, static
/// elements — a sensing-grid motif borrowed from `InteriorView` rather than
/// a decorative glow, on the grounds that Hawk Eye's actual job is reading a
/// field of RF reflections, not looking like an "AI app." That argument still
/// holds for the grid and the rings below, which is why both survive
/// unchanged. It did not survive contact with the "Aura" direction: a dark
/// gradient against near-black cards read as no change at all, and a
/// frosted-glass panel has nothing to look frosted *over* if nothing behind
/// it varies. So there are now two additional, deliberately restrained
/// elements:
///
/// 1. A sparse dot grid, unchanged — see above.
/// 2. A pair of concentric rings pinned to one corner, unchanged, static,
///    like a single radar return.
/// 3. **New:** two soft blurred fields of colour (`Palette.auraGlow` /
///    `auraGlowSecondary`), one per top corner, low-opacity and never
///    animated — the one concession to the Aura reference, sized to give
///    the gradient and the glass panels in front of it something to
///    actually read against.
struct AmbientBackground: View {
    var body: some View {
        GeometryReader { geo in
            ZStack {
                Palette.groundGradient

                Circle()
                    .fill(Palette.auraGlow.opacity(0.30))
                    .frame(width: geo.size.width * 1.1)
                    .position(x: geo.size.width * 0.08, y: geo.size.height * 0.02)
                    .blur(radius: 70)

                Circle()
                    .fill(Palette.auraGlowSecondary.opacity(0.16))
                    .frame(width: geo.size.width * 0.9)
                    .position(x: geo.size.width * 1.02, y: geo.size.height * 0.34)
                    .blur(radius: 80)

                Canvas { context, size in
                    let spacing: CGFloat = 30
                    var path = Path()
                    var y: CGFloat = 0
                    while y <= size.height {
                        var x: CGFloat = 0
                        while x <= size.width {
                            path.addEllipse(in: CGRect(x: x - 0.5, y: y - 0.5, width: 1, height: 1))
                            x += spacing
                        }
                        y += spacing
                    }
                    context.fill(path, with: .color(Palette.calm.opacity(0.22)))
                }

                let ringCenter = CGPoint(x: geo.size.width * 0.94, y: geo.size.height * 0.015)
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.18), lineWidth: 1)
                    .frame(width: geo.size.width * 1.2)
                    .position(ringCenter)
                Circle()
                    .strokeBorder(Palette.calm.opacity(0.11), lineWidth: 1)
                    .frame(width: geo.size.width * 1.8)
                    .position(ringCenter)
            }
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
    }
}
