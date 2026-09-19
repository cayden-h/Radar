import SwiftUI

/// Motion curves. Named, so the whole app moves at the same speed.
///
/// The constraint: nothing in this app bounces. A bouncy spring on a screen
/// that is reporting an unresponsive person reads as playful, which is wrong.
enum Motion {

    /// Default state change. Rows appearing, screens swapping.
    static let standard = Animation.spring(response: 0.42, dampingFraction: 0.92)

    /// Fast feedback on a direct touch.
    static let snappy = Animation.spring(response: 0.26, dampingFraction: 0.9)

    /// Slow, continuous, never-ending. Breathing rings and scan sweeps.
    static let ambient = Animation.easeInOut(duration: 3.2).repeatForever(autoreverses: true)

    /// The urgent pulse behind an unresponsive presence. Faster than ambient
    /// so it is legible as alarm rather than as ornament.
    static let urgent = Animation.easeInOut(duration: 0.9).repeatForever(autoreverses: true)

    /// Transcript lines and guidance cards arriving.
    static let arrive = Animation.spring(response: 0.5, dampingFraction: 0.86)
}
