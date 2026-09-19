import SwiftUI

@main
struct HawkEyeApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(.dark)
                .tint(Palette.ink)
        }
    }
}

/// Stage 1 to stage 2. A crossfade with a slight scale, so the Connect screen
/// recedes rather than sliding away: the main screen is a place you arrive at,
/// not a page you push.
struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.stage {
            case .connect:
                ConnectView()
                    .transition(.opacity.combined(with: .scale(scale: 1.04)))
            case .main(let hubName):
                HomeView(hubName: hubName)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
        }
        // `.frame` before `.background`, not a `ZStack` sibling: a ground
        // fill placed as a ZStack sibling ignores the safe area and reports
        // itself at the full device size, which inflates what the whole
        // ZStack is measured at. Neither ConnectView nor HomeView's content
        // is flexible enough to fill that inflated frame on its own, so it
        // ends up centered inside it instead of pinned under the status bar
        // — a large dead band top and bottom on every screen. Forcing this
        // frame to fill first means the switch content is what gets sized to
        // the screen; the background then just paints behind it.
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.ground.ignoresSafeArea())
        .animation(Motion.standard, value: model.stage)
    }
}
