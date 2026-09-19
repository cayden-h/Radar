import SwiftUI

/// A notice, on the home screen.
///
/// Violet, matching `Palette.personUnexpected` and the Burglary button, because
/// the presence it describes is already drawn in that colour on the floorplan
/// and in the roster. One colour, one meaning.
///
/// It is dismissible and it does not dial. The incident buttons are further down
/// the screen and still take a 1.5s hold, which is the separation the whole
/// product rests on: the system informs, a person decides.
struct NoticeBanner: View {
    let notice: Notice
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Space.sm) {
            Image(systemName: "person.fill.viewfinder")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.personUnexpected)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 1) {
                Text(notice.title)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.personUnexpected)
                Text(notice.body)
                    .font(TypeScale.caption)
                    .foregroundStyle(Palette.inkMuted)
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
        .padding(.horizontal, Space.md)
        .padding(.vertical, Space.sm)
        .background(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(Palette.personUnexpected.opacity(0.12))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .strokeBorder(Palette.personUnexpected.opacity(0.42), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(notice.title). \(notice.body)")
    }
}
