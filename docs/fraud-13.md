# The 13 attacks at fraud.webmesh.ai

**Pivot note, 2026-09-19.** The thirteen shapes and their implementations are unchanged; the pivot does not touch the verification layer.
**What changed is the analogue, and it got better.** The substitution this document runs on was "a spending mandate is to money what a verified sensing claim is to an armed response".
It is now **"a spending mandate is to money what a shutter grant is to a camera"**, which is a tighter fit: a grant authorizes one specific physical action at one specific moment, exactly as a mandate authorizes one payment.
Re-read `payTo_binding_check` and `underpay_valid_sig` against `shutter/CLAUDE.md`; both land harder there than they did on a 911 call.
See `docs/PIVOT.md`.

Assigned research item 1 from the GoDaddy track briefing.
Written 2026-09-19.

`fraud.webmesh.ai` is the track owner's adversarial test agent.
It runs a battery of targeted security probes with no credentials required, callable at `ans://v1.0.2.fraud.webmesh.ai`, with a `run_battery` verb that executes all thirteen concurrently.
Machine-readable index at `/.well-known/agents-index.json`.

This doubles as engineering work rather than background reading.
`agents/CLAUDE.md` specifies driving the refusal demo with this battery rather than a button labeled "simulate attacker," so the research and the demo are one effort.
Being able to say "we ran your attack suite, here are the thirteen results" is the strongest single sentence available to us on Sunday morning.

## Status

Two facts, and they are different facts. Keep them apart when speaking to a judge.

**1. We have not run his battery, and we cannot.**
Verified 2026-09-19 against `https://fraud.webmesh.ai/mcp/`: all sixteen tools, and `run_battery` plus every one of the thirteen attack tools takes **no target parameter**. The target is hardwired to `supplier.webmesh.ai`, which its own card states in its first line.
It is a reference implementation of a threat model, not a scanner.

**2. We implemented all thirteen shapes ourselves, and we pass them.**
`app/backend/hawkeye_backend/verification/` is the defence. `app/backend/tests/` is the local battery.

```
$ cd app/backend && python -m pytest -q
37 passed
```

Run it before believing this table.

| # | Probe | Our test | Result |
|---|---|---|---|
| - | baseline: an honest claim is accepted | `test_00_honest_claim_is_accepted` | ASSERTED, spoken |
| 1 | `replay_booking` | `test_01_replay_booking` | PROOF_REJECTED `proof_replay` |
| 2 | `underpay_booking` | `test_02_underpay_booking` | CLAIM_REJECTED `claim_signature` |
| 3 | `tamper_mandate` | `test_03_tamper_mandate` | CLAIM_REJECTED `claim_signature` |
| 4 | `underpay_valid_sig` | `test_04_underpay_valid_sig` | Signature valid, authority **capped** to CORROBORATING, not spoken |
| 4 | lower bound: UNTRUSTED source | `test_04b_untrusted_is_discarded` | CLAIM_REJECTED `profile_authorization` |
| 5 | `quote_swap_attack` | `test_05_quote_swap_attack` | CLAIM_REJECTED `incident_binding` |
| 6 | `wrong_audience_attack` | `test_06_wrong_audience_attack` | CLAIM_REJECTED `audience_binding` |
| 7 | `wrong_scope_attack` | `test_07_wrong_scope_attack` | Zone carried and bound; cannot be widened |
| 8 | `wrong_dpop_key_attack` | `test_08_wrong_dpop_key_attack` | PROOF_REJECTED `proof_key_binding` |
| 9 | `corrupt_jws_attack` | `test_09_corrupt_jws_attack` | CLAIM_REJECTED `claim_signature`, no exception |
| 9 | harder: not even valid base64 | `test_09b_garbage_signature_does_not_throw` | CLAIM_REJECTED, no exception |
| 10 | `superseded_format_attack` | `test_10_superseded_format_attack` | CLAIM_PARSE_ERROR |
| 10 | other direction: future schema | `test_10b_unknown_schema_version_refused` | CLAIM_REJECTED `schema_version` |
| 11 | `unknown_key_mandate` | `test_11_unknown_key_mandate` | CLAIM_REJECTED `known_issuer` |
| 12 | `replay_settled` | `test_12_replay_settled` | CLAIM_REJECTED `incident_lifecycle` |
| 13 | `canonicalization_probe` | `test_13_canonicalization_probe` | `1` and `1.0` canonicalize identically |
| B1 | `card_drift_watch` | `test_fingerprint_*` in `test_card.py` | Stable across key order, changes on content |
| M4 | `payTo_binding_check` | `test_dispatch_address_*` in `test_card.py` | Committed, not published; swap refused |

Nine further tests cover things the battery does not probe: proof-target binding, lifting a proof onto a different claim, claim and proof expiry, oversize payloads refused before parsing, agent suppression, replay-cache fail-closed, and the ordering rule below.

**Two real bugs were found by writing these**, which is the argument for writing them rather than only documenting them:

- `self._replay = replay or ReplayCache()` silently discarded an injected cache, because `ReplayCache` defines `__len__` and an empty cache is falsy. Every verifier got a private throwaway. That is exactly the failure ANS-6 §7.6 names under "shared scope behind load balancers": a proof replays cleanly against any replica holding its own cache. It passed every other test. Regression test: `test_injected_replay_cache_is_actually_used`.
- The test signer built its signing input by hand and serialized datetimes differently from pydantic, so nothing verified. That is the canonicalization-drift class probe #13 exists to catch, arriving for free in our own code within an hour of writing it. The signer now goes through the model rather than around it.

**What we say on stage:** "His battery only attacks his own supplier, so we implemented all thirteen against ours. Here they are, and here are the two bugs they found." That is true, checkable, and stronger than a claimed pass.

## The translation that makes the battery apply to us

The battery is built around agentic payments: RFC 9421 spending mandates issued by `authority.webmesh.ai`, DPoP proof-of-possession (RFC 9449), quote binding, and EVM settlement.
Hawk Eye moves no money, so a naive reading is that none of it applies.

That reading is wrong, and the correct one is the most useful idea in this file.

**A spending mandate is to money what a verified sensing claim is to an armed response.**

Both are a scoped, signed, audience-bound, time-bound authorization that permits an irreversible act.
Every structural property the battery probes for has a direct analogue:

| Mandate property | Hawk Eye analogue |
|---|---|
| `max_amount` | The severity a claim is allowed to trigger, gated by `recommendedProfile` |
| Audience binding | A claim addressed to *this* `master`, not any coordinator that will listen |
| Scope binding | A claim about the main bedroom used to justify a dispatch about the main bedroom |
| Quote binding | A claim bound to *this* incident, not replayed into a later one |
| DPoP key binding | The sensing agent proving it holds the key its Identity Certificate names |
| Nonce / replay state | The same reading not counted twice as corroboration |
| Signature validation | JWS on every inter-agent message |

Once the substitution is made, the battery is a checklist for `master`'s verification logic.
That is how we should present it.

## The thirteen

Grouped as the battery groups them: ten attack tests and three structural probes.
"Expected" is the verdict `fraud.webmesh.ai` expects a correct implementation to return.

### Attack tests

| # | Probe | What it does | Expected | Hawk Eye analogue | What we must implement |
|---|---|---|---|---|---|
| 1 | `replay_booking` | Reuses a spent DPoP proof to confirm nonce tracking rejects replay. | `DPOP_REJECTED` | A sensing agent's reading replayed to inflate corroboration, or an old lost-signature claim replayed into a new incident. | Nonce tracking per claim. The same signed reading must never count twice toward a dispatch threshold. |
| 2 | `underpay_booking` | Forges `max_amount=1.0` without re-signing, testing that signature verification is independent of amount checks. | `MANDATE_REJECTED` | A claim's severity field edited without re-signing. | Verify the signature over the whole payload before reading any field from it. Never parse first and verify later. |
| 3 | `tamper_mandate` | Inflates `max_amount` tenfold after signing. | `MANDATE_REJECTED` | "Respiration irregular" rewritten to "respiration absent" in transit. **This is the Infinite Impostor in one line.** | JWS integrity per message, with the verified payload being the only one any logic sees. |
| 4 | `underpay_valid_sig` | Submits a genuinely authority-signed mandate for $0.01 against a higher-priced ticket. Tests amount enforcement *beyond* signature validity. | `MANDATE_REJECTED` | A validly signed READ_ONLY claim used as the sole basis for a 911 call. | The `recommendedProfile` gate. A valid signature is not authorization. READ_ONLY corroborates and never triggers. This is the probe that maps most directly onto our profile table. |
| 5 | `quote_swap_attack` | Uses a mandate issued for quote A to book under quote B. | `MANDATE_REJECTED` | A genuine lost-signature claim from Tuesday replayed to justify a dispatch on Wednesday. | Incident-ID binding. Every claim carries the incident it was produced for, and `master` rejects cross-incident reuse. |
| 6 | `wrong_audience_attack` | Submits a mandate addressed to `rogue-supplier` rather than the target. | `MANDATE_REJECTED` | A claim addressed to a different household's `master`, or to a neighbour's installation. | Audience binding on every claim. Our ANSNames are per-installation, so this is checkable. |
| 7 | `wrong_scope_attack` | Applies a MAD-NYC mandate to a MAD-SIN booking. | `MANDATE_REJECTED` | A claim scoped to the kitchen used to justify "unresponsive occupant in the main bedroom." | Zone scoping in the claim, enforced at `master`. Room-level zones already exist in `agents/people`. |
| 8 | `wrong_dpop_key_attack` | Valid mandate, but the DPoP proof comes from a different key than `mandate.jkt`. | `DPOP_REJECTED` | An agent presenting a valid certificate it does not hold the private key for. | mTLS with the Identity Certificate. The handshake challenge is the defense and it is already the architecture. |
| 9 | `corrupt_jws_attack` | Structurally valid mandate with the last two bytes of the JWS signature flipped. Confirms clean rejection rather than an exception. | `MANDATE_REJECTED` | Bit-level corruption from a lossy link, or a clumsy tamper attempt. | **Fail closed, and fail quietly.** A crashed verifier mid-incident is a worse outcome than a rejected claim. Test this one deliberately; it is the probe most likely to catch a real bug in our code. |
| 10 | `superseded_format_attack` | A legacy mandate stripped of `scope`, `jkt`, and signature. | `MANDATE_REJECTED` or `MANDATE_PARSE_ERROR` | An older sensing agent build emitting a claim without a verification envelope. | Schema-version enforcement. An unversioned or under-specified claim is discarded, not accepted as a best effort. Directly relevant since we will have five agents at different build stages all weekend. |

### Structural probes

| # | Probe | What it does | Expected | Hawk Eye analogue | What we must implement |
|---|---|---|---|---|---|
| 11 | `unknown_key_mandate` | A mandate signed by an Ed25519 key absent from the authority's trust card. Tests fail-closed key validation. | `MANDATE_REJECTED` | A tenth agent that nobody registered, claiming to be a sensing agent. | Fail-closed trust store. An unknown key is a rejection, never an unknown-therefore-allow. |
| 12 | `replay_settled` | Resubmits an already-used mandate with fresh DPoP proofs, probing EIP-3009 nonce state on Sepolia Base. | `MANDATE_REJECTED`, `PAYMENT_REQUIRED`, or `EVM_SETTLEMENT_FAILED` | Re-triggering a dispatch for an incident already dispatched. Fresh envelope, spent authorization. | Incident lifecycle state in `master`. Freshness of the wrapper does not refresh the claim inside it. |
| 13 | `canonicalization_probe` | Requests mandates where `max_amount` serializes differently, float versus int, detecting JCS consistency drift. | Consistent handling across implementations | Two of our five agents serializing the same value differently, producing signature mismatches that look like tampering. | JCS canonicalization, decided once and applied across all five agents. This is the probe most likely to bite us as an ordinary bug rather than as an attack. |

### Bonus structural checks

The battery also exposes two checks outside the thirteen:

- **`payTo_binding_check`** verifies that a settlement address is attested rather than asserted.
  Our analogue is the **physical address the incident is anchored to**.
  This is the most important single binding in the entire project.
  An agent that can change the address a dispatch is sent to is a swatting tool, and no amount of claim verification upstream matters if the destination is forgeable.
  The address must be bound at registration and sealed into the transparency log, not carried in the claim.
- **`card_drift_watch`** detects unauthorized agent card mutations.
  This is our version-bound certificate drift story, arriving from the other direction, and it confirms the track owner considers card drift a first-class attack rather than a hygiene issue.
  It is also a reminder that our own cards must be kept current, since a stale card and a tampered card look identical to a monitor.

## What this tells us about `master`, concretely

The battery is thirteen ways of asking one question: **does this implementation treat a valid signature as authorization?**

Ten of the thirteen pass only if the answer is no.
Probe 4 is the purest form of it, a genuinely authority-signed mandate for the wrong amount, and it is the one to put on a slide.

`master`'s verification order must therefore be:

1. **Verify the envelope.** mTLS handshake, then JWS signature over the canonical payload. Nothing downstream sees an unverified field. (Probes 2, 3, 8, 9, 11, 13)
2. **Check bindings.** Audience, scope, incident ID, nonce. (Probes 1, 5, 6, 7, 12)
3. **Check schema version.** Reject under-specified claims rather than interpreting them charitably. (Probe 10)
4. **Then, and only then, apply the profile gate.** What this agent's `recommendedProfile` permits this claim to trigger. (Probe 4)
5. **Log what was discarded, with the reason.** Sealed via `agents/replay`.

Step 5 is not an afterthought.
"The agent that speaks to 911 only repeats claims it can cryptographically verify, and it tells you what it discarded" is the sentence that carries the submission, and the discard log is what makes it checkable rather than assertable.

## Running it

**Correction, 2026-09-19: the battery cannot be pointed at us.**

Verified directly against `https://fraud.webmesh.ai/mcp/`. It exposes 16 tools. `run_battery` and all 13 attack tools take **no target parameter**; only `replay_booking`, `underpay_booking`, and `tamper_mandate` accept arguments, and those are `captured_mandate`, `captured_dpop_proof`, and `quote_id`. The target is hardwired to `supplier.webmesh.ai`, which its own card states in the first line.

It is a reference implementation of a threat model, not a scanner. That does not reduce the value of the thirteen translations above; it changes who does the work.

1. ~~**Implement the thirteen shapes locally.**~~ **Done 2026-09-19.** `app/backend/hawkeye_backend/verification/`, built to ANS-6 Method B rather than an invented scheme. The wire-level verification order is in `ans/CARD.md` and in `verifier.py`'s docstring.
   Still to do: move this from the hub into `agents/master` proper once master exists, or have master import it. It is deliberately a standalone package with no FastAPI or hub dependencies so that move is an import change.
2. ~~Capture all thirteen verdicts verbatim.~~ Done; see the table above.
3. ~~Fill in the results column above, including failures.~~ Done. Two bugs found and fixed, both recorded above rather than quietly cleaned up.
   A documented failure with a stated reason is worth more than a claimed pass, and the track owner wrote these probes specifically to be failed by naive implementations.
4. **Separately, run `agent.webmesh.ai verify_agent` against all five hostnames.** That one does take an arbitrary host, and it is what will actually be pointed at us: DNS, DNSSEC, Transparency Log proof, published agent card, plus a live A2A message. Its `compatibility_verdict` is the thing to have clean before judging. See `ans/CARD.md`.
5. Pick one probe for the live demo.
   Probe 4, `underpay_valid_sig`, is the best candidate: a genuinely valid signature that must still be refused.
   It is the one that best demonstrates the difference between authentication and authorization to a room, and it is the one whose Hawk Eye analogue a non-technical judge understands immediately.

## Sources

- [fraud.webmesh.ai](https://fraud.webmesh.ai), agent card and battery description, retrieved 2026-09-19
- [ANS-6 agent authentication spec](https://github.com/agentnameservice/ans-registry/blob/main/spec/ans-6-agent-authentication.md), badge and SCITT verification tiers, mTLS and DPoP (RFC 9449)
- [RFC 9449, OAuth 2.0 Demonstrating Proof of Possession](https://www.rfc-editor.org/rfc/rfc9449.html)
- [RFC 9421, HTTP Message Signatures](https://www.rfc-editor.org/rfc/rfc9421.html)
