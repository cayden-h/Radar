#!/usr/bin/env bash
# Register the five agents with ANS. Written 2026-09-19.
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
#   ./scripts/register-agents.sh            # production
#   ANS_ENV=ote ./scripts/register-agents.sh  # rehearsal against OTE
#
# Each agent gets its own host, because ANS publishes _ans.<host> and
# _ans-badge.<host> per registration and five agents on one host would collide.
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

# slug|display name|description
AGENTS=(
  "people|agents/people|Who is in the building, where each one is, whether they are breathing, and whether one of them is on the floor."
  "intruder|agents/intruder|Detects and tracks a presence that no registered device accounts for."
  "master|agents/master|The incident coordinator, and the strictest verification point in the system."
  "caller|agents/caller|The agent that talks to humans: the 911 operator by phone, and the resident in the app. The only agent that acts on the outside world."
  "replay|agents/replay|The incident recorder. What happened, in order, on whose authority, sealed."
)

for entry in "${AGENTS[@]}"; do
  IFS='|' read -r slug name description <<< "$entry"
  host="${slug}.batradar.club"
  dir=".ans/${slug}"

  echo
  echo "=== ${name} -> ${host} ==="

  # --endpoint-protocol A2A because the wire between these five is pull-only
  # A2A JSON-RPC with a server-issued challenge, not MCP.
  ans-cli register \
    --name "$name" \
    --host "$host" \
    --version 0.1.0 \
    --identity-csr "${dir}/identity.csr" \
    --server-csr "${dir}/server.csr" \
    --endpoint-url "https://${host}/a2a" \
    --metadata-url "https://${host}/.well-known/agent-card.json" \
    --endpoint-protocol A2A \
    --description "$description" \
    | tee "${dir}/register.txt"
done

echo
echo "All five submitted. Next: publish every _acme-challenge TXT record above"
echo "at Porkbun, wait for propagation, then ./scripts/verify-agents.sh"
