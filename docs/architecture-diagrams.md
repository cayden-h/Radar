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
    P -->|"Channel State Information"| OCC
    P --> INT
    P --> BIO
    P --> COL
    G --> ENV

    subgraph SENSE["Sensing agents - CSI consumers"]
      OCC["occupancy<br/>count and location"]
      INT["intruder<br/>unexpected presence"]
      BIO["biometrics<br/>heart rate, breathing"]
      COL["collapse<br/>faint, fall"]
    end

    subgraph SENSE2["Independent modality"]
      ENV["environment<br/>CO, smoke"]
    end

    OCC -->|ANS| MA
    INT -->|ANS| MA
    BIO -->|ANS| MA
    COL -->|ANS| MA
    ENV -->|ANS| MA

    MA["master<br/>trust boundary<br/>classifies Burglary / Fire / Faint"]

    MA -->|ANS| CA["caller"]
    MA -->|ANS| GU["guidance"]
    MA -->|ANS| RE["replay"]

    CA ==>|"plain English voice - NO ANS"| OP(["911 operator<br/>a person"])
    GU ==>|"plain English - NO ANS"| US(["Resident<br/>iOS app"])
    RE --> LOG[("SCITT transparency log<br/>sealed, append only")]

    classDef human fill:#7a1f1f,stroke:#ff6b6b,color:#fff
    classDef sim fill:#5a4a00,stroke:#e0c000,color:#fff
    class OP,US human
    class G sim
```

## 2. The faint path - detection, alert, human tap, call

**Corrected 2026-09-19.** The version that sat in Notion until then went straight from `master` to
`caller` to the operator with no human in between. That contradicted the settled decision, the root
`CLAUDE.md`, and the shipped code, where `assert_human_released()` raises `AutonomousDialRefused`
on exactly that path.

The detection is autonomous. **The call is not.**

```mermaid
sequenceDiagram
    autonumber
    participant P as Pi / CSI
    participant COL as collapse
    participant BIO as biometrics
    participant MA as master
    participant APP as Resident app
    participant CA as caller
    participant OP as 911 operator

    P->>COL: fall transient
    P->>BIO: respiration signature
    COL->>MA: claim: occupant down, no movement 90s
    BIO->>MA: claim: breathing 11/min, still
    MA->>MA: verify ANSName + version-bound cert per claim
    MA->>MA: classify FAINT
    MA->>APP: ALERT - someone is down in the back bedroom

    Note over MA,CA: Hawk Eye does not dial on its own.<br/>A human tap is what releases caller.

    APP->>MA: resident taps Faint
    MA->>CA: released to dial, verified claims only
    CA->>CA: re-verify every source before speaking
    CA->>OP: "Unresponsive adult, back bedroom, 14 Oak Street."
    MA->>APP: transcript line + instruction
    OP->>CA: "Is the person still breathing?"
    CA->>MA: live query - not cached
    MA->>BIO: ANS-verified query
    BIO-->>MA: 11 breaths per minute
    MA-->>CA: verified answer
    CA->>OP: "Yes. Eleven breaths a minute."
    MA->>APP: instruction: do not move them
    MA->>APP: sealed entry written to SCITT
```

## 3. The refusal path

```mermaid
flowchart TD
    A["Claim arrives at caller<br/>'child unresponsive, back bedroom'"] --> B{"Resolve ANSName<br/>via agent.webmesh.ai"}
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
    E --> G["Burglary / Fire / Faint<br/>manual raise"]
    E -.->|"WS /v1/stream"| H["Incident screen"]
    G --> H

    F --> F1["Moving + breathing<br/>= confirmed person"]
    F --> F2["Still + breathing<br/>= NOT RESPONDING<br/>loudest thing on screen"]
    F --> F3["No respiration signature<br/>= unconfirmed presence"]

    H --> I["Live transcript of the 911 call"]
    H --> J["'What is happening' free text<br/>always visible"]
    H --> K["Instructions from guidance"]
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
