# Architecture diagrams

Source of truth for every Mermaid diagram on the Notion page.
Notion renders these live, but Notion is not version control, so they live here and get pushed there.

**If you change one, change it here first, then push it to Notion.**

**Rewritten 2026-09-19 for the camera pivot.** The previous five diagrams described a respiration-sensing system with two incident types. See `docs/PIVOT.md`.

## 1. System architecture - the two human boundaries

The asymmetry is the whole architecture.
Human to agent is plain English at both ends. Agent to agent is ANS, every hop.

```mermaid
flowchart TD
    router[Home router] -->|802.11ac| pi[sensor/ on Pi 4B<br/>nexmon_csi]
    pi -->|motion only| presence[presence<br/>motion, zone, device association]
    roster[(Household roster)] --> intruder
    presence -->|ANS| intruder[intruder<br/>motion no device accounts for]
    intruder -->|ANS| master[master<br/>trust boundary + coordinator]

    master -->|ANS: signed grant| shutter[shutter<br/>SG92R, 90 degrees]
    shutter -->|ANS: signed attestation| vision[vision<br/>Gemini Live + mp4 segments]
    vision -->|ANS| master

    master -->|ANS| caller[caller]
    master -->|ANS| replay[replay]

    caller -->|plain English, ElevenLabs| operator([911 operator])
    caller -->|plain English| resident([The resident])
    replay -->|Resend| police([Responding department])

    classDef human fill:#2b2b2b,stroke:#888,color:#fff
    class operator,resident,police human
```

**The two dashed-in-spirit edges are the human ones.** There is no ANS there and there cannot be, because the far ends are people.

## 2. The trigger path - motion to wrist in about three seconds

The only automatic physical action in the system is a shutter opening.

```mermaid
sequenceDiagram
    autonumber
    participant P as presence
    participant I as intruder
    participant M as master
    participant S as shutter
    participant V as vision
    participant W as Watch

    Note over P: t = 0.0s, CSI perturbation
    M->>P: observe(nonce)
    P-->>M: motion in living_room, 0 devices associated
    M->>I: observe(nonce)
    I-->>M: unaccounted, sticky
    Note over M: t = 0.8s
    M->>S: shutter.challenge
    S-->>M: nonce, single use, 10s TTL
    M->>S: shutter.open(grant signed over that nonce)
    S->>S: verify against master's published trust card
    S-->>M: position open, signed attestation
    Note over S: The shield physically moves
    M->>V: observe(nonce)
    V->>S: fetch attestation
    V->>V: shield clear, open Gemini Live, start recording
    V-->>M: first description
    Note over M: t = 3.0s
    M->>W: notice, carrying the camera's first sentence
    Note over W: Nothing has dialled
```

**Step 13 is the claim.** No call exists at this point and `TASKS.md` step 6 of the end-to-end test asserts it.

## 3. The refusal path - the submission

Same sequence, with an impostor in `master`'s place.

```mermaid
sequenceDiagram
    autonumber
    participant X as Impostor at a lookalike ANSName
    participant S as shutter
    participant R as replay
    participant A as iOS app

    X->>S: shutter.challenge
    S-->>X: nonce
    X->>S: shutter.open(grant with a valid signature)
    S->>S: fetch the issuer's published trust card
    S->>S: key does not match the registered master
    S-->>X: refusal: unregistered_issuer
    Note over S: The shield does not move.<br/>There is no code path from a failed<br/>verification to a GPIO write.
    S->>R: signed refusal observation
    R->>R: seal into the hash chain
    R->>A: shield refused
    Note over A: "Something asked to open your camera<br/>and could not prove it was allowed to."
```

**A valid signature is not authorization.** That is the whole difference the fraud battery exists to probe, and here it is a physical object that did not move.

## 4. The human path - watch, phone, operator

```mermaid
flowchart TD
    notice[Notice on the watch<br/>still frame + narration] --> d{Resident decides}
    d -->|This is expected| dismiss[Vouched for this session<br/>nothing persists]
    d -->|Remember this visitor| enroll[Named, device bound<br/>next visit raises nothing]
    d -->|Start Incident, hold 1.5s| inc[Incident opens]

    inc --> caller[caller dials 911]
    caller --> op([Operator])
    op -->|question in English| fan[Fan-out of ANS-verified queries]
    fan --> ans[Spoken answer from the current frame]
    ans --> op

    caller --> phone[iOS: transcript, camera feed,<br/>what-is-happening box]
    inc --> takeover[Take over<br/>agent goes silent mid-sentence]

    op -->|near the end| email[caller asks for a destination address<br/>reads it back, recorded as operator_supplied]
    email --> replay[replay seals and sends via Resend]

    classDef human fill:#2b2b2b,stroke:#888,color:#fff
    class op human
```

**Three of the four branches out of the decision node do not call anyone.** That is the design, not a gap.

## 5. Hardware topology

```mermaid
flowchart LR
    subgraph house[The house]
      router[Archer AX1450<br/>fixed channel, 80MHz<br/>802.11ac, no band steering]
      mac[MacBook<br/>traffic generator<br/>ping -i 0.01]
      subgraph pibox[Raspberry Pi 4B]
        csi[nexmon_csi<br/>wlan0 in monitor mode]
        gpio[GPIO 18 -> servo]
        usb[USB -> camera]
      end
      servo[SG92R + opaque shield]
      cam[Logitech USB camera]
      psu[Separate 5V supply]
    end

    router -.->|measured channel| csi
    mac -->|associated, generating frames| router
    router ---|Cat5, always wired| pibox
    gpio --> servo
    usb --> cam
    psu -->|V+| servo
    pibox -->|common ground| servo
    servo -.->|covers / uncovers| cam
```

Three things this diagram is trying to stop you doing:

- **The Cat5 is not optional.** `nexmon_csi` holds the WiFi interface in monitor mode, so there is no station interface while capturing
- **The servo is not on the Pi's 5V rail.** It stalls at over 700mA and browns the Pi out, and the failure presents as the camera or the capture dying
- **The router and the Pi are on opposite sides of the sensed space.** Side by side produces a flat capture that looks exactly like a failed firmware patch. The camera does not share that constraint, because it is on a USB extension

## 6. What is real and what is not

For the honesty slide. Green is real, amber is a limit stated in the data, and there is no red column any more.

```mermaid
flowchart TD
    subgraph real[Real]
      a1[Every agent identity, certificate and card]
      a2[The signed transport and every verification]
      a3[The shutter grant and the servo]
      a4[CSI motion detection]
      a5[The camera, the footage, the hash chain]
    end
    subgraph limits[Limits, carried in the data]
      b1[No face recognition against any database<br/>only enrolled residents]
      b2[One camera, one room, and the scope is a field]
      b3[Roughly one observation per second]
      b4[The floor plan is authored, not sensed]
    end
    real --> say[Said out loud on stage<br/>before anyone asks]
    limits --> say
```

**The pivot removed the only genuinely fabricated input in the project.** The simulated gas sensor is gone, and everything remaining is either real or a stated limit.
