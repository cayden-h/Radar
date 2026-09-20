# Deploying the agents

**The seven agents are live.** `curl https://master.batradar.club/.well-known/agent-card.json` works from anywhere, which is the hard ANS track requirement (`TASKS.md` T11).

Stood up 2026-09-20.

## What is running where

One Vultr instance, `hawkeye`, Ubuntu 24.04, 1 vCPU / 2GB, Newark.

| | |
|---|---|
| IP | `66.135.27.67` |
| SSH | `ssh -i ~/.ssh/larp_vultr root@66.135.27.67` |
| Vultr instance id | `e43a6151-b604-4606-84cd-ebd72341e529` |
| Source | `/opt/hawkeye-src/{agents,backend,vision}`, rsynced from this repo |
| Interpreter | `/opt/hawkeye-venv`, Python 3.13 from deadsnakes |
| Units | `hawkeye-agent@<slug>.service`, one per agent |
| Ports | `/etc/hawkeye/<slug>.env` pins `HAWKEYE_PORT`, 8101 through 8107 in roster order |
| Shared env | `/etc/hawkeye/agents.env`, which is where `HAWKEYE_PEERS` lives |
| Reverse proxy | Caddy, `/etc/caddy/Caddyfile`, automatic Let's Encrypt for all seven hostnames |

**One process per agent, not one process with seven agents in it.** They are seven independently registered identities on seven hostnames, and a single origin serving all of them would have one TLS identity and nothing to verify against anything else.

## Redeploy

```sh
rsync -a --delete \
  --exclude .venv --exclude .git --exclude __pycache__ --exclude '*.pyc' \
  --exclude .pytest_cache --exclude .ruff_cache --exclude '*.pt' --exclude .ans \
  -e "ssh -i ~/.ssh/larp_vultr" \
  agents app/backend vision root@66.135.27.67:/opt/hawkeye-src/

ssh -i ~/.ssh/larp_vultr root@66.135.27.67 \
  'for s in presence intruder master caller replay shutter vision; do
     systemctl restart hawkeye-agent@$s; sleep 6; done'
```

**Restart them one at a time, with a pause.** Each agent builds its trust store at startup by fetching every peer's published trust card, so restarting all seven at once means each one discovers nothing and comes up holding an empty store. Six of seven peers is the healthy number; the seventh is itself.

```sh
ssh ... 'journalctl -u hawkeye-agent@master --since "3 min ago" | grep "trust store"'
# trust store holds 6 of 7 peers
```

Rebuild the cards before shipping them, or the box serves cards that no longer match the code:

```sh
cd agents && PYTHONPATH=. ../app/backend/.venv/bin/python scripts/build_cards.py
```

## The ANS ACME challenge is served over plain HTTP, deliberately

The registration authority proves we control a host before it hands over the `_ans` and `_ans-badge` records. It validates over **plain HTTP and does not follow redirects**: against Caddy's automatic HTTPS redirect it reported `308 PERMANENT_REDIRECT` and called the challenge unverified.

So the Caddyfile has an explicit `http://` block for all seven hosts that serves `/.well-known/acme-challenge/*` from `/var/lib/hawkeye-acme` and redirects everything else to HTTPS. Drop the token file there, then `ans-cli verify-acme <id>`.

This is separate from the Let's Encrypt HTTP-01 challenge Caddy solves for itself; Caddy's own solver is registered ahead of these routes and still wins for renewals.

## Known gap: the TLSA records do not match the certificate we serve

The registry issues each agent a server certificate from the **GoDaddy Private ANS Issuing CA** and publishes a TLSA record binding it: `3 0 1 <sha256 of that certificate>`.

Caddy serves a **Let's Encrypt** certificate instead, because a private-CA certificate fails in every browser and in `curl`, and public reachability is the hard requirement. The consequence is that the published TLSA records do not describe the certificate on the wire, so DANE validation fails rather than merely being absent.

That is the honest position and it costs us Silver tier. Three ways out, none free:

1. Serve the ANS-issued server certificate and lose plain `curl` and browser reachability.
2. Republish TLSA as `3 1 1` over the Let's Encrypt SPKI, and pin Caddy's key so renewal does not invalidate it.
3. Remove the TLSA records and state plainly that we are Bronze.

Not decided. `ans/CLAUDE.md` has the tier table this trades against.
