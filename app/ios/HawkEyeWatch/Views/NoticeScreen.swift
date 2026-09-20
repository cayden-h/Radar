import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// The still frame, the camera's sentence, and two controls.
///
/// **This is the demo's emotional beat.** The wrist buzzes about three seconds
/// after someone walks in, and what it says is what the camera is looking at,
/// not "motion detected". A generic string here throws away the entire camera
/// pivot, so the phone refuses to send a notice without a sentence and this
/// screen has no fallback copy to fall back to.
///
/// Two controls, not three. **Start Incident** is held, because an accidental
/// press calls 911. **This is expected** is tapped, because its worst case is a
/// banner going away. Naming a visitor needs a keyboard and stays on the phone,
/// and the two are deliberately not merged: one is a mute button and the other
/// changes what the house believes.
struct NoticeScreen: View {

    var notice: WatchNotice
    var isSending: Bool
    var deliveryFailed: Bool
    var now: Date
    var act: (WatchAction) -> Void
    var dismissFailure: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.sm) {

                header

                frame

                Text(notice.narration)
                    .font(.system(size: 14, weight: .medium, design: .rounded))
                    .foregroundStyle(Palette.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(Space.sm)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassPanel(cornerRadius: Radius.sm)

                if deliveryFailed {
                    failureBanner
                } else if isSending {
                    sendingRow
                } else {
                    controls
                }
            }
            .padding(.horizontal, Space.sm)
            .padding(.bottom, Space.md)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: Pieces

    private var header: some View {
        HStack(spacing: Space.xs) {
            Circle()
                .fill(Palette.personUnexpected)
                .frame(width: 7, height: 7)
            Text("Unexpected")
                .eyebrowStyle(Palette.personUnexpected)
            Spacer(minLength: 0)
            Text(IdleScreen.elapsed(now.timeIntervalSince(notice.raisedAt)))
                .font(.system(size: 11, weight: .medium, design: .monospaced))
                .foregroundStyle(Palette.inkFaint)
        }
    }

    /// The photograph, or an honest statement that there is not one.
    ///
    /// A missing frame is not a broken image well. It means the shield never
    /// opened, and saying that is more useful than a grey rectangle.
    @ViewBuilder
    private var frame: some View {
        ZStack(alignment: .bottomTrailing) {
            #if canImport(UIKit)
            if let data = notice.stillFrame, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                noFrame
            }
            #else
            noFrame
            #endif

            if notice.simulated {
                // The limit travels in the data and is drawn from it. Nothing
                // here can be mistaken on stage for something a lens saw.
                Text("SIMULATED")
                    .font(.system(size: 8, weight: .bold, design: .monospaced))
                    .foregroundStyle(Palette.ink.opacity(0.85))
                    .padding(.horizontal, 4)
                    .padding(.vertical, 2)
                    .background(Capsule().fill(Palette.ground.opacity(0.75)))
                    .padding(4)
            }
        }
        .aspectRatio(16.0 / 9.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.glassBorder, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.35), radius: 12, y: 6)
    }

    private var noFrame: some View {
        ZStack {
            Rectangle().fill(.ultraThinMaterial.opacity(0.12))
            Rectangle().fill(Palette.glassTint)
            Text("The shield stayed closed.\nThere is no picture.")
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(Palette.inkMuted)
                .multilineTextAlignment(.center)
        }
    }

    private var controls: some View {
        VStack(spacing: Space.sm) {
            HoldToConfirm(
                title: WatchAction.startIncident.title,
                tint: Palette.personUnexpected
            ) {
                act(.startIncident)
            }

            TapControl(title: WatchAction.expected.title) {
                act(.expected)
            }

            Text("To name this visitor, use your phone.")
                .font(.system(size: 10, design: .rounded))
                .foregroundStyle(Palette.inkFaint)
                .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private var sendingRow: some View {
        HStack(spacing: Space.sm) {
            ProgressView()
                .controlSize(.small)
            Text("Sending to your phone")
                .font(.system(size: 13, weight: .medium, design: .rounded))
                .foregroundStyle(Palette.inkMuted)
        }
        .frame(maxWidth: .infinity, minHeight: 48)
    }

    private var failureBanner: some View {
        VStack(spacing: Space.sm) {
            Text("That did not reach your phone.")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text("Nothing was raised. Try again, or use your phone.")
                .font(.system(size: 11, design: .rounded))
                .foregroundStyle(Palette.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
            TapControl(title: "Try again", action: dismissFailure)
        }
        .frame(maxWidth: .infinity)
        .padding(Space.sm)
        .glassPanel(tint: Palette.personUnresponsive)
    }
}
