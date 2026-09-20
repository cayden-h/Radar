"""Ratio-based motion/presence classifier against a slow-adapting baseline."""


class BaselineClassifier:
    def __init__(
        self,
        present_variance_ratio=3.0,
        active_motion_ratio=4.0,
        baseline_alpha=0.02,
        epsilon=1e-6,
        initial_baseline_variance=0.5,
        initial_baseline_motion_energy=0.5,
        min_baseline_variance=0.1,
        min_baseline_motion_energy=0.1,
    ):
        self.present_variance_ratio = present_variance_ratio
        self.active_motion_ratio = active_motion_ratio
        self.baseline_alpha = baseline_alpha
        self.epsilon = epsilon
        self.min_baseline_variance = min_baseline_variance
        self.min_baseline_motion_energy = min_baseline_motion_energy
        self.baseline_variance = initial_baseline_variance
        self.baseline_motion_energy = initial_baseline_motion_energy

    def classify(self, variance, motion_energy):
        # min_baseline_* is a physically-meaningful noise floor (constant integer
        # RSSI readings during a quiet room produce exact-zero variance/motion,
        # which would otherwise let the EMA baseline collapse toward zero and
        # turn epsilon into the effective, hair-trigger divisor). epsilon remains
        # only as the true divide-by-zero guard.
        variance_divisor = max(self.baseline_variance, self.min_baseline_variance, self.epsilon)
        motion_divisor = max(self.baseline_motion_energy, self.min_baseline_motion_energy, self.epsilon)

        variance_ratio = variance / variance_divisor
        motion_ratio = motion_energy / motion_divisor

        if motion_ratio > self.active_motion_ratio:
            state = "active"
        elif variance_ratio > self.present_variance_ratio:
            state = "present-still"
        else:
            state = "absent"

        # Only freeze-and-drift the baseline while the room reads as genuinely
        # empty. Freezing it on "active" alone let a present-still tick keep
        # dragging the baseline toward itself, decaying present-still back to
        # absent within a few seconds.
        if state == "absent":
            self.baseline_variance = max(
                self.baseline_alpha * variance + (1 - self.baseline_alpha) * self.baseline_variance,
                self.min_baseline_variance,
            )
            self.baseline_motion_energy = max(
                self.baseline_alpha * motion_energy + (1 - self.baseline_alpha) * self.baseline_motion_energy,
                self.min_baseline_motion_energy,
            )

        return state
