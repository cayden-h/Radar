#!/usr/bin/env bash
#
# Finish ANS registration for the three agents the pivot added.
#
# presence, shutter and vision were registered with the RA on 2026-09-20 and
# have been sitting at PENDING_DNS since. Their ACME HTTP-01 tokens are already
# staged on the box and serving over plain HTTP; what is missing is the DNS
# records and the two verification calls that consume them.
#
# The other four agents - master, intruder, caller, replay - are already ANS
# ACTIVE and this script does not touch them.
#
# Prerequisites:
#
#   1. ANS_API_KEY (or ANS_OAUTH_TOKEN) exported.
#   2. The twelve DNS records printed by `--records` published at Porkbun and
#      propagated. The script checks and refuses to call verify-dns without them,
#      because a failed verification burns an attempt against a registration that
#      expires 2026-09-27.
#
# Usage:
#   scripts/finish-registration.sh --records   # print the DNS records, do nothing
#   scripts/finish-registration.sh --check     # report what is and is not published
#   scripts/finish-registration.sh             # run the remaining steps
#
set -euo pipefail

cd "$(dirname "$0")/.."
AGENTS=(presence shutter vision)

agent_id() { python3 -c "import json;print(json.load(open('.ans/$1/status.json'))['agentId'])"; }

records() {
  python3 - <<'PY'
import json
for a in ("presence", "shutter", "vision"):
    s = json.load(open(f".ans/{a}/status.json"))
    print(f"# {a}  ({s['agentId']})")
    for r in s["registrationPending"]["dnsRecords"]:
        print(f"{r['type']:6} {r['name']:42} {r['value']}")
    print()
PY
}

# The four already-ACTIVE agents were verified with three records, not four:
# _ans, _ans-badge and TLSA. None of them has an HTTPS (TYPE65) record and all
# four passed verify-dns anyway, so the HTTPS record is treated as optional here
# rather than blocking on a record the RA demonstrably does not require.
# Queried against the zone's own nameserver, not the local resolver. A resolver
# that was asked for one of these names *before* it was published holds an
# NXDOMAIN for the zone's 1800s negative TTL, and will keep reporting a record
# missing for half an hour after it is live. That is exactly the window this
# script runs in, and a false "missing" here blocks a verify-dns call against a
# registration with an expiry on it.
NS=$(dig +short NS batradar.club | head -1)

check() {
  local missing=0
  for a in "${AGENTS[@]}"; do
    for pair in "TXT:_ans.$a.batradar.club" "TXT:_ans-badge.$a.batradar.club" \
                "TLSA:_443._tcp.$a.batradar.club"; do
      local type="${pair%%:*}" name="${pair#*:}"
      if [ -z "$(dig +short @"$NS" "$type" "$name")" ]; then
        printf "  missing  %-6s %s\n" "$type" "$name"; missing=$((missing + 1))
      else
        printf "  present  %-6s %s\n" "$type" "$name"
      fi
    done
  done
  return "$missing"
}

case "${1:-}" in
  --records) records; exit 0 ;;
  --check)   check && echo "all records published" || echo "records still missing"; exit 0 ;;
esac

: "${ANS_API_KEY:?export ANS_API_KEY (or ANS_OAUTH_TOKEN) first}"

# The RA validates ACME over plain HTTP and does not follow redirects. Confirm
# the token is still reachable that way before spending a verification attempt.
echo "==> checking the ACME tokens still serve over plain HTTP"
for a in "${AGENTS[@]}"; do
  token=$(grep "HTTP Path" ".ans/$a/register.txt" | sed 's|.*/||')
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
    "http://$a.batradar.club/.well-known/acme-challenge/$token")
  [ "$code" = "200" ] || { echo "  $a: token returned $code, not 200"; exit 1; }
  echo "  $a: 200"
done

# Already-VERIFIED is a success, not a failure. The RA refuses to re-run a
# validation that passed ("Validation status is VERIFIED and cannot be retried"),
# and all three of these were verified when they were first registered. Treating
# that as an error would abort the run one step before the part that is actually
# outstanding.
echo "==> verify-acme"
for a in "${AGENTS[@]}"; do
  out=$(ans-cli verify-acme "$(agent_id "$a")" 2>&1) || true
  if printf '%s' "$out" | grep -q "status is VERIFIED"; then
    echo "  $a: already verified"
  elif printf '%s' "$out" | grep -qi "error"; then
    echo "  $a: FAILED"; printf '%s\n' "$out" | sed 's/^/    /'; exit 1
  else
    echo "  $a: verified"
  fi
done

echo "==> checking DNS"
check || { echo "publish the records above first: scripts/finish-registration.sh --records"; exit 1; }

echo "==> verify-dns"
for a in "${AGENTS[@]}"; do
  echo "  $a"; ans-cli verify-dns "$(agent_id "$a")" | sed 's/^/    /'
done

echo "==> certificates"
for a in "${AGENTS[@]}"; do
  id=$(agent_id "$a")
  ans-cli submit-identity-csr "$id" --csr-file ".ans/$a/identity.csr" | sed 's/^/    /'
  ans-cli submit-server-csr   "$id" --csr-file ".ans/$a/server.csr"   | sed 's/^/    /'
  ans-cli get-identity-certs "$id" -j > ".ans/$a/identity-certs.json"
  ans-cli get-server-certs   "$id" -j > ".ans/$a/server-certs.json"
  ans-cli badge              "$id" -j > ".ans/$a/badge.json"
  ans-cli status             "$id" -j > ".ans/$a/status.json"
  echo "  $a: $(python3 -c "import json;print(json.load(open('.ans/$a/status.json'))['agentStatus']['status'])")"
done

echo
echo "All three should now read ACTIVE. Confirm from outside:"
echo "  for h in presence shutter vision; do dig +short TXT _ans.\$h.batradar.club; done"
