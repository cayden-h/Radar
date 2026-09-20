"""The console's in-browser verifier must agree with the Python that wrote the record.

There are three implementations of one canonical form: `replay/chain.py`, the
`verify.py` shipped in the export, and the JavaScript in the replay console. The
first two are held together by `test_the_shipped_verifier_agrees_with_the_server`.
This holds the third.

It is worth a node dependency because the disagreement it catches is invisible
and looks exactly like tampering. `JSON.stringify` writes the float 1.0 as `1`
where Python writes `1.0`, and leaves non-ASCII as itself where Python's default
`ensure_ascii` writes `\\uXXXX`. Either one changes the hash of an entry nobody
touched, and the console would then accuse an intact record of being altered,
which is the single most damaging thing this page could do.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hawkeye_backend.replay.chain import canonical, entry_hash

CONSOLE_JS = Path(__file__).resolve().parents[2] / "web" / "replay" / "console.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not CONSOLE_JS.is_file(),
    reason="needs node and app/web/replay/console.js",
)

# Every value that has ever made two JSON serializers disagree, in one object.
AWKWARD: dict[str, object] = {
    "zebra": 1,
    "alpha": "sorted after zebra by insertion, before it when canonical",
    "integral_float": 1.0,
    "negative_zero_ish": -0.0,
    "tiny": 1e-07,
    "big": 12345678901234.0,
    "rounded": 0.30000000000000004,
    "unicode": "café — naïve 中文",
    "astral": "\U0001f525 smoke",
    "control": 'line\nbreak\ttab "quote" back\\slash',
    "empty_string": "",
    "null": None,
    "true": True,
    "false": False,
    "nested": {"b": [1.0, 2.5, None, {"z": 0.0, "a": "x"}], "a": {}},
    "empty_list": [],
}


def _node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _load_js() -> str:
    """Evaluate console.js under node and expose its canonicalizer.

    The file is an IIFE that touches no DOM at definition time, so node can
    evaluate it without a browser.
    """
    return (
        "const fs = require('fs');"
        f"const src = fs.readFileSync({json.dumps(str(CONSOLE_JS))}, 'utf8');"
        "const HawkEye = eval(src + '; HawkEye');"
        "const { canonical, parseKeepingNumbers } = HawkEye._canonical;"
    )


def test_the_console_canonicalizes_exactly_as_python_does() -> None:
    """Same object, same bytes, through both implementations."""
    served = json.dumps(AWKWARD)  # what FastAPI would put on the wire
    script = (
        _load_js()
        + f"const served = {json.dumps(served)};"
        + "process.stdout.write(canonical(parseKeepingNumbers(served)));"
    )
    assert _node(script) == canonical(AWKWARD)


def test_the_console_reaches_the_same_entry_hash() -> None:
    """The form that actually matters: `{prev, entry}`, hashed."""
    body: dict[str, object] = {
        "seq": 7,
        "kind": "frame",
        "actor": "sensor.hawkeye.invalid",
        "summary": "presence change: 3 in [living_room], 1 still",
        "detail": AWKWARD,
    }
    prev = "a" * 64
    served = json.dumps({"prev": prev, "entry": body})
    script = (
        _load_js()
        + f"const served = {json.dumps(served)};"
        + "const crypto = require('crypto');"
        + "const text = canonical(parseKeepingNumbers(served));"
        + "process.stdout.write(crypto.createHash('sha256').update(text, 'utf8').digest('hex'));"
    )
    assert _node(script) == entry_hash(body, prev)


def test_the_console_preserves_number_literals_rather_than_reparsing() -> None:
    """The specific failure this file exists for.

    `1.0` must survive as `1.0`. A verifier that reparses it into a JavaScript
    number writes `1` and declares an untouched record altered.
    """
    script = (
        _load_js()
        + "process.stdout.write(canonical(parseKeepingNumbers('{\"a\": 1.0, \"b\": 2e3, \"c\": -0.0}')));"
    )
    assert _node(script) == '{"a":1.0,"b":2e3,"c":-0.0}'
