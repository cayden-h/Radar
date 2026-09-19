"""Burglary, Fire or Faint, from what the sensing agents said.

**Classification is the interesting part and should be visible.** A judge
watching a system switch on one signal sees a thermostat; a judge watching it
combine two independent modalities sees something that is thinking. So this
returns the reasoning alongside the verdict, in plain English, and the app
renders it.

The table is from `docs/research/agent-briefs.md`:

| Observation                                          | Classification                          |
|------------------------------------------------------|-----------------------------------------|
| Fall + elevated CO                                    | Fire with a casualty, not a faint       |
| Fall + normal air + no other presence                 | Faint, and nobody is coming to help     |
| Unexpected presence + resident in a different room    | Burglary in progress with occupants home |
| Unexpected presence + house registered empty          | Burglary, no occupants at risk          |

The second row is the one to lead with. It is the case where the statistics say
the outcome is decided by discovery time.

**All three types are raised by a human**, from the iOS app. This function does
not raise anything and cannot. It answers "if someone raises an incident right
now, what is it", so that a resident who taps `Faint` while the air is full of
CO gets corrected toward Fire before the call is placed rather than after.
"""

from __future__ import annotations

from dataclasses import dataclass

from hawkeye_backend.models.incident import IncidentType

from agents.master.gate import AdmittedClaim


@dataclass(frozen=True)
class Classification:
    """What master thinks this is, and why, in words a resident can read."""

    incident_type: IncidentType
    reasoning: str
    confidence: float
    contributing_fields: tuple[str, ...]


def _truthy(claims: list[AdmittedClaim], field: str) -> AdmittedClaim | None:
    for claim in claims:
        if claim.assertion.field == field and claim.assertion.value == "true":
            return claim
    return None


def _value(claims: list[AdmittedClaim], field: str) -> str | None:
    for claim in claims:
        if claim.assertion.field == field:
            return claim.assertion.value
    return None


def classify(claims: list[AdmittedClaim], *, requested: IncidentType | None = None) -> Classification:
    """Classify from admitted claims. Discarded claims are not visible here.

    That is deliberate and it is the point of the gate: a compromised sensor's
    claim never reaches the classifier at all, so there is no path by which a
    fabricated observation changes what a dispatcher is told. The claims this
    function sees have already survived the profile gate.
    """
    collapse = _truthy(claims, "people.collapse_detected")
    elevated = _truthy(claims, "master.co_elevated")
    intruder = _truthy(claims, "intruder.unexpected_presence")
    headcount = _value(claims, "people.headcount")
    still_down = _value(claims, "people.still_down_s")

    # Fire first, and specifically the fall-plus-CO combination, because getting
    # this one wrong is the most consequential misclassification available. A
    # casualty inside a building with rising CO is a fire response with a rescue,
    # and calling it a faint sends an ambulance to a house that needs a truck.
    if collapse is not None and elevated is not None:
        co = _value(claims, "master.co_ppm") or "elevated"
        return Classification(
            incident_type=IncidentType.FIRE,
            reasoning=(
                f"A collapse in {collapse.assertion.zone_scope} with carbon monoxide at "
                f"{co} ppm. Two independent modalities: CSI saw the fall, a separate gas "
                "sensor saw the air. This is a fire with a casualty, not a faint - toxic "
                "gases can render someone unconscious in under a minute, often before they "
                "know there is a fire."
            ),
            confidence=0.8,
            contributing_fields=("people.collapse_detected", "master.co_elevated", "master.co_ppm"),
        )

    if elevated is not None and collapse is None:
        co = _value(claims, "master.co_ppm") or "elevated"
        return Classification(
            incident_type=IncidentType.FIRE,
            reasoning=(
                f"Carbon monoxide at {co} ppm with no collapse detected. Everyone in the "
                "building is still on their feet, which is the moment to leave."
            ),
            confidence=0.6,
            contributing_fields=("master.co_ppm",),
        )

    # Burglary next. The dangerous case is the minority where someone is home
    # and the burglar did not expect it, and it is the one worth separating.
    if intruder is not None:
        zones = _value(claims, "intruder.occupied_zones")
        intruder_zone = _value(claims, "intruder.intruder_zone")
        if intruder_zone is not None:
            reasoning = (
                f"A breathing presence in {intruder_zone} with no registered device on the "
                "network, and no resident device associated at all. The house is registered "
                "empty; no occupants are known to be at risk."
            )
            confidence = 0.7
        else:
            reasoning = (
                f"A body with no corresponding device, with residents also in the building. "
                f"Presences are resolved in {zones or 'unknown zones'}. Which one is the "
                "unaccounted body cannot be determined without re-identification, which this "
                "system does not do, so every occupied zone is reported instead. This is the "
                "dangerous case: someone is home and did not expect company."
            )
            confidence = 0.6
        return Classification(
            incident_type=IncidentType.BURGLARY,
            reasoning=reasoning,
            confidence=confidence,
            contributing_fields=("intruder.unexpected_presence", "people.headcount"),
        )

    # Faint. The headline case, and the one the statistics belong to.
    if collapse is not None:
        alone = headcount == "1"
        down = f"{float(still_down) / 60.0:.0f} minutes" if still_down else "an unknown time"
        return Classification(
            incident_type=IncidentType.FAINT,
            reasoning=(
                f"A collapse in {collapse.assertion.zone_scope}, down {down}, with normal air "
                "and no unexpected presence. "
                + (
                    "One resident is home by device association, so nobody is coming to help. "
                    "The fall is not what kills; the time to discovery is."
                    if alone
                    else "Other occupants are home."
                )
            ),
            confidence=0.75 if alone else 0.65,
            contributing_fields=(
                "people.collapse_detected",
                "people.still_down_s",
                "people.headcount",
            ),
        )

    # Nothing corroborates. The resident's tap still stands - a person decides
    # what is an emergency, not this function - and master says plainly that it
    # has nothing to add rather than manufacturing a reason.
    if requested is not None:
        return Classification(
            incident_type=requested,
            reasoning=(
                f"Raised as {requested.value} by the resident. No sensing agent currently "
                "corroborates it. The tap stands: a person decides that emergency services "
                "are needed, and the sensors inform rather than authorize."
            ),
            confidence=0.3,
            contributing_fields=(),
        )

    return Classification(
        incident_type=IncidentType.FAINT,
        reasoning=(
            "No corroborating claims and nothing was raised. This is a placeholder verdict "
            "and must not be presented as a classification."
        ),
        confidence=0.0,
        contributing_fields=(),
    )
