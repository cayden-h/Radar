"""Build the two cards for every agent, as byte-stable artifacts on disk.

`ans/CARD.md` measure 2: **the card is a build artifact, not a response.**
`card_drift_watch` hashes the signed card and compares it against the previous
run, and drift without a re-registration event is a finding. A card assembled
per request drifts on its own - map ordering, a timestamp, a counter - and hands
a monitor a finding we earned by accident.

    python scripts/build_cards.py            # write build/cards/<slug>/
    python scripts/build_cards.py --check    # fail if anything drifted

`--check` is the one to put in CI. It rebuilds in memory and compares
fingerprints against what is on disk, so a card edited by hand or a code change
that alters a card without a version bump both fail loudly. Measure 3 says stop
editing cards by hand after Saturday: late cosmetic edits to a description field
are indistinguishable from an attack to any monitor watching, and this is what
makes that rule enforceable rather than remembered.

**Each agent signs its own card with its own key**, loaded from
`agents.core.keys` - the same key it signs claims with at runtime. That is not a
detail: the card exists so `master` can learn the public half and accept claims
from nobody else, so a card published under a different key than the agent signs
with would make every claim it ever sends fail verification.

Five agents, five keys. Sharing one would be one agent wearing five names, and a
compromised sensing agent could then sign as `master`.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from hawkeye_backend.verification.b64 import key_thumbprint
from hawkeye_backend.verification.card import commit_address

from agents.core import cards
from agents.core.identity import ROSTER
from agents.core.keys import load_or_create

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "cards"

#: The address the installation is anchored to. Fictional, and it stays that
#: way: a simulated 911 call must never carry a real residential address.
#:
#: Only its **commitment** reaches the card. The card is world-readable, and
#: publishing the street address of someone who cannot get off the floor would
#: be a worse outcome than the attack this binding defends against.
DEMO_ADDRESS = "1 Fictional Way, Blacksburg VA 24060"


def build(*, write: bool) -> dict[str, str]:
    """Build every card, each under its own agent's key.

    Returns slug -> A2A card fingerprint.
    """
    commitment, salt = commit_address(DEMO_ADDRESS)
    # TODO(ans): the salt and the plaintext are sealed at registration and never
    # served. Right now the salt is discarded at the end of this function, which
    # means `caller` cannot yet recompute the commitment over the address it is
    # about to speak. Persisting it into a sealed store is part of registration,
    # not part of card generation, and doing it here would put the secret in the
    # same place as the public artifact.
    del salt

    fingerprints: dict[str, str] = {}
    for agent in ROSTER:
        # The agent's own key, the same one it will sign claims with. Created on
        # first use and stable thereafter; a key that changed per build would
        # invalidate the published card every time, which to any monitor is
        # indistinguishable from the agent having been replaced.
        key = load_or_create(agent.slug)
        a2a = cards.build_a2a_card(agent, address_commitment=commitment)
        signed_a2a = cards.sign(a2a, key, agent)
        trust = cards.build_trust_card(
            agent,
            public_key_b64=cards.public_key_b64(key),
            kid=key_thumbprint(key.public_key()),
            # Deterministic from the ANSName rather than random, so rebuilding
            # does not produce a new agentId and therefore fake drift. A real
            # registration assigns this; until then a stable value is the only
            # one that does not lie about having changed.
            agent_id=str(uuid.uuid5(uuid.NAMESPACE_URL, agent.ansname)),
            x5c=None,
            transparency_receipt=None,
        )
        signed_trust = cards.sign(trust, key, agent)

        fingerprints[agent.slug] = cards.fingerprint(signed_a2a)
        if write:
            directory = OUT / agent.slug
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "agent-card.json").write_bytes(cards.serialize(signed_a2a))
            (directory / "trust-card.json").write_bytes(cards.serialize(signed_trust))
    return fingerprints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare against disk; do not write.")
    args = parser.parse_args(argv)

    if args.check:
        # `--check` compares the *unsigned* content fingerprint. Signature
        # bytes changing is a re-signing event and card content changing is
        # drift; conflating them would make every rebuild look like tampering.
        failures = []
        for agent in ROSTER:
            path = OUT / agent.slug / "agent-card.json"
            if not path.is_file():
                failures.append(f"{agent.slug}: no card on disk")
                continue
            import json

            on_disk = json.loads(path.read_bytes())
            rebuilt = cards.build_a2a_card(
                agent, address_commitment=commit_address(DEMO_ADDRESS)[0]
            )
            on_disk.pop("signatures", None)
            # The address commitment is salted, so it differs every build by
            # design - two installations at the same address must not produce
            # linkable cards. Excluded from the comparison for that reason.
            for card in (on_disk, rebuilt):
                card.get("x-hawkeye", {}).pop("dispatchAddressCommitment", None)
            if cards.fingerprint(on_disk) != cards.fingerprint(rebuilt):
                failures.append(f"{agent.slug}: card on disk differs from the code that built it")
        if failures:
            print("card drift:", *failures, sep="\n  ")
            return 1
        print(f"{len(ROSTER)} cards match the code that built them")
        return 0

    fingerprints = build(write=True)
    for slug, fingerprint in sorted(fingerprints.items()):
        print(f"{slug:<12} {fingerprint}")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
