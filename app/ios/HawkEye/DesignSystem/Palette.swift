import SwiftUI

/// Hawk Eye's colour palette. Dark-first and deliberately narrow.
///
/// The rule the palette enforces: colour means state, never decoration.
/// Anything that is not carrying state is a grey.
enum Palette {

    // MARK: Ground

    /// The base ground. Near-black with a trace of blue so it does not read as OLED void.
    static let ground = Color(hex: 0x07090C)
    /// One step up from ground. Cards, sheets, the floorplan well.
    static let surface = Color(hex: 0x0E1218)
    /// Two steps up. Rows, fields, pressed states.
    static let surfaceRaised = Color(hex: 0x161B23)
    /// Hairlines. Always this, never an opacity guess.
    static let hairline = Color(hex: 0x232A35)

    // MARK: Ink

    /// Primary text.
    static let ink = Color(hex: 0xF2F5F9)
    /// Secondary text. Labels, timestamps, supporting copy.
    static let inkMuted = Color(hex: 0x8D97A6)
    /// Tertiary text. Only for things the eye should skip.
    static let inkFaint = Color(hex: 0x525C6B)

    // MARK: State

    /// The system is healthy and watching. Used sparingly.
    static let calm = Color(hex: 0x4FD1C5)
    /// A confirmed person, moving and breathing. Nothing is wrong.
    static let personMoving = Color(hex: 0x5BA8FF)
    /// A person who is still but breathing. The loudest state in the product.
    static let personUnresponsive = Color(hex: 0xFF3B4E)
    /// A perturbation with no respiration signature. Not a person.
    static let unconfirmed = Color(hex: 0x6E7889)

    /// A confirmed person the system did not expect to be in the building.
    ///
    /// Deliberately the same violet as the Burglary button: the colour the
    /// roster turns and the button the resident presses are the same fact, and
    /// pairing them means the screen does not have to explain the link.
    ///
    /// `expected` is an orthogonal axis to `PresenceState`, not a fourth state,
    /// so this tint replaces the state tint rather than adding a case to it.
    static let personUnexpected = Color(hex: 0x8B7CFF)

    // MARK: Incidents

    static let burglary = Color(hex: 0x8B7CFF)
    static let fire = Color(hex: 0xFF7A3D)
    static let faint = Color(hex: 0xFF3B4E)

    /// Active call state.
    static let live = Color(hex: 0xFF3B4E)
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}
