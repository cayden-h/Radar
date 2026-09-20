import SwiftUI

/// The backdrop behind every screen. Two elements, both quiet, both drawn
/// from the same language the product already uses rather than invented for
/// decoration:
///
/// 1. A sparse dot grid — the same motif `InteriorView` draws under the
///    floor plan to represent the sensed space. Reusing it here instead of a
///    soft gradient blob is the point: the one thing Hawk Eye actually does
///    is read a field of RF reflections, so the chrome around the product
///    is built from that, not from a stock "AI app" glow.
/// 2. A pair of concentric rings pinned to one corner, like a single radar
///    return. Static — nothing here pulses or drifts — because the
///    background's job is to sit still and let the actual sensing data (the
///    presences that *do* move) be the only thing in motion on screen.
///
/// Both are low-opacity purple, matching the mascot, and neither competes
/// with foreground content or costs anything semantically: nothing here
/// means "danger" or "state," so it can never be confused with the palette
/// that does.
struct AmbientBackground: View {
    var body: some View {
        GeometryReader { geo in
            ZStack {
                Palette.groundGradient

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
