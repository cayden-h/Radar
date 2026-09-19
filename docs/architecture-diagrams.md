# Architecture diagrams

Source of truth for every Mermaid diagram on the Notion page.
Notion renders these live, but Notion is not version control, so they live here and get pushed there.

**If you change one, change it here first, then push it to Notion.**
Before 2026-09-19 these existed only in Notion and were not backed up anywhere.

## 1. System architecture - the two human boundaries

The asymmetry is the whole architecture.
Human to agent is plain English at both ends. Agent to agent is ANS, every hop.

```mermaid
flowchart TD
    M["MacBook<br/>traffic generator"]
    R["TP-Link Archer AX1450"]
    P["Raspberry Pi 4B<br/>nexmon_csi"]
    G["Gas reading<br/>SIMULATED - demo-trigger"]

    M -->|"802.11ac frames at 100 Hz"| R
    R -.->|"RF through walls and people"| P
    P -->|"Channel State Information"| PE
    G --> MA

    subgraph SENSE["Sensing agents"]
      PE["people<br/>count, location, personhood,<br/>respiration, movement, responsiveness"]
      INT["intruder<br/>unexpected presence"]
    end

    PE -->|ANS| INT
    NET["roster + device association"] --> INT

    PE -->|ANS| MA
    INT -->|ANS| MA

    MA["master<br/>trust boundary<br/>reads the gas sensor directly<br/>classifies Burglary / Fire"]

    MA -->|ANS| CA["caller<br/>both human boundaries"]
    MA -->|ANS| RE["replay"]

    CA ==>|"plain English voice - NO ANS"| OP(["911 operator<br/>a person"])
    CA ==>|"plain English - NO ANS"| US(["Resident<br/>iOS app"])
    RE --> LOG[("SCITT transparency log<br/>sealed, append only")]

    classDef human fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    classDef sim fill:#5a4a00,stroke:#e0c000,color:#fff
    class OP,US human
    class G sim
```

## 2. The fire path - detection, alert, human tap, call

**Rekeyed 2026-09-19** when the third incident type and fall detection were cut. This diagram used to walk the cut type's path, and the copy in Notion still does.
The choreography is unchanged, because the choreography was never about a fall: something is sensed, the app raises an alert, a human taps, and only then does anyone dial.
What changed is the claim that drives it. It is now elevated CO from the gas sensor plus a breathing signature that `people` had and no longer has, which is two independent modalities rather than two views of one CSI stream.

**Corrected 2026-09-19.** The version that sat in Notion until then went straight from `master` to
`caller` to the operator with no human in between. That contradicted the settled decision, the root
`CLAUDE.md`, and the shipped code, where `assert_human_released()` raises `AutonomousDialRefused`
on exactly that path.

The detection is autonomous. **The call is not.**

```mermaid
sequenceDiagram
    autonumber
    participant P as Pi / CSI
    participant PE as people
    participant MA as master
    participant APP as Resident app
    participant CA as caller
    participant OP as 911 operator

    P->>PE: respiration signature, back bedroom
    P->>PE: signature no longer resolvable
    PE->>PE: clock runs from the LAST resolvable frame
    PE->>MA: claim: respiration_lost 90s, back bedroom
    PE->>MA: claim: breathing 11/min, main bedroom
    MA->>MA: gas sensor: CO above the 70 ppm alarm floor
    MA->>MA: verify ANSName + version-bound cert per claim
    MA->>MA: classify FIRE - CO plus a lost signature, two modalities
    MA->>APP: ALERT - bad air, and a breathing signature just went missing

    Note over MA,CA: Hawk Eye does not dial on its own.<br/>A human tap is what releases caller.

    APP->>MA: resident taps Fire
    MA->>CA: released to dial, verified claims only
    CA->>CA: re-verify every source before speaking
    CA->>OP: "I had a breathing signature in the back bedroom 90 seconds ago<br/>and I do not have one now. 14 Oak Street."
    CA->>OP: "That is not the same as them having stopped breathing."
    MA->>APP: transcript line + instruction
    OP->>CA: "Is anyone else still breathing?"
    CA->>MA: live query - not cached
    MA->>PE: ANS-verified query
    PE-->>MA: 11 breaths per minute, main bedroom
    MA-->>CA: verified answer
    CA->>OP: "Yes. One adult, eleven breaths a minute."
    MA->>APP: instruction: get out now, do not go to the back bedroom
    MA->>APP: sealed entry written to SCITT
```

## 3. The refusal path

```mermaid
flowchart TD
    A["Claim arrives at caller<br/>'breathing signature lost, back bedroom'"] --> B{"Resolve ANSName<br/>via agent.webmesh.ai"}
    B -->|"does not resolve"| X1["DISCARD<br/>and say what was discarded"]
    B -->|resolves| C{"Certificate version<br/>matches registered code?"}
    C -->|"code drift detected"| X2["DISCARD<br/>and say what was discarded"]
    C -->|match| D{"Trust Index<br/>recommendedProfile"}
    D -->|UNTRUSTED| X3["DISCARD"]
    D -->|READ_ONLY| Y1["May inform context.<br/>May NOT trigger dispatch."]
    D -->|TRANSACTIONAL| Y2["May trigger dispatch"]
    D -->|FIDUCIARY| Y2
    Y2 --> E["caller speaks the claim to the operator"]
    E --> F["Seal into SCITT:<br/>identity, address, each claim, what the operator was told"]
    X1 --> G["Shown in the app as a refusal,<br/>with the reason"]
    X2 --> G
    X3 --> G

    classDef bad fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    classDef ok fill:#14532d,stroke:#4ade80,color:#fff
    class X1,X2,X3 bad
    class E,F ok
```

## 4. The iOS app flow

```mermaid
flowchart LR
    A["Launch"] --> B["Connect screen<br/>Bonjour _hawkeye._tcp"]
    B --> C{"Hub selected"}
    C --> D["GET /v1/hub<br/>verify identity + ANSName"]
    D -->|fails| B
    D -->|ok| E["Main screen"]

    E --> F["Live interior view<br/>presences rendered by confidence"]
    E --> G["Burglary / Fire<br/>manual raise"]
    E -.->|"WS /v1/stream"| H["Incident screen"]
    G --> H

    F --> F1["Moving + breathing<br/>= confirmed person"]
    F --> F2["Signature we had and<br/>no longer have<br/>= NO BREATHING SIGNATURE<br/>loudest thing on screen"]
    F --> F3["No respiration signature<br/>= unconfirmed presence"]

    H --> I["Live transcript of the 911 call"]
    H --> J["'What is happening' free text<br/>always visible"]
    H --> K["Instructions from caller"]
    H --> L["Verification feed<br/>including what was DISCARDED"]

    classDef alarm fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    class F2 alarm
```

## 5. Hardware topology

```mermaid
flowchart LR
    subgraph LEFT["One side of the room"]
      R["TP-Link Archer AX1450<br/>fixed channel, 80MHz, 802.11ac<br/>band steering OFF"]
    end
    subgraph MID["The sensed space"]
      H1["people"]
    end
    subgraph RIGHT["Opposite side of the room"]
      P["Raspberry Pi 4B<br/>WiFi in monitor mode<br/>NO station interface"]
    end

    R -.->|"RF path that gets perturbed"| H1
    H1 -.-> P
    P ==>|"Cat5 - mandatory, not a convenience"| R
    M["MacBook<br/>sudo ping -i 0.01 gateway"] -->|WiFi| R
    I["iPhone - Hawk Eye app"] -->|WiFi| R
    R --> BE["Backend + agents"]

    classDef wire stroke-width:4px
    class P wire
```
