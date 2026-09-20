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

    .venv/bin/python3 calibrate.py --label still --seconds 10 --out still.json
    # now walk between the laptop and the router
    .venv/bin/python3 calibrate.py --label walk --seconds 10 --out walk.json
    .venv/bin/python3 calibrate.py --compare still.json walk.json

Paste the printed suggested thresholds into `classifier.py`.

## Run

    .venv/bin/python3 server.py

Then open `static/index.html` in a browser.
