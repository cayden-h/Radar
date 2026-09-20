import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// A stand-in for a frame the camera did not take.
///
/// Mock mode has to put something on the wrist where the still frame goes,
/// because a notice with an empty image well does not demonstrate the thing the
/// camera pivot bought. This draws that something.
///
/// **It is never passed off as a photograph.** Everything built here travels
/// with `WatchNotice.simulated` set, and the views draw a marker off that flag
/// rather than off a comment. The root `CLAUDE.md` honesty rule is explicit:
/// limits are carried in the data itself.
///
/// It also deliberately does not look like a person. A recognisable synthetic
/// human would be a fabricated record of someone being somewhere, which is the
/// one thing a system that emails police must never manufacture. What it draws
/// is a camera's empty frame with its burn-in, which is honest about being a
/// placeholder while still showing the layout the real frame will occupy.
@MainActor
enum SimulatedCameraFrame {

    /// Small on purpose. This crosses WatchConnectivity to a wrist.
    static let defaultSize = CGSize(width: 320, height: 180)

    static func jpeg(
        room: String?,
        capturedAt: Date = Date(),
        size: CGSize = defaultSize,
        quality: CGFloat = 0.7
    ) -> Data? {
        #if canImport(UIKit)
        let renderer = ImageRenderer(content: Canvas(room: room, capturedAt: capturedAt)
            .frame(width: size.width, height: size.height))
        renderer.scale = 1
        return renderer.uiImage?.jpegData(compressionQuality: quality)
        #else
        return nil
        #endif
    }

    /// The frame itself. A dark room, a light source, and a camera's burn-in.
    private struct Canvas: View {
        var room: String?
        var capturedAt: Date

        private var stamp: String {
            capturedAt.formatted(date: .omitted, time: .standard)
        }

        var body: some View {
            ZStack {
                // The low-light look a shielded camera has in the first second
                // after the shutter clears: mostly black, one source of light.
                LinearGradient(
                    colors: [Color(hex: 0x11161F), Color(hex: 0x05070A)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )

                RadialGradient(
                    colors: [Color(hex: 0x2A3647).opacity(0.75), .clear],
                    center: UnitPoint(x: 0.72, y: 0.26),
                    startRadius: 2,
                    endRadius: 150
                )

                // Sensor noise, so it does not read as a flat placeholder swatch.
                GeometryReader { geometry in
                    SwiftUI.Canvas { context, _ in
                        var generator = SplitMix(seed: 0x9E3779B9)
                        for _ in 0..<420 {
                            let x = Double(generator.next() % 1_000) / 1_000 * geometry.size.width
                            let y = Double(generator.next() % 1_000) / 1_000 * geometry.size.height
                            let a = Double(generator.next() % 100) / 100 * 0.06
                            context.fill(
                                Path(ellipseIn: CGRect(x: x, y: y, width: 1.4, height: 1.4)),
                                with: .color(.white.opacity(a))
                            )
                        }
                    }
                }

                // The burn-in a fixed camera writes into its own frame.
                VStack {
                    HStack {
                        Text("SHIELD OPEN")
                        Spacer()
                        Text(stamp)
                    }
                    Spacer()
                    HStack {
                        Text((room ?? "Unknown room").uppercased())
                        Spacer()
                    }
                }
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(.white.opacity(0.68))
                .padding(10)
            }
        }
    }

    /// A tiny deterministic generator, so the same notice renders the same grain
    /// every time and the demo does not shimmer between runs.
    private struct SplitMix {
        var seed: UInt64
        mutating func next() -> UInt64 {
            seed &+= 0x9E3779B97F4A7C15
            var z = seed
            z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
            z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
            return z ^ (z >> 31)
        }
    }
}
