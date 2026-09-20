import SwiftUI

/// The detector's boxes, drawn by the app and tappable.
///
/// ## Why the app draws these rather than the hub
///
/// The hub already burns boxes into the MJPEG for the browser and the watch
/// (`app/backend/hawkeye_backend/edge/annotate.py`), and that stays exactly as
/// it is. The phone is the one surface where a box is a *control* rather than a
/// picture: you point at a person and say who they are. A box made of pixels
/// cannot be tapped, so on this surface the phone takes the raw frame and draws
/// its own.
///
/// It also gets the app a box that is styled like the rest of the app rather
/// than like `cv2.putText`, and a name that renders in a real typeface.
///
/// ## What a box may and may not say
///
/// **A green box is not recognition.** Nothing in Hawk Eye identifies anybody:
/// the name on a box is what a resident typed after looking at the picture, and
/// the sheet says so out loud rather than leaving it to be inferred. See
/// `app/backend/hawkeye_backend/edge/vouch.py`.
///
/// A box whose vouch has lost its track is drawn dashed and dimmed, because a
/// vouch inside its grace window and a vouch on somebody in frame are different
/// statements about the room and must not look the same.
struct TrackOverlay: View {

    let snapshot: TracksSnapshot

    /// The rect the *image* occupies, which is not the view's bounds: the panel
    /// is 4:3, the camera is 16:9, and `.fit` letterboxes. See
    /// `TrackBox.fittedRect(for:in:)`.
    let imageRect: CGRect

    let onTap: (TrackBox) -> Void

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach(snapshot.tracks) { track in
                box(for: track)
            }
        }
        // The overlay must never eat a tap that did not land on a box, or the
        // camera panel stops being scrollable content and becomes a wall.
        .allowsHitTesting(true)
    }

    @ViewBuilder
    private func box(for track: TrackBox) -> some View {
        let rect = track.rect(in: imageRect)
        let vouch = snapshot.vouch(for: track.trackID)

        RoundedRectangle(cornerRadius: 6, style: .continuous)
            .strokeBorder(
                colour(for: vouch),
                style: StrokeStyle(
                    lineWidth: 2,
                    dash: (vouch?.held == false) ? [5, 4] : []
                )
            )
            .frame(width: rect.width, height: rect.height)
            .overlay(alignment: .bottomLeading) {
                label(for: vouch)
                    .offset(y: 20)
            }
            .contentShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .onTapGesture { onTap(track) }
            .position(x: rect.midX, y: rect.midY)
            // Boxes arrive a few times a second and jump between measurements.
            // Animating the position turns that into a person walking rather
            // than a rectangle teleporting, which is the difference between
            // looking measured and looking broken.
            .animation(Motion.snappy, value: rect)
            .animation(Motion.snappy, value: vouch)
    }

    private func colour(for vouch: PersonVouch?) -> Color {
        guard let vouch else { return Palette.personUnexpected }
        return vouch.held ? Palette.calm : Palette.unconfirmed
    }

    @ViewBuilder
    private func label(for vouch: PersonVouch?) -> some View {
        Text(text(for: vouch))
            .font(.system(size: 11, weight: .bold, design: .rounded))
            .foregroundStyle(Palette.ink)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .frame(height: 20)
            .background(Capsule().fill(colour(for: vouch).opacity(0.9)))
            .fixedSize()
    }

    private func text(for vouch: PersonVouch?) -> String {
        guard let vouch else { return "Tap to name" }
        // Said on the box itself rather than only in the sheet. Somebody
        // glancing at this screen must not read a greyed name as "the camera
        // lost them" when what it means is "they left frame and this lapses".
        return vouch.held ? vouch.name : "\(vouch.name) · left frame"
    }
}

// MARK: - Naming

/// The sheet that opens when a box is tapped.
///
/// Deliberately small: a text field, one action, and one sentence saying what
/// this is and is not. It is reached by pointing at a person on a live feed, so
/// the resident already knows who they mean; the job here is to take a name and
/// get out of the way.
struct VouchSheet: View {

    let trackID: Int
    let existing: PersonVouch?
    let onVouch: (String) -> Void
    let onRevoke: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String = ""
    @FocusState private var focused: Bool

    private var trimmed: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: Space.md) {
                TextField("Their name", text: $name)
                    .textFieldStyle(.plain)
                    .font(.system(size: 22, weight: .semibold, design: .rounded))
                    .foregroundStyle(Palette.ink)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled()
                    .submitLabel(.done)
                    .focused($focused)
                    .onSubmit(vouch)

                // The honesty rule, on the screen where the claim is made
                // rather than only in a doc. A resident who types a name here
                // must not come away believing the house now recognises anyone.
                Text(
                    "This only applies while they are on camera, and it is not recognition - "
                    + "Hawk Eye cannot identify anyone. It stops this person being counted as "
                    + "unaccounted for, and it never places a call."
                )
                .font(.system(size: 13))
                .foregroundStyle(Palette.inkMuted)

                Spacer()

                if existing != nil {
                    Button(role: .destructive) {
                        onRevoke()
                        dismiss()
                    } label: {
                        Text("Remove this name")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }

                Button(action: vouch) {
                    Text(existing == nil ? "Vouch for them" : "Update")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(trimmed.isEmpty)
            }
            .padding(Space.lg)
            .background(Palette.ground)
            .navigationTitle(existing == nil ? "Who is this?" : "Change name")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium])
        .onAppear {
            name = existing?.name ?? ""
            focused = true
        }
    }

    private func vouch() {
        guard !trimmed.isEmpty else { return }
        onVouch(trimmed)
        dismiss()
    }
}
