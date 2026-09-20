# The trust layer, explained

**Pivot note, 2026-09-19.** The trust layer is untouched by the camera pivot; this file's mechanics are all still correct.
Two substitutions when you read it: the roster is seven agents rather than five, and the canonical "something valuable moves" example is now a servo uncovering a camera lens rather than an armed response to an address. The second is the one to use on stage, because a judge can watch it happen.
See `docs/PIVOT.md`.

What `agents/master` actually does to a claim before `agents/caller` is allowed to say it out loud,
and what the thirteen `fraud.webmesh.ai` attacks are trying to do to it.

This is the abstract part of the project. The other diagrams in `architecture-diagrams.md` show
what happens; this one shows why any of it can be believed.

## Start here: a claim is a signed permission slip

A sensing agent never just "reports a number". It issues a slip that reads, in effect:

> I, the people agent, say the person in the main bedroom has stopped breathing.
> This slip is for the master at *this* house, about incident #1234, about the *main bedroom*,
> it is good for five minutes, only the holder of *this* key may hand it over,
> and it is strong enough to justify calling 911.

Every clause in that sentence is a lock.
**The thirteen attacks are thirteen ways of trying to pick one of them.**

```mermaid
flowchart LR
    subgraph C["ONE CLAIM - a signed permission slip"]
      direction TB
      I["issuer<br/>who is speaking"]
      A["audience<br/>which master it is for"]
      N["incident_id<br/>which emergency"]
      Z["zone_scope<br/>which room"]
      V["field + value<br/>respiration = absent"]
      S["severity_ceiling<br/>the most it may ever trigger"]
      K["proof_key_thumbprint<br/>who is allowed to hand it over"]
      X["expires_at<br/>how long it stays good"]
    end
    C ==>|"one Ed25519 signature over ALL of it"| U["a tamper-evident unit<br/><br/>change any single field<br/>and it stops verifying"]

    classDef ok fill:#14532d,stroke:#4ade80,color:#fff
    class U ok
```

Why sign the whole slip rather than just the reading: so that "respiration irregular" cannot be
edited into "respiration absent" somewhere between the sensor and the dispatcher. That edit is the
Infinite Impostor, and it is the attack this project exists to stop.

## The two stages, and why the second one is the interesting one

Verification is not one question. It is two, in order.

**Stage 1 asks "is this real?"** - is the signature good, is the key registered, has this proof
been used before.

**Stage 2 asks "is it allowed to do this?"** - a perfectly real slip can still be the wrong slip.

```mermaid
flowchart TD
    IN["claim + possession proof arrive at master"] --> S1

    S1["STAGE 1 - AUTHENTICATION<br/><b>Is this really from who it says?</b><br/><br/>size bound · strict parse · schema version<br/>registered issuer · signature verifies<br/>presenter holds the named key · proof not already spent"]

    S1 -->|"any check fails"| R1["DISCARDED"]
    S1 -->|"all pass"| S2

    S2["STAGE 2 - AUTHORIZATION<br/><b>Is it allowed to do what it is asking?</b><br/><br/>addressed to THIS master · about THIS incident<br/>incident still open · not expired<br/>profile permits this severity"]

    S2 -->|"wrong recipient, wrong incident, stale"| R1
    S2 -->|"asks for more than its profile allows"| CAP["CAPPED<br/>downgraded, not refused"]
    S2 -->|"within its authority"| OK["ACCEPTED"]

    OK --> SPEND["spend the proof<br/><b>last, and only now</b>"]
    SPEND --> SPOKEN["caller may speak it to the 911 operator"]
    CAP --> CORR["corroboration only<br/>never the sole basis for a call"]
    R1 --> LOG["sealed into replay<br/>and shown in the app as a refusal, with the reason"]

    classDef bad fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    classDef ok fill:#14532d,stroke:#4ade80,color:#fff
    classDef warn fill:#5a4a00,stroke:#e0c000,color:#fff
    class R1,LOG bad
    class OK,SPOKEN,SPEND ok
    class CAP,CORR warn
```

Two details in that diagram are load-bearing and easy to miss.

**The proof is spent last.** Not when it arrives - after every other check has passed. If a
rejected claim burned its proof id, anyone submitting garbage could fill a fixed-size cache and
fail-close authentication for every honest agent. On this system that is a denial of service
against a 911 call.

**A discard is a product feature, not an error.** It gets sealed and it gets rendered on the
resident's phone with its reason. "The agent that speaks to 911 only repeats claims it can verify,
and it tells you what it discarded" is only checkable because the discard is a first-class object.

## The one idea worth taking away

This is the sentence the whole design turns on:

**A valid signature is not authorization.**

Ten of the thirteen attacks pass only if that is true. The clearest case is attack #4: nothing is
forged at all. The signature is genuine, the key is registered, the slip parses perfectly. It is
refused anyway, because the agent that issued it is not permitted to trigger what it is asking for.

```mermaid
flowchart LR
    A["<b>a sensing agent</b><br/><br/>signature: VALID<br/>key: REGISTERED<br/>envelope: PARSES<br/>nothing is forged<br/><br/>asks to trigger: <b>DISPATCH 911</b>"]
    A --> Q{"What is this agent's<br/>Trust Index profile?"}
    Q -->|FIDUCIARY| F["may dispatch"]
    Q -->|TRANSACTIONAL| T["may act, attributed"]
    Q -->|"READ_ONLY  ← it is this one"| R["<b>CAPPED</b> to corroboration<br/>will_be_spoken = false"]
    Q -->|UNTRUSTED| U["discarded entirely"]
    R --> O["The operator never hears it.<br/><br/>Nothing was forged.<br/>It simply was not allowed."]

    classDef warn fill:#5a4a00,stroke:#e0c000,color:#fff
    classDef bad fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    classDef ok fill:#14532d,stroke:#4ade80,color:#fff
    class R,O warn
    class U bad
    class F,T ok
```

The everyday version: a real employee badge that opens the front door does not open the vault.
Checking *who you are* and checking *what you may do* are different checks, and systems that
collapse them into one are the ones that get robbed.

## Where each of the thirteen attacks dies

Grouped by which property stops it, which is more useful than the numbering.

```mermaid
flowchart TB
    subgraph G1["Stopped by AUTHENTICATION - 'that is not really you'"]
      direction LR
      a2["#2 edit a field<br/>without re-signing"]
      a3["#3 inflate severity<br/>after signing"]
      a9["#9 corrupt the<br/>signature bytes"]
      a10["#10 strip fields,<br/>legacy format"]
      a11["#11 sign with an<br/>unregistered key"]
      a8["#8 hand it over with<br/>a different key"]
    end

    subgraph G2["Stopped by AUTHORIZATION - 'real, but not allowed'"]
      direction LR
      a4["#4 valid signature,<br/>wrong magnitude"]
      a5["#5 slip from<br/>another incident"]
      a6["#6 addressed to<br/>another master"]
      a7["#7 scoped to<br/>another room"]
      a12["#12 incident already<br/>dispatched"]
    end

    subgraph G3["Stopped by SINGLE USE"]
      a1["#1 replay a proof<br/>that was already spent"]
    end

    subgraph G4["Stopped by A SHARED CANONICAL FORM"]
      a13["#13 the same value written<br/>two ways: 1 versus 1.0"]
    end

    classDef bad fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    class a1,a2,a3,a4,a5,a6,a7,a8,a9,a10,a11,a12,a13 bad
```

#13 is the odd one out and the most likely to bite us for ordinary reasons. It is not really an
attack: it is two agents writing the same number differently, producing signature mismatches that
look exactly like tampering. The defence is that there is exactly one canonicalizer in the
codebase and every agent uses it.

## What this does not do

Say this before a judge does.

The 911 operator is a person on a phone. No signature, certificate, or transparency log reaches
them. Everything above governs the machine hops *behind* the voice. The operator cannot verify us
live, and we do not claim they can - what they get is a voice, and what an investigator gets
afterwards is a sealed, tamper-evident record of exactly who claimed what.

## Where it lives in code

| Part of the diagram | File |
|---|---|
| The permission slip | `app/backend/hawkeye_backend/verification/envelope.py` |
| Both stages, in order | `app/backend/hawkeye_backend/verification/verifier.py` |
| Registered agents and profiles | `app/backend/hawkeye_backend/verification/trust.py` |
| Single use, spent last | `app/backend/hawkeye_backend/verification/replay.py` |
| The one canonicalizer | `app/backend/hawkeye_backend/verification/canonical.py` |
| All thirteen attacks, as tests | `app/backend/tests/test_battery.py` |

```sh
cd app/backend && python -m pytest -q   # 37 passed
```

Deeper reading: `docs/fraud-13.md` for the per-attack translation, `ans/CARD.md` for the agent-card
side, `docs/threat-landscape.md` for why any of this is the right threat model.
