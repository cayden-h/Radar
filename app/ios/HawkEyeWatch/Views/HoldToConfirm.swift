import SwiftUI

/// A control that fires only after it has been held.
///
/// **Hold rather than a confirmation dialog**, and the reasoning is specific to
/// a panicking person, from `app/CLAUDE.md`: a dialog makes you find and hit a
/// second target with shaking hands, and can itself be dismissed by accident. A
/// hold is one gesture on the target you already found, it gives continuous
/// feedback, and releasing cancels it. Apple's Emergency SOS uses the same
/// pattern, so it needs no teaching.
///
/// **The feedback is visual only.** No haptic, no sound. On a watch the buzz is
/// reserved for the notice arriving, which is the thing that has to wake
/// someone; a confirmation that buzzes while the resident is already reading
/// the screen adds nothing and an intrusion is exactly the situation where
/// noise may be unsafe.
struct HoldToConfirm: View {

    var title: String
    var tint: Color
    var duration: Double = WatchConfig.holdDuration
    var action: () -> Void

    @State private var progress: Double = 0
    @State private var holding = false
    @State private var completion: Task<Void, Never>?

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(tint.opacity(0.18))

            // The fill is the progress. It makes release-to-cancel discoverable
            // without a line of instructional text, which there is no room for.
            GeometryReader { geometry in
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                    .fill(tint.opacity(0.62))
                    .frame(width: geometry.size.width * progress)
            }

            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(tint.opacity(0.7), lineWidth: 1)

            VStack(spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: .semibold, design: .rounded))
                    .foregroundStyle(Palette.ink)
                Text(holding ? "Keep holding" : "Hold")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Palette.ink.opacity(0.7))
                    .contentTransition(.opacity)
            }
            .padding(.horizontal, Space.sm)
            .multilineTextAlignment(.center)
        }
        .frame(minHeight: 48)
        .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in begin() }
                .onEnded { _ in cancel() }
        )
        .accessibilityElement()
        .accessibilityLabel(title)
        .accessibilityHint("Hold for \(Int(duration)) seconds to confirm")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { action() }
        .onDisappear { completion?.cancel() }
    }

    private func begin() {
        guard !holding else { return }
        holding = true
        withAnimation(.linear(duration: duration)) { progress = 1 }
        completion = Task {
            try? await Task.sleep(for: .seconds(duration))
            guard !Task.isCancelled else { return }
            action()
            holding = false
            withAnimation(Motion.snappy) { progress = 0 }
        }
    }

    private func cancel() {
        completion?.cancel()
        completion = nil
        guard holding else { return }
        holding = false
        withAnimation(Motion.snappy) { progress = 0 }
    }
}

/// A single-tap control, for the actions whose worst case is a banner going
/// away. Held controls and tapped controls are visually distinct on purpose.
struct TapControl: View {
    var title: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 14, weight: .medium, design: .rounded))
                .foregroundStyle(Palette.ink)
                .frame(maxWidth: .infinity, minHeight: 40)
                .background(
                    RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                        .fill(Palette.surfaceRaised)
                )
        }
        .buttonStyle(.plain)
    }
}
