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

## Security headers

Set 2026-09-20, in the `(agent)` snippet so all seven hostnames inherit them. `ans/CARD.md` measure 9.

```
Strict-Transport-Security   max-age=31536000; includeSubDomains
X-Content-Type-Options      nosniff
X-Frame-Options             DENY
Content-Security-Policy     default-src 'none'; frame-ancestors 'none'
Referrer-Policy             strict-origin-when-cross-origin
Permissions-Policy          geolocation=(), camera=(), microphone=()
```

The last one is set deliberately rather than copied from the reference stack.
A system whose entire pitch is that the camera cannot see until a signature checks out should say so in a header a machine can read.

These are on the HTTPS blocks only.
The `http://` block still serves the RA's ACME token with no redirect and no HSTS, which is the behaviour registration depends on; HSTS over plain HTTP is ignored by spec anyway.

```sh
curl -sI https://shutter.batradar.club/.well-known/agent-card.json | grep -i permissions-policy
```

## All seven agents are ANS ACTIVE

Finished 2026-09-20. `presence`, `shutter` and `vision` were registered with the RA that morning and sat at `PENDING_DNS` until their records were published.

```sh
cd agents && scripts/finish-registration.sh --check    # what is published
```

Each agent needs **four** records, and the first three are the ones people forget:

| Record | Why |
|---|---|
| `_ans.<host>` TXT | The ANSName and endpoint |
| `_ans-badge.<host>` TXT | The transparency-log entry |
| `_443._tcp.<host>` TLSA | `3 0 1` over the certificate the RA issued. See below |
| `<host>` HTTPS (TYPE65) | `1 . alpn=h2`. **Required**, despite the four older agents having passed without it |

The HTTPS record is the trap. `master`, `intruder`, `caller` and `replay` are ACTIVE and have no HTTPS record at all, which made it look optional; `verify-dns` rejected all three new agents until it was added. Do not reason from what the older four happen to have.

Two other things that cost time and are worth knowing:

- **`verify-acme` is not re-runnable.** All three were already validated at registration, and the RA answers `Validation status is VERIFIED and cannot be retried`. That is a success, not a failure, and the script treats it as one.
- **Check DNS against the zone's own nameserver, not your resolver.** A resolver asked for one of these names before it was published caches the NXDOMAIN for the zone's 1800s negative TTL, and will keep reporting a live record missing for half an hour. Both scripts query `$(dig +short NS batradar.club)` directly for this reason.

## TLSA, DANE, and why we are Bronze

**The published TLSA records do not describe the certificate on the wire, and cannot.**

The RA issues each agent a server certificate and publishes `3 0 1 <sha256 of that certificate>`. Caddy serves **Let's Encrypt** instead, because reachability in a browser and in plain `curl` is the hard track requirement. So DANE validation **fails** rather than merely being absent.

### We tried to fix it, and it is not fixable while staying registered

On 2026-09-20 all seven were republished as `3 1 1` over the Let's Encrypt SPKI - the correct record for the certificate actually served - with `reuse_private_keys` set in the Caddyfile so renewals could not rotate the key out from under it.

`verify-dns` refuses that record:

```
Incorrect DNS records (fix these):
  _443._tcp.presence.batradar.club  TLSA  EXPECTED 3 0 1 <hash>  FOUND 3 1 1 E60CFB...
```

Publishing **both** records was the obvious workaround and was tested rather than assumed: RFC 7671 accepts a certificate matching any one TLSA record, so DANE would have passed. The RA does an exact-set comparison and still fails on the extra record.

**So a DANE-correct TLSA record and an ANS registration are mutually exclusive.** Registration wins. An unregistered agent is absent from the Trust Index and fails `agent.webmesh.ai verify_agent`, and that is worth more than a DANE record nobody at the table is checking. All seven publish the RA's `3 0 1`, we are Bronze, and we say so out loud rather than letting someone find it.

This supersedes the older three-options framing, which did not know that option 2 blocks registration outright.

### The lead worth ten minutes before judging

The RA's **server** certificate is issued by `GoDaddy TLS Intermediate CA DV - R1v1`. The **identity** certificate is issued by `GoDaddy Private ANS Issuing CA - PR1v1`. Those are different CAs, and this document previously conflated them - the "private CA breaks every browser" reasoning was about the identity certificate.

If that DV intermediate is in public trust stores, then serving the ANS-issued server certificate instead of Let's Encrypt gets everything at once: `3 0 1` becomes true, DANE validates, `verify-dns` still passes, and browsers and `curl` keep working.

Unconfirmed. The RA returns no chain with the certificate, `openssl verify` fails against the local bundle, and the intermediate is not one of GoDaddy's well-known public ones. Treat it as a lead, not a plan. `scripts/tlsa.sh --wire` prints what the records would need to become.

## Still stale: the `people` records

`_ans.people.batradar.club` and `_443._tcp.people.batradar.club` are still published and still describe the pre-pivot agent. `people` became `presence`, the host no longer answers, and both should be deleted.

**Left in place pending a decision**, because deleting records is not reversible from here.
