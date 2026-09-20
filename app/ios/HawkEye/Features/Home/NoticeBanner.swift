import SwiftUI

/// A notice, read from the Notices panel behind the bell icon.
///
/// Rose-magenta (`Palette.personUnexpected`), not the red the Burglary
/// button uses — that red is reserved for "you are about to dial 911," and a
/// notice is not that; it's the system telling you what it saw so a tap is
/// informed, not urging you to make one.
///
/// It is dismissible and it does not dial. The incident button lives on a
/// different screen entirely now and still takes a 1.5s hold, which is the
/// separation the whole product rests on: the system informs, a person
/// decides.
struct NoticeBanner: View {
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
        HStack(alignment: .top, spacing: Space.sm) {
            Image(systemName: "person.fill.viewfinder")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Palette.personUnexpected)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 3) {
                Text(notice.title)
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(Palette.personUnexpected)
                // The time is load-bearing, not decoration. A notice records
                // where someone was when it was raised, and the presence keeps
                // moving after that, so without a timestamp the banner reads as
                // a live position that disagrees with the roster underneath it.
                // "Living room" over a roster row saying "Kitchen" looks like a
                // bug; "Living room, 2:01" reads as the history it is.
                //
                // The SMS already says the time for the same reason. Two
                // renderings of one notice should not disagree about what it is.
                Text("\(notice.body) \(Self.clock.string(from: notice.raisedAt))")
                    .font(TypeScale.body)
                    .foregroundStyle(Palette.ink.opacity(0.85))

                // The two distinctions this notice guards, side by side rather
                // than stacked, so neither reads as the default. One button
                // vouches for a session; the other writes a name down forever,
                // and conflating them would routinely persist a stranger
                // because someone wanted the banner gone.
                HStack(spacing: Space.md) {
                    Button("This is expected", action: onApprove)
                        .buttonStyle(.plain)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Palette.personUnexpected)

                    Button("Remember this visitor", action: onRemember)
                        .buttonStyle(.plain)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Palette.ink.opacity(0.75))
                }
                .padding(.top, 4)
            }

            Spacer(minLength: Space.sm)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Palette.inkMuted)
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss")
        }
        .padding(.horizontal, Space.lg)
        .padding(.vertical, Space.md)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.personUnexpected.opacity(0.16))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.personUnexpected.opacity(0.5), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(notice.title). \(notice.body) Raised at \(Self.clock.string(from: notice.raisedAt))."
        )
    }

    /// Wall-clock time, local, no seconds. Built once: a `DateFormatter` per
    /// render is expensive and this view redraws on every state tick.
    private static let clock: DateFormatter = {
        let f = DateFormatter()
        f.timeStyle = .short
        f.dateStyle = .none
        return f
    }()
}
