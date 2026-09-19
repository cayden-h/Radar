import SwiftUI

/// The type scale. Six sizes, no improvising a seventh at the call site.
///
/// Rounded for anything a frightened person reads quickly; monospaced digits
/// anywhere a number ticks, so the layout does not jitter.
enum TypeScale {

    /// The wordmark and nothing else.
    static let wordmark = Font.system(size: 30, weight: .semibold, design: .rounded)

    /// Screen titles.
    static let title = Font.system(size: 26, weight: .semibold, design: .rounded)

    /// Section headings and the incident banner.
    static let heading = Font.system(size: 19, weight: .semibold, design: .rounded)

    /// Body copy. Transcript lines, guidance cards.
    static let body = Font.system(size: 16, weight: .regular)

    /// Emphasised body. Guidance instructions the user must act on.
    static let bodyStrong = Font.system(size: 16, weight: .semibold)

    /// Row subtitles, field labels.
    static let caption = Font.system(size: 13, weight: .medium)

    /// All-caps eyebrow labels. Always paired with `.tracking(1.4)`.
    static let eyebrow = Font.system(size: 11, weight: .semibold)

    /// Any ticking number: call duration, still-down seconds, signal strength.
    static let numeric = Font.system(size: 13, weight: .medium, design: .monospaced)
}

extension View {
    /// An all-caps, tracked label. Used for every eyebrow in the app so the
    /// tracking value lives in exactly one place.
    func eyebrowStyle(_ color: Color = Palette.inkFaint) -> some View {
        self.font(TypeScale.eyebrow)
            .tracking(1.4)
            .textCase(.uppercase)
            .foregroundStyle(color)
    }
}
