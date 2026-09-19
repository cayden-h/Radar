#!/usr/bin/env bash
# Drive the five registrations from PENDING_VALIDATION to ACTIVE.
#
# Run it after the _acme-challenge TXT records from register-agents.sh are
# published and propagating. It is safe to re-run: every step is idempotent and
# the script reports status rather than assuming it.
#
# Order matters and the CLI enforces it: ACME proves you own the host, and only
# then does the registry hand over the _ans and _ans-badge TXT records. Both are
# required. TLSA is skipped unless the zone has DNSSEC enabled - turn DNSSEC on
# at Porkbun if you want Silver tier, because DANE is what the second trust
# channel is made of.
set -euo pipefail

cd "$(dirname "$0")/.."

# shellcheck source=/dev/null
source ~/.hawkeye-ans.env
if [[ "${ANS_ENV:-production}" == "ote" ]]; then
  export ANS_BASE_URL="https://api.ote-godaddy.com"
fi

for slug in people intruder master caller replay; do
  host="${slug}.batradar.club"
  echo
  echo "=== ${slug} ==="

  # The agent id is printed by register; pull it back out rather than asking a
  # human to copy five UUIDs around at 2am.
  id=$(grep -oE '/v1/agents/[0-9a-f-]{36}' ".ans/${slug}/register.txt" | head -1 | cut -d/ -f4)
  if [[ -z "$id" ]]; then
    echo "  no agent id in .ans/${slug}/register.txt - register it first"
    continue
  fi
  echo "  id: ${id}"

  # Must run from a terminal, not a browser: the RA checks the caller.
  ans-cli verify-acme "$id" || echo "  verify-acme not satisfied yet; check the TXT record has propagated"
  ans-cli verify-dns  "$id" || echo "  verify-dns not satisfied yet; publish _ans.${host} and _ans-badge.${host}"
  ans-cli status "$id"
done

echo
echo "Looking for ACTIVE on all five. Then: ans-cli get-identity-certs <id>"
