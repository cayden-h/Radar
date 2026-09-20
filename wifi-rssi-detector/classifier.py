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
    ):
        self.present_variance_ratio = present_variance_ratio
        self.active_motion_ratio = active_motion_ratio
        self.baseline_alpha = baseline_alpha
        self.epsilon = epsilon
        self.baseline_variance = initial_baseline_variance
        self.baseline_motion_energy = initial_baseline_motion_energy

    def classify(self, variance, motion_energy):
        variance_ratio = variance / max(self.baseline_variance, self.epsilon)
        motion_ratio = motion_energy / max(self.baseline_motion_energy, self.epsilon)

        if motion_ratio > self.active_motion_ratio:
            state = "active"
        elif variance_ratio > self.present_variance_ratio:
            state = "present-still"
        else:
            state = "absent"

        if state != "active":
            self.baseline_variance = (
                self.baseline_alpha * variance + (1 - self.baseline_alpha) * self.baseline_variance
            )
            self.baseline_motion_energy = (
                self.baseline_alpha * motion_energy + (1 - self.baseline_alpha) * self.baseline_motion_energy
            )

        return state
