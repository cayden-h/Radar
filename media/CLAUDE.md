# media/

The demo video, plus the cinematic layer: Blender hero loop, pitch deck opener, Devpost thumbnail.

Read the root `CLAUDE.md` first.

## Two demos, and they show different things

We are doing both a recorded video and a live demo at judging. They carry different claims, and confusing them is how the live one fails.

**The video, shot at home, carries the physical claims.** Live CSI, real walls, real calibration, a real person in a real bedroom whose breathing signature goes missing. This is the only place the sensing layer can honestly be shown.

**The live demo at the venue carries the ANS claims.** The agents are hosted on Vultr and internet-reachable, so the entire GoDaddy submission runs from a laptop with no hardware dependency at all.

**Full sensing cannot be demoed at the venue**, and the reason is not the calibration step, which no longer exists. It is that counting and localization need a baseline at all:

- A baseline captured in a hall **decays as the hall fills**, because bodies are reflectors and the static multipath structure it described stops existing.
- **Occupancy assumes a bounded space.** An open hall has no wall defining who is inside.
- The band is saturated and everything in the room is moving.

Motion and breathing need no baseline, which is why those are the parts that do survive a judging table. Do not attempt or promise the rest.

See `agents/CLAUDE.md` for what the live demo runs. The video is the rest.

Treat this as a feature rather than a concession. It buys retakes, real calibration conditions, a real router, real rooms with walls to see through, and no dependency on a network we do not control.
It also means the thing judges see is the best version of the run rather than whichever one happened at 9am.

### What it has to show

Follow the demo sequence in `agents/CLAUDE.md`. In order:

1. **The lost breathing signature.** Open here, silent. `people` had a signature in the bedroom and no longer does, and the clock starts from the last resolvable frame. The app raises an alert; no call is placed.
   **Do not stage a fall and do not let the edit imply one.** Fall detection was cut on 2026-09-19 and the system does not detect one. The subject lies down and goes still; the claim on screen is about breathing, not about falling.
2. **A hand reaches for the phone and taps Fire.** Hawk Eye does not call 911 by itself, and the video should make that unmistakable rather than leaving it to the voiceover.
3. Sensing agents corroborating, on screen, with confidence.
   **Do not put an exact sensed headcount on screen.** A 1x1 link cannot deliver it, and a judge who knows RF will ask. Show one resolved presence plus a roster-sourced "2 residents registered, both devices present". Counting limits are under `agents/people`.
   If two people must appear in frame, stage them in opposite corners or either side of a wall with one moving. Two people within a metre of each other read as one.
4. `master` classifying and verifying, showing what it discarded.
5. The call. Real ElevenLabs voice, a real conversation.
6. The resident's phone: live transcript, the "what is happening" box, instructions arriving.
7. **The operator asks a follow-up and the question fans out into ANS-verified queries.** Show this fan-out. It is the architecture in one animation.
   Then show **TAKE OVER** being tapped and the agent falling silent mid-sentence. Five seconds, and it defuses the biggest objection anyone has to this project.
   If the burglary path gets screen time, show **whisper mode**: the resident speaks and the phone makes no sound at all.
8. **The refusal.** A compromised sensing agent, driven by `fraud.webmesh.ai`, and the system declining to escalate on its claims.

Step 8 is the submission. Do not let the video run long before reaching it.

For step 7, shoot `underpay_valid_sig`: a genuinely valid signature that the system still refuses.
It reads on camera better than a corrupted message does, because the audience can see that nothing looks wrong and the system refuses anyway.
The on-screen line is the discard log, not a red X.
Per-probe translations and the reasoning are in `docs/fraud-13.md`.

### B-roll

**Sourcing and licensing rules: `docs/research/footage.md`. Read it before pulling a single clip.**
A copyright strike on the Devpost video is an unrecoverable failure on submission day.

Short version: NIST fire research footage is US federal and therefore public domain, credit requested. UL FSRI is a private nonprofit and is not. Firefighter bodycam off YouTube is not. Never use footage showing an identifiable real victim.

**The one clip worth hunting for:** NIST's legacy-versus-modern furnishing comparison, showing a room become unsurvivable in under three minutes. It is the visual proof of the claim the whole Fire path rests on, and it does more work than any amount of generic flame B-roll.

Keep external B-roll to a handful of seconds. It exists to make the stakes legible in the first fifteen seconds, then get out of the way of what we built.

### Production notes

- **Keep it under three minutes.** Judges have many to watch. Two is better.
- Show the house. The through-wall claim only lands if the viewer can see there is a wall.
- Screen-record the agent console separately and cut it in. Do not film a laptop screen.
- Subtitle the ElevenLabs call. Phone audio is unreliable and the dialogue is the substance.
- **Say what is simulated, in the video, out loud.** `environment` reads a simulated sensor. See the honesty rule in the root `CLAUDE.md`. Disclosing it on camera reads as confidence; being caught reads as fabrication.
- Record the raw footage early. Editing is compressible, filming is not, and the Pi may stop cooperating.

### Hard dependency

The video cannot be made until the system runs end to end at the house.
That makes **fixing the broken deployment** the blocking item for the video as well as for everything else.

### Calibration on camera

There is no 30-second calibration ritual any more; the design is a rolling baseline with slow adaptation. See `sensor/CLAUDE.md`.

Two consequences for filming:

- **Let it run for several minutes before the take.** The baseline improves with time rather than being captured in one window, so power the system up well before you shoot.
- **Do not have the subject hold still during baseline warmup and then start the scene.** A person stationary for minutes risks being absorbed. Move normally, then lie down and go still for the take.

### Capture the replay session while you are there

While filming, record a clean CSI session and keep it. It becomes the input for the live venue demo, and it is fallback ladder level 2 in `sensor/CLAUDE.md`.
Downstream agents cannot tell replayed CSI from live, which is exactly why the venue demo works at all.

## The cinematic layer

Separate artifact, separate purpose: the Devpost page, the deck opener, the thumbnail.

## Scope boundary

**Blender is for the cinematic layer only.**
The live app's 3D occupancy view is pure Three.js / react-three-fiber, procedural, driven by live data. It lives in `app/`.
Do not round-trip simple dynamic primitives through Blender.

Blender's job is the 4-6 second loop that plays before anyone sees the real thing. The demo video is the real thing; this is the title card.

## The subject

Human presences resolving out of RF noise inside a dark house.

This is the right subject for three reasons.
It is the product thesis in one image.
It is geometric and procedural, which is where headless `bpy` is strong.
And it avoids organic sculpting, which is where it is not.

Direction: start in near-total noise, let structure emerge, resolve to three distinct presences and a room.
The emotional beat is "something in the dark becomes legible."
Do not render firefighters, flames, or anything literal. The restraint is what makes it look like a real product.

## Workflow

Claude-driven via headless `bpy` scripts, with a human directing the look.

```
blender --background --python script.py
```

- **Eevee Next while iterating.** Fast feedback matters more than accuracy during look development.
- **Cycles for the final pass**, with denoising on.
- 1080p, 4-6 seconds. Longer loops cost render time and nobody watches past six seconds.

Keep scripts in this folder and keep them re-runnable.
A hand-tweaked `.blend` nobody can regenerate is a liability at 3am.

## Vultr

Consider rendering the final Cycles pass on a Vultr GPU instance.

This is a materially more defensible Vultr track claim than hosting a web server there, and the agents already need hosting somewhere regardless.
Doing both makes the claim stronger still.

## Local environment

- Blender 5.2.1 LTS at `/opt/homebrew/bin/blender` and `/Applications/Blender.app`
- Apple M2 Pro, Metal 4

Metal handles Eevee iteration comfortably.
The final Cycles pass is where offloading to Vultr earns its keep.

## Deliverables

1. Hero loop, 4-6s, 1080p, for the Devpost page.
2. Pitch deck opener. Can be the same loop.
3. Devpost thumbnail. A single strong frame pulled from the loop.

## Timing and priority

Order of importance, when time runs short:

1. **The demo video.** Without it there is nothing to judge. Non-negotiable.
2. The Devpost thumbnail. A single strong frame.
3. The Blender hero loop. First thing to cut.

The hero loop is also the first thing judges see, so resolve that tension by making it early and making it short.
A rough loop finished Saturday afternoon beats a beautiful one that does not exist Sunday morning.

Neither of these is worth one hour taken from the deployment.
