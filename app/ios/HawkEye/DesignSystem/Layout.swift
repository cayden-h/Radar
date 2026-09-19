import SwiftUI

/// Spacing and radii. A 4pt grid, named so nobody types `14` at a call site.
enum Space {
    static let hair: CGFloat = 2
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    static let xxxl: CGFloat = 48

    /// The single horizontal gutter used by every screen.
    static let gutter: CGFloat = 20
}

enum Radius {
    static let sm: CGFloat = 8
    static let md: CGFloat = 14
    static let lg: CGFloat = 20
    static let xl: CGFloat = 28
    /// Rows and buttons that should read as capsule-adjacent without being capsules.
    static let pill: CGFloat = 999
}

/// Minimum tap target. Emergency UI, so nothing is smaller than this.
enum Hit {
    static let min: CGFloat = 52
}
