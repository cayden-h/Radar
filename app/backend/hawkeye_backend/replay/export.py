"""The bundle a detective is handed.

A zip, not a JSON blob, because the person opening it may have no tooling and no
Python knowledge beyond running one file. Four members:

  record.json  the full record, canonical JSON
  chain.txt    one readable line per entry, needs nothing but a text editor
  verify.py    recomputes the chain, prints INTACT or names the altered entry
  README.txt   what this proves, and plainly what it does not

The README is load-bearing. There is no transparency-log receipt yet, so this
record is tamper-evident to whoever holds it and to nobody else, and it says so
in the first paragraph rather than in a footnote. An export that overstates what
it proves is worse than no export, because it will be believed.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

from hawkeye_backend.models.incident import ReplayRecord
from hawkeye_backend.replay.chain import canonical

#: Standalone, no imports beyond the standard library, no arguments to get
#: wrong. Reimplements the canonical form rather than importing it, on purpose:
#: a verifier that depends on the code that produced the record verifies
#: nothing. Anyone can read these forty lines and check they match the README.
VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""Recompute the hash chain in record.json. Prints INTACT or names the bad entry.

    python3 verify.py [record.json]

No third-party packages. Python 3.8 or newer.

What a pass means: nobody has edited, reordered, inserted or removed an entry
since the record was sealed. What it does not mean: that the system which wrote
the record wrote it honestly. See README.txt.
"""
import hashlib
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "record.json"
with open(path, "r", encoding="utf-8") as handle:
    record = json.load(handle)

entries = record.get("entries", [])
prev = None
for entry in entries:
    body = {
        "seq": entry["seq"],
        "kind": entry["kind"],
        "summary": entry["summary"],
        "detail": entry.get("detail", {}),
    }
    if entry.get("actor") is not None:
        body["actor"] = entry["actor"]
    blob = json.dumps({"prev": prev, "entry": body}, sort_keys=True, separators=(",", ":"))
    computed = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    if entry.get("prev_hash") != prev:
        print("ALTERED: entry %s does not follow entry %s" % (entry["seq"], entry["seq"] - 1))
        sys.exit(1)
    if computed != entry["entry_hash"]:
        print("ALTERED: entry %s has been changed since it was written" % entry["seq"])
        print("  expected %s" % entry["entry_hash"])
        print("  computed %s" % computed)
        sys.exit(1)
    prev = entry["entry_hash"]

if record.get("root_hash") not in (None, prev):
    print("ALTERED: root hash does not match the final entry")
    sys.exit(1)

print("INTACT: %d entries, chain complete to %s" % (len(entries), prev))
if not record.get("scitt_receipt"):
    print("NOTE: no transparency-log receipt. See README.txt for what that limits.")
sys.exit(0)
'''


def _readme(record: ReplayRecord, exported_at: datetime) -> str:
    sealed = record.sealed_at.isoformat() if record.sealed_at else "NOT SEALED"
    discarded = sum(1 for v in record.verifications if v.decision.value == "DISCARDED")
    return f"""HAWK EYE INCIDENT RECORD
========================

Incident      {record.incident_id}
Address       {record.site_address}
Calling agent {record.caller_ansname}
Sealed        {sealed}
Entries       {len(record.entries)}
Root hash     {record.root_hash}
Algorithm     {record.hash_algorithm}
Exported      {exported_at.isoformat()}


WHAT THIS IS
------------

An append-only record of one emergency incident, written entry by entry as it
happened. Recording opened when a person in the house raised the incident, and
sealed when the 911 call ended. Nothing was written after the seal.

Each entry carries the hash of the entry before it. Changing, reordering,
inserting or removing any entry changes every hash after it, and `verify.py`
detects that.


WHAT IT PROVES
--------------

That this record has not been altered since it was sealed, to anyone holding
this file and running verify.py.


WHAT IT DOES NOT PROVE
----------------------

That the system which wrote it wrote it honestly.

A hash chain held by one party proves internal consistency, not truthfulness.
Proving the record to a third party who does not already hold it requires the
entry to be sealed into an append-only transparency log (SCITT) at the moment it
was written, and that step is NOT implemented. `scitt_receipt` in record.json is
null and must stay null until it is real.

Treat this record as you would a business record produced by the party that
created it: useful, checkable for internal consistency, and not self-proving.


THE VERIFICATION ENTRIES
------------------------

{len(record.verifications)} claims were checked before anything was said to the
911 operator; {discarded} of them were DISCARDED and never spoken.

The discarded ones are kept deliberately and at equal weight. A record that only
retained what was accepted could not show what the system refused to repeat, and
what it refused to repeat is the point.


RUNNING THE CHECK
-----------------

    python3 verify.py

Prints INTACT, or names the first entry that does not check out.


FILES
-----

record.json   the full record, canonical JSON
chain.txt     one line per entry, readable without tooling
verify.py     the checker above
README.txt    this file
"""


def _chain_txt(record: ReplayRecord) -> str:
    lines = [
        f"# Hawk Eye incident {record.incident_id}",
        f"# {record.site_address}",
        f"# root {record.root_hash}",
        "#",
        "# seq  timestamp                        kind         actor                summary",
        "",
    ]
    for entry in record.entries:
        actor = (entry.actor or "-")[:20]
        summary = entry.summary.replace("\n", " ")
        lines.append(
            f"{entry.seq:>5}  {entry.at.isoformat()}  {entry.kind:<12} {actor:<20} {summary}"
        )
        lines.append(f"       hash {entry.entry_hash}")
        lines.append(f"       prev {entry.prev_hash or '(genesis)'}")
        lines.append("")
    return "\n".join(lines)


def build_export(record: ReplayRecord, exported_at: datetime) -> bytes:
    """The zip, in memory. Records are small; a temp file would buy nothing."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        # Canonical, so two exports of the same sealed record are byte-identical
        # and a detective can diff them.
        bundle.writestr("record.json", canonical(record.model_dump(mode="json")))
        bundle.writestr("chain.txt", _chain_txt(record))
        bundle.writestr("verify.py", VERIFY_SCRIPT)
        bundle.writestr("README.txt", _readme(record, exported_at))
    return buffer.getvalue()
