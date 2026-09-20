#!/usr/bin/env bash
# Register agents with ANS. Written 2026-09-19, made roster-driven 2026-09-20.
#
# The roster is read from `agents.core.identity`, not typed in here. The old
# version of this script carried its own list of five, and the 2026-09-19 pivot
# immediately made that list wrong: `people` became `presence` and `shutter` and
# `vision` arrived. A second copy of the roster is a copy that will disagree
# with the first one by morning, and the disagreement shows up as an agent that
# serves a card nobody registered.
#
#   ./scripts/register-agents.sh                    # every agent in the roster
#   ./scripts/register-agents.sh presence vision    # just these
#   ANS_ENV=ote ./scripts/register-agents.sh        # rehearsal against OTE
#
# Already-registered agents are skipped: registration is not idempotent at the
# registry, and re-submitting one that is ACTIVE would mint a second identity
# for the same host.
#
# Needs a PRODUCTION GoDaddy API key. An OTE key authenticates against
# api.ote-godaddy.com and 401s against api.godaddy.com with nothing but
# "Unauthorized", which is how the first attempt was lost: create the key at
# https://classic-developer.godaddy.com/keys with type Production and complete
# the mobile-PIN prompt, which is the step that actually gates production.
#
# Credentials live in ~/.hawkeye-ans.env, outside the repo. The private keys
# under agents/.ans/ are gitignored and must stay that way: the identity key
# IS the agent, and anything holding it can speak as a verified Hawk Eye agent.
#
# Each agent gets its own host, because ANS publishes _ans.<host> and
# _ans-badge.<host> per registration and seven agents on one host would collide.
# After this runs, publish the ACME TXT records it prints at Porkbun, then
# scripts/verify-agents.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

# shellcheck source=/dev/null
source ~/.hawkeye-ans.env

if [[ "${ANS_ENV:-production}" == "ote" ]]; then
  export ANS_BASE_URL="https://api.ote-godaddy.com"
fi
echo "Registering against ${ANS_BASE_URL}"

PYTHON="${HAWKEYE_PYTHON:-../app/backend/.venv/bin/python}"
VERSION=$(PYTHONPATH=. "$PYTHON" -c 'from agents.core.identity import VERSION; print(VERSION)')

slugs=("$@")
if [[ ${#slugs[@]} -eq 0 ]]; then
  mapfile -t slugs < <(PYTHONPATH=. "$PYTHON" -c \
    'from agents.core.identity import ROSTER
for a in ROSTER: print(a.slug)')
fi

for slug in "${slugs[@]}"; do
  IFS='|' read -r host name summary < <(PYTHONPATH=. "$PYTHON" -c \
    "from agents.core.identity import identity
a = identity('${slug}')
print(f'{a.host}|{a.name}|{a.summary}')")
  dir=".ans/${slug}"

  echo
  echo "=== ${name} -> ${host} ==="

  if [[ -f "${dir}/register.txt" ]]; then
    echo "  already registered (${dir}/register.txt exists); skipping"
    continue
  fi

  mkdir -p "$dir"
  # EC P-256 for identity, RSA for server, which is what the registry accepts.
  # The ANSName goes in the SAN as a URI, which is what "version-bound" means
  # concretely: the certificate names the exact version it was issued for.
  ans-cli generate-csr \
    --host "$host" \
    --org "Hawk Eye" \
    --version "$VERSION" \
    --out-dir "$dir"

  # --endpoint-protocol A2A because the wire between these seven is pull-only
  # A2A JSON-RPC with a server-issued challenge, not MCP.
  ans-cli register \
    --name "$name" \
    --host "$host" \
    --version "$VERSION" \
    --identity-csr "${dir}/identity.csr" \
    --server-csr "${dir}/server.csr" \
    --endpoint-url "https://${host}/a2a" \
    --metadata-url "https://${host}/.well-known/agent-card.json" \
    --endpoint-protocol A2A \
    --description "$summary" \
    | tee "${dir}/register.txt"
done

echo
echo "Submitted. Next: publish every _acme-challenge TXT record above at"
echo "Porkbun, wait for propagation, then ./scripts/verify-agents.sh"
