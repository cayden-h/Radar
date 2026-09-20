# WiFi RSSI Motion/Presence Detector

Mac-only, self-contained backup to the Pi/CSI presence-detection path. Polls
this laptop's WiFi RSSI via CoreWLAN, computes rolling variance and
frame-to-frame motion energy over a sliding window, and classifies
absent / present-still / active using thresholds calibrated against your
environment — not fixed dBm numbers.

## Setup

    cd wifi-rssi-detector
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## Calibrate before trusting any threshold

Captures must run longer than the 12-second feature window or `calibrate.py`
has nothing to average and will refuse to produce a summary -- use at least
20 seconds.

    .venv/bin/python3 calibrate.py capture --label still --seconds 20 --out still.json
    # now walk between the laptop and the router
    .venv/bin/python3 calibrate.py capture --label walk --seconds 20 --out walk.json
    .venv/bin/python3 calibrate.py compare still.json walk.json

`compare` prints the raw still/walk distributions (useful for eyeballing that
they actually separate) and, below that, the suggested thresholds --
dimensionless ratios against the runtime EMA baseline. Paste those ratio
values, not the raw distributions, into `classifier.py`.

## Run

    cd wifi-rssi-detector
    .venv/bin/python3 server.py

Then open the URL the server prints for the static frontend, e.g.
`http://localhost:8766/index.html`. Opening `static/index.html` directly over
`file://` will not work -- the page can't infer the WebSocket port without a
server origin to derive it from.
