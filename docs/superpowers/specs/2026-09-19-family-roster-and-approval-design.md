# Family roster and approval: telling the house who belongs here

Written 2026-09-19.

## The problem

`agents/intruder` decides that a confirmed person is unexpected by **roster plus device
association**: two registered residents, both resident phones associated to the network, and at
least one more presence than those devices account for.

That rule is written down in `agents/CLAUDE.md` and `docs/research/identity.md`.
It is not implemented anywhere, and there is no roster.
The roster in `master/scenario.py` is the roster of the nine agents, not of people.

The consequence is a failure in the wrong direction.
A resident whose phone has Wi-Fi off reads as **an unexpected person in their own home**, which
raises a notice and, once Twilio is configured, texts them about themselves.
A false intruder alert on the person who lives there is worse than a missed one, because it is the
alert that teaches someone to stop believing the system.

It also has no answer for the ordinary case of a guest.
A grandparent visiting every Sunday is an intruder every Sunday.

## What this is

Two capabilities that are easy to conflate and must not be:

**Approving a presence.** Session-scoped. "The person in the living room right now is fine."
Silences notices about that presence. Forgotten when the presence is.

**Remembering a visitor.** Permanent. "That was Grandma; her phone is now on the roster."
The next visit raises nothing at all, because the arithmetic accounts for her.

The first is a mute button. The second changes what the house believes.
A UI that offers one button for both would routinely persist a stranger because someone wanted the
banner to go away, so they are separate actions with separate words.

## The identifier, and why a phone is the only honest one

**CSI cannot recognise a person, ever.** `presence_id` is documented as stable within a session only
and the project must not claim re-identification. A body reflecting RF carries no identity.

So a persistent identifier has to be carried, and the only thing everyone already carries is a
phone. The mechanism is the router's association table.

The fact that makes this work, and that is widely got wrong: **iOS "Private Wi-Fi Address" is
randomised per network and then stable for that network.** It is on by default since iOS 14 and does
not re-randomise on each connection. Android 10+ behaves the same way. A guest who joins the home
Wi-Fi once presents the same address on that network on every later visit.

Three limits, stated here because the UI has to be honest about them rather than hide them:

- **Binding is an inference, not proof.** "The device that associated a moment ago" and "the presence
  I am approving" are correlated by timing. Two people arriving together can bind the wrong phone.
  The UI therefore shows what it is about to remember and makes the resident confirm it.
- **A guest who never joins the Wi-Fi can never be auto-recognised.** That is physics. They can still
  be named and approved per visit, and the system says so rather than pretending otherwise.
- **"Forget This Network" issues a new address.** A remembered guest who forgets the network reads as
  a stranger again. Rare, and it will look like a bug exactly once, so it is written down here.

### Identifiers are stored hashed

A roster is a list of which humans were in a building and which devices they carry. That is the kind
of file that should not be useful to whoever steals it.

Device identifiers are stored as `HMAC-SHA256(site_salt, mac)`, never in the clear. Matching an
observed device is hashing the observation and comparing, so nothing above the store changes. A
short display fingerprint (`a4:…:91`, first and last octet of the real address plus four hex of the
hash) is kept alongside for a human disambiguating two phones in the same room.

This costs about five lines and it is consistent with the rest of the service: the dispatch address
never travels in a claim, the Twilio token is a `SecretStr`, and provenance is computed rather than
asserted.

## Where it lives

**In the hub, `app/backend/hawkeye_backend/household/`, as a standalone package**, the way
`verification/` is standalone: no FastAPI imports, no hub imports, so it moves into `agents/intruder`
as an import change rather than a rewrite.

The hub is the only thing that runs today, so this is the only placement that is demoable this
weekend on both the mock and the live path.

**The surplus arithmetic stays in `agents/intruder` and is not built here.** The hub holds the roster
and answers "is this device known", which is the part the app needs and the part intruder will call.
Deciding `expected` from presences, roster and association table is intruder's job, and duplicating
it here would create two copies of the rule that decides whether someone is an intruder.

What the hub does own today is a **local suppression set**: a presence the resident has approved
raises no further notices, whatever the upstream `expected` says. That is a human override of a
machine inference, applied on the human side of the boundary, which is the right side for it.

## The app surface

**No settings screen, and no new stage.** `app/CLAUDE.md` says the app is not a dashboard and has no
settings, accounts, onboarding or history browser, and that rule is load-bearing: it is why the app
is usable by someone in the worst ten minutes of their year.

The roster is therefore reached through the thing that already interrupts you.

A notice gains two actions:

```
  Unexpected person
  Not accounted for. Living room. 2:19 PM

  [ This is expected ]   [ Remember this visitor ]   [ ✕ ]
```

- **This is expected** approves the presence. The banner goes, nothing persists.
- **Remember this visitor** opens a single sheet: a name field, the device it proposes to bind with
  its fingerprint, and a plain "no device" option for a guest who is not on the Wi-Fi. One
  confirmation, then it is on the roster.

A **Household** list is reachable from the home screen header. It is read-only plus delete: who is on
the roster, which devices each person has, and when each was last seen. No add button, because adding
happens by approving a real detection, which is both simpler and the only moment the system has a
device to bind.

For the judging table this is demoable on the mock path with no hardware: the scripted burglary
raises its notice, and the flow runs from there.

## Data model

`hawkeye_backend/models/household.py`:

```python
class MemberKind(StrEnum):
    RESIDENT = "resident"   # lives here, counted always
    GUEST = "guest"         # welcome, counted when present


class KnownDevice(BaseModel):
    device_id: str                  # our id, not theirs
    identifier_hash: str            # HMAC-SHA256(site_salt, observed address)
    fingerprint: str                # short, for a human telling two phones apart
    label: str | None = None        # "iPhone", typed by the resident
    added_at: datetime
    last_seen_at: datetime | None = None


class HouseholdMember(BaseModel):
    member_id: str
    name: str
    kind: MemberKind
    devices: list[KnownDevice] = []
    added_at: datetime
    # How this member came to be on the roster. A member added by approving a
    # live detection is a different kind of fact from one typed in during setup,
    # and the Household list says which.
    added_by: Literal["approval", "enrollment"]
```

A member with no devices is legal and meaningful: a named guest the system cannot auto-recognise.
The Household list renders that as "no device, will not be recognised automatically" rather than
leaving it blank, because the difference matters and is invisible otherwise.

## API

| Route | What it does |
|---|---|
| `GET /v1/household` | The roster. Members, devices, last seen. |
| `DELETE /v1/household/members/{member_id}` | Remove a member and their devices. |
| `GET /v1/household/unclaimed-devices` | Devices seen associated that no member claims, newest first. The candidates for a binding. |
| `POST /v1/presences/{presence_id}/approve` | Session-scoped. Suppresses notices for that presence. |
| `POST /v1/household/remember` | `{name, kind, device_id \| null}`. Creates a member and optionally binds a device. |

`POST /v1/household/remember` is deliberately one call rather than create-then-bind. The two halves
are meaningless apart, and a partial failure that leaves a named member with no device is exactly the
state that looks like a working roster and silently never recognises anyone.

### Where unclaimed devices come from

The hub does not talk to the router. `InteriorState` gains an optional list:

```python
associated_devices: list[ObservedDevice] = []
```

supplied by `master` from the router's association table, carrying `Provenance` like every other
reading. Absent on a frame, it means "not reported", never "nobody is here", and the app says
"no devices reported" rather than drawing an empty roster as fact.

The mock supplies it, so the whole flow runs with no hardware.

## Persistence: MongoDB Atlas

The roster must survive a restart. A roster enrolled at the venue and lost to a process restart is
worse than no roster, because the demo will have been rehearsed against a populated one.

`store.py` already carries `MongoStore` as an explicit seam with its own implementation note. This
spec implements it, which also serves the MongoDB Atlas sponsor track.

- Add `motor>=3.6` to `pyproject.toml`.
- `MongoStore` implements the existing `Store` protocol, one collection per method group, keyed by
  `incident_id` where there is one. `events` is capped at the same size as the in-memory deque.
- Two new collections, `household_members` and `known_devices`, behind two new `Store` methods.
- `HAWKEYE_STORE_BACKEND=mongodb` switches it. `memory` stays the default, so nothing breaks for
  anyone who does not set it, and the demo still runs with no network.

**`InMemoryStore` implements the roster methods too.** The mock path must not require Atlas, or the
judging demo acquires a network dependency it was specifically designed not to have.

The Atlas URI is already in `app/backend/.env` as `HAWKEYE_MONGODB_URI`. It contains a password, so
it stays out of every committed file, and `.env.example` carries a placeholder.

## Verification, and the boundary this sits on

A roster entry is a **human declaration**, not a sensed fact, and is labelled as one.

Its provenance is `Source.USER_INPUT`, which maps to `SourceClass.HUMAN`. It is never
`AGENT_INFERENCE` and never anything measured. When `caller` speaks to a dispatcher, "the resident
says this person is expected" is honest and "the system verified this person" is not, and the type
system is what keeps those apart.

Every roster change is sealed into `agents/replay` with who made it and when, for the same reason
the incident is: the decision that a stranger was welcome is exactly the decision an investigator
would want afterwards.

**This is a human override of a machine inference, and that direction is the safe one.** The resident
can tell the house that someone is fine. Nothing in this design lets the house decide on its own that
a stranger is fine, and nothing lets a roster entry raise an alarm. It can only ever lower one.

## Testing

- The identifier hash is stable for the same address and salt, and differs across sites. A leaked
  roster from one house does not identify devices in another.
- A remembered device suppresses the notice on a later visit; an unremembered one does not.
- Approving a presence suppresses notices for that presence and no other, including a second
  unexpected presence in the same frame.
- Approval does not persist: a new session with the same `presence_id` is not pre-approved.
- A member created with `device_id: null` is stored, surfaces in the roster, and never matches an
  observed device.
- `remember` is atomic: a failure binding the device leaves no half-created member.
- `InMemoryStore` and `MongoStore` pass the same roster test suite, so the seam is real rather than
  asserted.
- The mock path runs the whole flow with no Atlas and no hardware.

## Honesty rule

- **Real:** the roster, the approval, the hashing, the persistence, the provenance labelling, and
  the fact that a human decision is recorded as a human decision.
- **Not implemented here:** the surplus arithmetic that decides `expected`, which stays in
  `agents/intruder`. The hub answers "is this device known" and holds the resident's overrides.
- **Simulated on the demo path:** `associated_devices` comes from the mock rather than a real
  association table, because no router integration exists yet. It carries `Provenance` saying so,
  and swapping in the real table is a producer change behind a field that already exists.

## What this deliberately does not do

- **No schedules.** "Expect someone Tuesdays 2 to 4" is the right answer for a cleaner who never
  joins the Wi-Fi, and it is a separate feature with its own recurrence and timezone edges.
- **No face, voice or gait recognition.** The radio cannot do it and the project must not imply it.
- **No automatic enrolment.** A device is never remembered without a human naming it. A house that
  silently learns who is allowed in is a house that can be taught to allow the wrong person.
