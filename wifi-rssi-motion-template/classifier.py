"""Ratio-based motion classifier against a slow-adapting baseline.

Binary: absent (no motion) / active (motion). An earlier three-state
version also had "present-still" (elevated variance, low motion energy --
someone sitting still), driven by a separate variance-ratio threshold. It
was dropped: it wasn't a reliably distinguishable state in practice, and a
detector this simple is more useful as a clean motion/no-motion signal than
as an unreliable occupancy sensor.
"""


class BaselineClassifier:
    def __init__(
        self,
        active_motion_ratio=4.0,
        baseline_alpha=0.02,
        epsilon=1e-6,
        initial_baseline_motion_energy=0.5,
        min_baseline_motion_energy=0.1,
        hysteresis_ticks=1,
    ):
        self.active_motion_ratio = active_motion_ratio
        self.baseline_alpha = baseline_alpha
        self.epsilon = epsilon
        self.min_baseline_motion_energy = min_baseline_motion_energy
        self.baseline_motion_energy = initial_baseline_motion_energy
        # hysteresis_ticks=1 (the default) confirms every raw classification
        # immediately -- identical to having no debounce at all, which keeps
        # every existing single-call test's behavior unchanged. A caller that
        # wants debounced output (a short analysis window reacts fast but
        # ticks noisily from sample to sample) passes a higher value so a new
        # state must repeat that many consecutive ticks before it's reported.
        self.hysteresis_ticks = max(1, hysteresis_ticks)
        self._confirmed_state = "absent"
        self._pending_state = None
        self._pending_count = 0

    def classify(self, variance, motion_energy):
        # `variance` is accepted for signature stability (callers already
        # compute it via extract_features, and it's still shown in the UI
        # as a diagnostic) but no longer drives classification.
        del variance

        # min_baseline_motion_energy is a physically-meaningful noise floor
        # (constant integer RSSI readings during a quiet room produce
        # exact-zero motion_energy, which would otherwise let the EMA
        # baseline collapse toward zero and turn epsilon into the
        # effective, hair-trigger divisor). epsilon remains only as the
        # true divide-by-zero guard.
        motion_divisor = max(self.baseline_motion_energy, self.min_baseline_motion_energy, self.epsilon)
        motion_ratio = motion_energy / motion_divisor

        raw_state = "active" if motion_ratio > self.active_motion_ratio else "absent"

        # Debounce: a new state must be seen hysteresis_ticks times in a row
        # (not necessarily consecutive calls agreeing with each other across
        # resets -- any raw reading that breaks the streak restarts the count)
        # before it's actually reported, so a single noisy tick on a short
        # window can't flip the badge on its own.
        if raw_state == self._confirmed_state:
            self._pending_state = None
            self._pending_count = 0
        else:
            if raw_state == self._pending_state:
                self._pending_count += 1
            else:
                self._pending_state = raw_state
                self._pending_count = 1
            if self._pending_count >= self.hysteresis_ticks:
                self._confirmed_state = raw_state
                self._pending_state = None
                self._pending_count = 0

        # Only freeze-and-drift the baseline while the *confirmed* (reported)
        # state reads as genuinely empty -- matches what a human would call
        # "the room is currently absent", not a single raw absent tick that
        # hasn't cleared the debounce yet.
        if self._confirmed_state == "absent":
            self.baseline_motion_energy = max(
                self.baseline_alpha * motion_energy + (1 - self.baseline_alpha) * self.baseline_motion_energy,
                self.min_baseline_motion_energy,
            )

        return self._confirmed_state
