import SwiftUI
import UIKit

/// A notice, presented as a centered modal card.
///
/// This replaced `NoticeBanner`, an inline violet-outlined banner at the top
/// of the camera page. The outline read as "warning chrome"; what a notice
/// actually is is a detection event with an AI-generated description
/// underneath, so the card looks like a normal surface — `Palette.surface`,
/// a neutral hairline, the same shape every other sheet-presented card in
/// this app uses — and colour is reserved for the one place it still carries
/// state: a small accent dot and the header's tint. See `HomeView` for how
/// this is presented (`.sheet(item:)` over the newest notice).
///
/// It is dismissible and it does not dial. The incident controls live on
/// `HomeView` underneath this sheet, and closing this card does not touch
/// them: the system informs, a person decides.
///
/// Adapted from `app/ios/HawkEyeWatch/Views/NoticeScreen.swift`'s layout —
/// still frame, the camera's sentence, two actions — sized for a phone
/// rather than a wrist.
struct NoticeCard: View {
    let notice: Notice
    let onDismiss: () -> Void
    /// "This is expected." Vouches for the presence this session only. Nothing
    /// persists, which is the entire reason this is a separate control from
    /// `onRemember` rather than a second tap on the same button.
    let onApprove: () -> Void
    /// "Remember this visitor." Names the person and, when a device just
    /// joined, offers to bind it. Permanent.
    let onRemember: () -> Void

    var body: some View {
        ScrollView {
            card
                .padding(.horizontal, Space.gutter)
                .padding(.vertical, Space.xl)
        }
        .background(Palette.ground.ignoresSafeArea())
        .accessibilityElement(children: .contain)
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: Space.md) {
            header
            frame
            Text(notice.narration ?? notice.body)
                .font(TypeScale.body)
                .foregroundStyle(Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
            actions
        }
        .padding(Space.lg)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.4), radius: 24, y: 12)
    }

    // MARK: Pieces

    private var header: some View {
        HStack(alignment: .top, spacing: Space.sm) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: Space.xs) {
                    Circle()
                        .fill(Palette.personUnexpected)
                        .frame(width: 7, height: 7)
                    Text("Unexpected motion detected")
                        .font(TypeScale.heading)
                        .foregroundStyle(Palette.ink)
                }
                Text(Self.clock.string(from: notice.raisedAt))
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
            }

            Spacer(minLength: Space.sm)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Palette.inkMuted)
                    .frame(width: 30, height: 30)
                    .background(Circle().fill(Palette.surfaceRaised))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
        }
    }

    /// The photograph, or an honest statement that there is not one.
    ///
    /// A missing frame is not a broken image well. It means the shield never
    /// opened, and saying that is more useful than a grey rectangle — same
    /// rule as the watch's `NoticeScreen`.
    @ViewBuilder
    private var frame: some View {
        ZStack {
            if let data = notice.stillFrame?.jpeg, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                noFrame
            }
        }
        .aspectRatio(16.0 / 9.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.hairline, lineWidth: 1)
        )
    }

    private var noFrame: some View {
        ZStack {
            Palette.surfaceRaised
            Text("The shield stayed closed.\nThere is no picture.")
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkMuted)
                .multilineTextAlignment(.center)
        }
    }

    // The two distinctions this card guards, side by side rather than
    // stacked, so neither reads as the default. One button vouches for a
    // session; the other writes a name down forever, and conflating them
    // would routinely persist a stranger because someone wanted the card
    // gone.
    private var actions: some View {
        HStack(spacing: Space.md) {
            Button("This is expected", action: onApprove)
                .buttonStyle(.plain)
                .font(TypeScale.bodyStrong)
                .foregroundStyle(Palette.personUnexpected)

            Button("Remember this visitor", action: onRemember)
                .buttonStyle(.plain)
                .font(TypeScale.caption)
                .foregroundStyle(Palette.inkMuted)
        }
        .padding(.top, Space.xs)
    }

    /// Wall-clock time, local, no seconds. Built once: a `DateFormatter` per
    /// render is expensive and this view can redraw on every state tick.
    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.timeStyle = .short
        f.dateStyle = .none
        return f
    }()
}
