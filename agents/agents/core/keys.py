"""Where an agent's private key lives, and why not in the repository.

An agent's signing key *is* its identity on the wire, in the only sense that
matters to a verifier. `master` learns the public half from the agent's
published trust card and will accept a claim from nobody else.

Consequences, and all three are easy to get wrong in a hurry:

- **Never in git.** A committed private key is not an identity, it is a
  liability, and every agent in the mesh would share it. `agents/build/` is
  gitignored for exactly this.
- **Stable across restarts.** A key regenerated on boot invalidates the
  published card, which to any monitor watching is indistinguishable from the
  agent having been replaced. That is `card_drift_watch` firing on us for a
  reason we caused.
- **One per agent.** Five agents sharing a key is one agent wearing five names,
  and it would make the entire verification story theatre: a compromised
  sensing agent could sign as `master`.

Production loads from a secret store. Here it is a file per agent, created on
first use, with an env override so a deployment can inject one instead.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_pem_private_key,
)

logger = logging.getLogger(__name__)

#: Default key directory. Gitignored. One PEM per agent slug.
KEY_ROOT = Path(__file__).resolve().parent.parent.parent / "build" / "keys"

#: Env var holding a PEM directly, for a deployment that injects secrets rather
#: than mounting a volume. Takes precedence over the file.
ENV_TEMPLATE = "HAWKEYE_{slug}_KEY_PEM"


def load_or_create(slug: str, *, root: Path | None = None) -> Ed25519PrivateKey:
    """This agent's signing key, stable across restarts.

    Creating one silently is right for development and wrong for production,
    where a missing key should fail the deploy rather than mint a new identity
    nobody registered. The log line is the seam: when `ans/` has real
    registration, make the create path conditional on an explicit flag.
    """
    injected = os.environ.get(ENV_TEMPLATE.format(slug=slug.upper()))
    if injected:
        key = load_pem_private_key(injected.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{ENV_TEMPLATE.format(slug=slug.upper())} is not an Ed25519 key")
        return key

    directory = root or KEY_ROOT
    path = directory / f"{slug}.pem"
    if path.is_file():
        key = load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{path} is not an Ed25519 private key")
        return key

    directory.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    path.chmod(0o600)
    logger.warning(
        "minted a new signing key for %s at %s. This is a NEW IDENTITY: any card "
        "published under the previous key is now stale and will read as drift. "
        "Rebuild cards before publishing.",
        slug,
        path,
    )
    return key
