import math
import unittest

import g1_readonly_diagnostic as diagnostic


class FakeMotor:
    def __init__(self, active=True, q=0.1):
        self.mode = 1 if active else 0
        self.q = q if active else 0.0
        self.dq = 0.0
        self.ddq = 0.0
        self.tau_est = 0.0
        self.temperature = [31, 32] if active else [0, 0]
        self.vol = 48.0 if active else 0.0
        self.sensor = [0, 0]
        self.motorstate = 0


class FakeImu:
    quaternion = [1.0, 0.0, 0.0, 0.0]
    gyroscope = [0.1, 0.2, 0.3]
    accelerometer = [0.0, 0.0, 9.81]
    rpy = [0.1, -0.2, 0.3]
    temperature = 35


class FakeLowState:
    def __init__(self, motors):
        self.mode_pr = 0
        self.mode_machine = 5
        self.tick = 1234
        self.imu_state = FakeImu()
        self.motor_state = motors


class DiagnosticTests(unittest.TestCase):
    def test_joint_layout_is_29_dof(self):
        self.assertEqual(len(diagnostic.JOINT_NAMES), 29)
        self.assertEqual(
            diagnostic.OPTIONAL_29_DOF_INDICES,
            (13, 14, 20, 21, 27, 28),
        )

    def test_classifies_active_optional_joints_as_29_dof(self):
        motors = [FakeMotor(active=True) for _ in range(35)]
        result, detected = diagnostic.classify_29_dof(motors)
        self.assertIn("CONFIRMADO", result)
        self.assertEqual(detected, list(diagnostic.OPTIONAL_29_DOF_INDICES))

    def test_does_not_confirm_zero_placeholder_slots(self):
        motors = [FakeMotor(active=True) for _ in range(35)]
        for index in diagnostic.OPTIONAL_29_DOF_INDICES:
            motors[index] = FakeMotor(active=False)
        result, detected = diagnostic.classify_29_dof(motors)
        self.assertIn("INCONCLUSO", result)
        self.assertEqual(detected, [])

    def test_build_report_extracts_imu_and_motor_health(self):
        message = FakeLowState([FakeMotor(active=True) for _ in range(35)])
        snapshot = diagnostic.ReceiveSnapshot(
            message_count=500,
            elapsed_s=1.0,
            rate_hz=499.0,
            latest=message,
            last_age_s=0.01,
        )
        report = diagnostic.build_report(message, snapshot)
        self.assertEqual(report["motor_slots"], 35)
        self.assertEqual(report["mode_machine"], 5)
        self.assertEqual(report["imu_accel_m_s2"], [0.0, 0.0, 9.81])
        self.assertEqual(report["nonfinite_joint_indices"], [])

    def test_nonfinite_joint_value_is_reported(self):
        motors = [FakeMotor(active=True) for _ in range(35)]
        motors[18].q = math.nan
        message = FakeLowState(motors)
        snapshot = diagnostic.ReceiveSnapshot(1, 0.0, 0.0, message, 0.0)
        report = diagnostic.build_report(message, snapshot)
        self.assertEqual(report["nonfinite_joint_indices"], [18])


if __name__ == "__main__":
    unittest.main()
