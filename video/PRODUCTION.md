# How the video gets made

`SKIT.md` is what happens on screen. This is where each frame comes from.

Three layers. Every shot in the beat sheet belongs to exactly one of them, and the
rule for which is not aesthetic.

---

## The rule

**Anything that is a claim about what Hawk Eye does gets shot or rendered by the real thing.
Everything else can be generated.**

A judge cannot tell a generated hallway from a real one and does not care.
A judge cares enormously whether the box around the intruder came from our tracker or from a
video model that was told to draw a box.

So the line falls in a specific place, and it is not "real where convenient."

---

## Layer A - the plate

Shot on the day, by us, in a real house.

| Beat | Shot |
|---|---|
| 1 | Door opening, interior wide |
| 2 | Servo macro, shield rotating off the lens |
| 4, 6, 10 | Camera-feed plates: the intruder in the living room, searching, taking things |
| 7 | Camera-feed plate: the hallway, second position of the same camera |
| 5 | Closet, resident, the watch, the hold |
| 9 | Closet, the phone, the transcript, typing |
| 12 | Shutter macro closing |

**Shoot the camera-feed beats on the actual Logitech, through `hawkeye_vision`.**
Not on a phone, not on a mirrorless. The feed has to look like the sensor it claims to be,
and the cheapest way to guarantee that is for it to be the sensor it claims to be.

```sh
cd vision
python3 -m hawkeye_vision --record ../video/plates/living-room
```

That writes clean, unoverlaid, hash-sealed segments. Those are the plates.
They are also, not incidentally, real evidence files produced by the real recorder, which is
worth saying out loud in the pitch.

---

## Layer B - the burn

The plates go back through the product to get their overlays.

This is the part that makes the film honest. The boxes in the video are the boxes YOLO11m and
BoT-SORT actually put on that footage, rendered by `hawkeye_vision/overlay.py`, offline, on the
MacBook, with no Pi and no network in the loop.

```sh
cd vision
python3 -m hawkeye_vision \
    --fixture ../video/plates/living-room/segment-000.mp4 \
    --render  ../video/burns/living-room.mp4 \
    --headless
```

`--render` writes one mp4 with the overlay burned into every frame. It is deliberately a
different file from `--record`: the record is evidence and has nothing drawn on it, the print is
for the film. Both can run at once and they will not agree byte for byte, on purpose.

**What the burn gives us that a motion graphic cannot:**

- The box tracks because the tracker tracked it, including wherever it wobbles or drops. Leave
  the wobble in. A box that never flickers is a box nobody believes.
- ReID carries the same `track_id` across the living room and the hallway plates, which is what
  makes the beat-7 handoff a real claim instead of a title card.
- The lighting state and the people count in the status line are measured, so the numbers in the
  film match the numbers in the tests.

**What the burn does not give us:** the film-grade label copy from the beat sheet.
`overlay.py` draws a debug readout - `id 3  0.87`, `day  luma 142.3  people 1` - because that is
what it is for. The skit wants `unauthorized person · living room · dark jacket, hood up`.

Two ways to close that, and the second is better:

1. Composite the copy in the edit, over the burn, matched to the box position by hand.
2. Give `overlay.py` a presentation mode that draws the label from a track's description field.
   That is a small change, it puts the film's copy inside the tested code, and it is the same
   overlay the iOS app will eventually draw from `vision.tracks[]`.

Do 2 if there is time before the shoot. Do 1 if there is not.

---

## Layer C - generation

Higgsfield, for everything we cannot stage and that carries no claim.

| Beat | Why it is generated |
|---|---|
| 8, 11 | Dispatch centre. We are not getting into a PSAP. |
| 12 | Exterior: headlights across the house, officers approaching, the arrest. |
| - | Establishing exterior of the house at night, if the real one does not read. |
| - | Texture and transitions: grain, gate weave, the light change on the shutter open. |

**Generate faces only in profile, from behind, or out of focus.** A generated operator's face in
full frame is the single most likely thing to read as AI slop and it costs nothing to avoid.

### The hard constraint on generation

**No generated shot may contain readable text.** Not a UI, not a badge, not a screen, not a
street sign.

Video models mangle text, and in this film every piece of readable text is a factual claim about
what our system produced. A generated dispatch screen with plausible-looking garbage on it is
worse than no screen at all, because a judge who pauses will find it.

Where a generated shot needs a screen in it, either shoot the screen as a plate and composite it
in, or frame so the screen is off-axis and illegible.

### What must never be generated

- The shutter opening or closing. It is the hero shot and it is a physical claim.
- Any camera feed with a box on it.
- The watch, the hold, the phone transcript.
- The agent mesh graphic.

If we generate any of those, the video stops being a demo and becomes a concept trailer, and the
GoDaddy track is judged on the first thing.

---

## The mesh graphic - beat 3

**Not Higgsfield. HyperFrames.**

It is nine lines of text, seven ANSNames, and a green check per hop. It is the single most
text-dense shot in the film and the one where a wrong character is a wrong claim.

HyperFrames gives deterministic HTML/GSAP with real strings, rendered at 1080p, seekable, and
re-renderable in thirty seconds when a domain name changes. A video model gives
`presence.howkeye.ai` and nobody notices until the judge does.

Same argument for any lower third or end card.

---

## Order of operations

1. **Shoot the shutter macro.** First, while the light is controlled and everyone is fresh.
2. **Shoot the camera-feed plates** through `hawkeye_vision --record`, both room positions, in
   one session with the same wardrobe and the same camera height.
3. **Burn the plates** with `--render`. Watch them. If a box drops somewhere ugly, reshoot the
   plate rather than fixing it in the edit.
4. **Shoot the closet beats.** These are the only performance-dependent shots; budget takes.
5. **Build the mesh graphic** in HyperFrames against the burned plates, so the timing matches.
6. **Generate layer C** last, once the cut length of each hole is known. Generating before the
   assembly means generating the wrong durations.
7. **Re-perform the 911 call** and grade it. See the sourcing note in `SKIT.md`.
8. **Assemble, grade, mix.**

Step 3 gates step 6. Do not start generating until the burns are watchable, because the burns
determine how much screen time the feed can hold and therefore how much generated material the
film actually needs.

---

## What already exists

- `vision/hawkeye_vision/` - capture, lighting, YOLO11m + BoT-SORT with ReID, overlay, recorder.
- `vision/hawkeye_vision/render.py` and `--render` - the burn path. Added for this. 5 tests.
- `vision/yolo11m.pt` - the weights.
- `vision/hawkeye_vision/botsort_reid.yaml` - the tracker config that carries ids across cuts.
- `video/audio/` - the reference call and its transcript, for the re-performance.

`cd vision && python3 -m pytest -q` is 109 passing.
