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
        ZStack {
            Palette.ground.ignoresSafeArea()

            switch model.stage {
            case .connect:
                ConnectView()
                    .transition(.opacity.combined(with: .scale(scale: 1.04)))
            case .main(let hubName):
                HomeView(hubName: hubName)
                    .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
        }
        .animation(Motion.standard, value: model.stage)
    }
}
