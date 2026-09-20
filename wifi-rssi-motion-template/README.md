# wifi-rssi-motion-template

Mac-only, self-contained backup to the Pi/CSI presence-detection path. Polls
this laptop's WiFi RSSI via CoreWLAN, computes rolling variance and
frame-to-frame motion energy over a sliding window, and classifies
**no motion / motion** using a threshold calibrated against your
environment — not a fixed dBm number.

**This directory is a working starting point, not a finished feature** --
the core sensing/calibration/UI loop works end to end (see below), but it's
meant to be extended: e.g. wiring its motion events into the agent mesh,
richer visualization, persisting calibration across restarts, multi-room
support. Keep it self-contained (no dependency on `sensor/`, `agents/`,
`app/`, or ANS) unless a change deliberately extends its scope.

## How it works, and what it can't do

RSSI is "how strong does my current WiFi connection feel right now" — a
single number, updated a few times a second. It doesn't come from a beam
pointed at anything; it's a side effect of every radio path between this
laptop and whichever access point it's currently associated with, all of
which your body (mostly water) absorbs and scatters a little just by being
in the room. Movement perturbs those paths more than stillness does, so a
jumpier RSSI signal over the last few seconds usually means something moved.

That means detection is strongest **near the direct radio path between the
laptop and the router** — the closer together they are, the more even small
movements swing the signal, and the more reliably a "still" baseline can be
told apart from a "walking" one. It is not a proximity sensor around the
laptop specifically, and it does not localize where someone is or count
how many people are present — it only reports whether the *whole path* is
calm or disturbed.

**In a venue building, where the router isn't nearby or visible** (e.g. a
distant ceiling AP down a hallway or on another floor), this degrades in
two ways: the baseline signal is weaker and already more variable from wall
attenuation and multipath, so genuine environmental noise is larger relative
to any one person's effect; and someone moving far from both the laptop and
the direct path to the AP may barely perturb the signal at all. It can
still show *something* in a venue, but reliability drops a lot compared to
a small room with the router close by, and it would need recalibrating for
that specific location and AP.

## Setup

    cd wifi-rssi-motion-template
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Calibrate before trusting any threshold

The server (and `calibrate.py`) analyze RSSI over a short, 4-second sliding
window -- fast to react, but any single window is noisy, so calibration
still uses a generous 20-second capture per phase to average that noise out
over many overlapping windows. Captures must run longer than the window or
`calibrate.py` has nothing to average and will refuse to produce a summary.

The easiest way to calibrate is the **Calibrate** button in the running
app (see Run, below) -- it gives you a 5-second grace period to get away
from the laptop, then walks you through a 20s "stand still" phase and a 20s
"walk" phase, and applies the result live, no restart needed. A **Stop**
button appears while it's running if you need to abort and try again. The
CLI below does the same thing manually, useful for scripting or debugging:

    .venv/bin/python3 calibrate.py capture --label still --seconds 20 --out still.json
    # now walk between the laptop and the router
    .venv/bin/python3 calibrate.py capture --label walk --seconds 20 --out walk.json
    .venv/bin/python3 calibrate.py compare still.json walk.json

`compare` prints the raw still/walk distributions (useful for eyeballing that
they actually separate) and, below that, the suggested threshold -- a
dimensionless ratio against the runtime EMA baseline. Paste that ratio
value, not the raw distributions, into `classifier.py` to keep it after
a restart (the in-app button only applies it for the current server
process).

Note the ratio the calibration formula suggests is sensitive to how
vigorously you walk during the "walk" phase -- a brisk walk sets a high bar
that ordinary movement won't clear later, while barely shifting in place
sets a hair-trigger bar. Walk at a normal, everyday pace for the most
useful result, and recalibrate if the first pass feels off.

## Run

    cd wifi-rssi-motion-template
    .venv/bin/python3 server.py

Then open the URL the server prints for the static frontend, e.g.
`http://localhost:8766/index.html`. Opening `static/index.html` directly over
`file://` will not work -- the page can't infer the WebSocket port without a
server origin to derive it from.
