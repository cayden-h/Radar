import SwiftUI

/// Hawk Eye's colour palette. Dark-first and deliberately narrow.
///
/// The rule the palette enforces: colour means state, never decoration.
/// Anything that is not carrying state is a grey.
enum Palette {

    // MARK: Ground

    /// The base ground. Near-black with a trace of purple, echoing the
    /// mascot, so it does not read as OLED void.
    static let ground = Color(hex: 0x090810)
    /// One step up from ground. Cards, sheets, the floorplan well.
    static let surface = Color(hex: 0x100D19)
    /// Two steps up. Rows, fields, pressed states.
    static let surfaceRaised = Color(hex: 0x1A1522)
    /// Hairlines. Always this, never an opacity guess.
    static let hairline = Color(hex: 0x282030)

    // MARK: Ground, as a gradient

    /// The dusk-toned three-stop gradient `AmbientBackground` paints instead
    /// of a flat `ground` fill. Every ink/state colour above still reads at
    /// the same contrast it was tuned against against the darkest stop —
    /// the gradient only has to be visible, not loud.
    static let duskTop = Color(hex: 0x3B2A68)
    static let duskMid = Color(hex: 0x201638)
    static let duskBase = Color(hex: 0x0B0813)

    static var groundGradient: LinearGradient {
        LinearGradient(
            colors: [duskTop, duskMid, duskBase],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    /// Two soft, blurred fields of colour behind the dot grid — the thing
    /// `AmbientBackground`'s own doc comment used to argue against, revised
    /// because a gradient this dark against near-black cards was reading as
    /// no change at all. Kept to two, kept low-opacity, and kept off the
    /// state palette (`auraGlow` is decoration only, never a status).
    static let auraGlow = Color(hex: 0x9B6BFF)
    static let auraGlowSecondary = Color(hex: 0xFF8FC0)

    // MARK: Glass

    /// The border every frosted panel uses in place of `hairline` — see
    /// `View.glassPanel` in `Components.swift`.
    static let glassBorder = Color.white.opacity(0.12)
    /// A light, neutral grey wash over every frosted panel — deliberately
    /// *not* tinted purple, so glass reads as glass and the brand colour
    /// stays reserved for accents, state and the mascot.
    static let glassTint = Color.white.opacity(0.09)

    // MARK: Ink

    /// Primary text.
    static let ink = Color(hex: 0xF2F5F9)
    /// Secondary text. Labels, timestamps, supporting copy.
    static let inkMuted = Color(hex: 0x8D97A6)
    /// Tertiary text. Only for things the eye should skip.
    static let inkFaint = Color(hex: 0x525C6B)

    // MARK: State

    /// The system is healthy and watching. Used sparingly.
    /// Purple-pink, matching the mascot. Deliberately warmer/pinker than
    /// `collapse`/`faint` below (also a purple) so the two never read as the
    /// same signal — one is brand chrome, the other is a person down.
    static let calm = Color(hex: 0xC97BFF)
    /// A confirmed person, moving and breathing. Nothing is wrong.
    static let personMoving = Color(hex: 0x5BA8FF)
    /// A person whose breathing signature we had and no longer have. The
    /// loudest state in the product, and the only name for this colour.
    static let personUnresponsive = Color(hex: 0xFF3B4E)
    /// A perturbation with no respiration signature. Not a person.
    static let unconfirmed = Color(hex: 0x6E7889)

    /// A confirmed person the system did not expect to be in the building.
    ///
    /// Deliberately the same deep red as the Burglary button: the colour the
    /// roster turns and the button the resident presses are the same fact, and
    /// pairing them means the screen does not have to explain the link.
    ///
    /// `expected` is an orthogonal axis to `PresenceState`, not a fourth state,
    /// so this tint replaces the state tint rather than adding a case to it.
    static let personUnexpected = Color(hex: 0x9A1B1B)

    /// A confirmed person who is still and breathing, on the map/roster only.
    /// Kept separate from `Palette.personUnresponsive`, which is the
    /// unrelated danger/refusal red used elsewhere in the app.
    static let collapse = Color(hex: 0x8B7CFF)

    // MARK: Incidents

    static let burglary = Color(hex: 0x9A1B1B)
    static let fire = Color(hex: 0xFF7A3D)

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
