# agents/

**Pivot note, 2026-09-19.** Seven agents now, not five. `people` is `presence`; `shutter` and `vision` are new.
`shutter` is written and tested; `vision` is not yet.
Run commands below gain `python -m agents shutter --port 8106` and `python -m agents vision --port 8107`, and `HAWKEYE_PEERS` must list them.
See `docs/PIVOT.md` and `agents/CLAUDE.md`.

The five ANS-registered agents behind Hawk Eye.

`CLAUDE.md` in this directory is the contract and the reasoning.
`TODO.md` is the work queue: what is unfinished, in dependency order.
This file is how to run them.

## Layout

One subpackage per agent, named exactly as the docs name it, so `agents/people`
in the prose is `agents.people` in the code.

| Path | What it is |
|---|---|
| `agents/core/` | Identity, cards, keys, signing, the transport, discovery, the ports, the signal helpers |
| `agents/people/` | Presence, personhood, respiration, location, responsiveness. The only CSI consumer |
| `agents/intruder/` | Roster plus device association over the personhood verdict |
| `agents/master/` | The trust gate, the classifier, the incident, the local gas sensor |
| `agents/shutter/` | The grant, the eight refusals, and the one GPIO pin behind a `VerifiedGrant` |
| `agents/caller/` | The 911 phone call, the conference bridge, and the resident's guidance |
| `agents/replay/` | The hash-chained incident record |
| `scripts/build_cards.py` | Builds both cards per agent as byte-stable artifacts |
| `tests/` | The suite. Every "must not claim" line has a test |
| `TODO.md` | What is left, what it blocks, and what blocks it |

## Install

`hawkeye-backend` is a path dependency, not a published one. It carries the
verification package and the shared models that enforce the honesty rule, and
`agents/CLAUDE.md` is explicit that there must not be a second copy of either.

```sh
pip install -e ../app/backend
pip install -e .
```

## Run one

```sh
python -m agents --list
python -m agents people --port 8001
python -m agents shutter --port 8106
```

Each agent serves the same five surfaces:

```
/.well-known/agent-card.json      the A2A card, bytes from disk
/.well-known/agent.json           the same bytes, the alias the spec allows
/.well-known/ans/trust-card.json  the ANS card, bytes from disk
/healthz                          liveness, and honest about tick failures
/v1/observation                   this agent's latest observation
/v1/identity                      what the agent believes it is
```

`/v1/observation` is a read-only convenience for the app and for a judge poking
at a running agent. **It is not the inter-agent channel.** See the wire note
below.

## Cards

Cards are build artifacts, not responses. `card_drift_watch` hashes the signed
card and compares it against the previous run, so a card assembled per request
drifts on its own and hands a monitor a finding we earned by accident.

```sh
python scripts/build_cards.py           # write build/cards/<slug>/
python scripts/build_cards.py --check   # fail if anything drifted
```

An agent with no card on disk serves 503 for the card paths rather than
assembling one. That is deliberate.

## Test

```sh
python -m pytest -q
```

The suite takes about two minutes, almost all of it in `test_people.py`: the
rolling baseline needs 120 simulated seconds before it will answer, and the
tests run that rather than reaching in and faking it.

## The wire

**Pull-only A2A JSON-RPC with a server-issued challenge.** `master` asks, sensing
agents answer, nothing is pushed. Full reasoning in `CLAUDE.md`; the short
version is that pull lets master control the nonce, so a claim is bound to a
question we asked rather than to a moment the producer chose.

Run the mesh by pointing each agent at its peers:

```sh
python -m agents people --port 8101
HAWKEYE_PEERS=people=http://127.0.0.1:8101 python -m agents master --port 8100
```

`HAWKEYE_PEERS` is a comma-separated `slug=url` list, and setting it is what
turns the wire on. With it, master fetches each peer's trust card, builds its
trust store from the published keys, issues a fresh challenge per fetch, and
verifies every claim before anything reaches its gate. Without it, `LocalMesh`
stands in and **verifies nothing** - which the whole stack reports honestly:
`envelope_verified: false` on every claim, and `caller` refuses to speak.

Keys live in `build/keys/<slug>.pem`, created on first use and gitignored. The
card builder signs each agent's card with that same key, because the card exists
so master can learn the public half; a card published under a different key
would make every claim that agent sends fail verification.

`tests/test_wire.py` is the file to read. It stands up `people` as a real ASGI
app, has `master` fetch over A2A, and proves both halves: a claim crosses and
verifies, and a claim signed by the wrong key, from an unregistered agent, from
a lookalike ANSName, or replayed, is discarded with a reason.

**Not implemented, on purpose:** MCP alongside A2A, and mTLS. MCP is a second
adapter over the same handlers and buys presentation rather than capability.
mTLS is the second layer: it proves the connection, where JWS proves the claim,
and our threat model is a compromised agent whose connection is perfectly valid.
