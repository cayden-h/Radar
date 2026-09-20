import SwiftUI

/// The live camera feed on Home, where the floor plan used to be.
///
/// **Front-end only, for now.** No computer-vision pipeline is wired up —
/// this is the honest placeholder for one. `selectedCamera` is real, local UI state; only camera 1
/// has anything behind it in this project's scope, but the second slot is
/// left toggleable because the hub is built to carry more than one feed
/// eventually, and the switch itself costs nothing to ship now. It is a pop-out
/// menu rather than an inline toggle so a third or fourth camera is a new row,
/// not a redesign.
struct CameraFeedView: View {
    @State private var selectedCamera = 1

    var body: some View {
        ZStack {
            Color.clear.glassPanel()

            Image(systemName: "video.fill")
                .font(.system(size: 40, weight: .regular))
                .foregroundStyle(Palette.ink.opacity(0.7))
        }
        // Grouped and labelled *before* the switch is overlaid on top, so
        // VoiceOver gets one element for the (decorative) feed placeholder
        // and a separate, reachable element for the interactive menu below —
        // grouping after the overlay would swallow the switch into a single
        // static element and make it untappable by VoiceOver entirely.
        .accessibilityElement()
        .accessibilityLabel("Camera \(selectedCamera) feed, not yet connected")
        .overlay(alignment: .topTrailing) {
            cameraSwitch
                .padding(10)
        }
        .aspectRatio(4.0 / 3.0, contentMode: .fit)
    }

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
