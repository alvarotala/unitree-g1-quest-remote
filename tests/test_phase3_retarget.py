import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HAS_PHASE3 = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("mujoco"))
if HAS_PHASE3:
    import numpy as np
    from phase3.retarget import (
        MotionFilter, QUEST_TO_G1, G1Kinematics, scaled_rotation_matrix)
    from phase3.replay import replay


@unittest.skipUnless(HAS_PHASE3, "Phase 3 optional dependencies are not installed")
class Phase3Tests(unittest.TestCase):
    def test_quest_axes_map_to_g1_axes(self):
        np.testing.assert_allclose(QUEST_TO_G1 @ [0, 0, -1], [1, 0, 0])
        np.testing.assert_allclose(QUEST_TO_G1 @ [1, 0, 0], [0, -1, 0])
        np.testing.assert_allclose(QUEST_TO_G1 @ [0, 1, 0], [0, 0, 1])
        self.assertAlmostEqual(np.linalg.det(QUEST_TO_G1), 1.0)

    def test_filter_limits_velocity_and_acceleration(self):
        motion_filter = MotionFilter(np.zeros(2), max_velocity=1.0, max_acceleration=2.0)
        first = motion_filter.update(np.ones(2) * 10, 0.01, np.ones(2) * -20, np.ones(2) * 20)
        np.testing.assert_allclose(first, [0.0002, 0.0002], atol=1e-9)
        self.assertLessEqual(np.max(np.abs(motion_filter.velocity)), 0.02 + 1e-9)

    def test_rotation_scaling_uses_shortest_axis_angle(self):
        rotation_180_z = np.diag([-1.0, -1.0, 1.0])
        scaled = scaled_rotation_matrix(rotation_180_z, 0.25)
        angle = np.arccos(np.clip((np.trace(scaled) - 1.0) / 2.0, -1.0, 1.0))
        self.assertAlmostEqual(angle, np.pi / 4.0)

    def test_official_model_has_seven_dof_arms(self):
        root = Path(__file__).resolve().parents[2]
        model = root / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
        if not model.exists():
            self.skipTest("official unitree_mujoco checkout is absent")
        kinematics = G1Kinematics(model)
        self.assertEqual(len(kinematics.qpos_indices["left"]), 7)
        self.assertEqual(len(kinematics.qpos_indices["right"]), 7)
        self.assertEqual(kinematics.unsafe_collision_pairs(), set())

    def test_synthetic_log_runs_through_offline_replay(self):
        root = Path(__file__).resolve().parents[2]
        model = root / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
        if not model.exists():
            self.skipTest("official unitree_mujoco checkout is absent")

        def controller(position):
            pose = {"position": position, "orientation": [0, 0, 0, 1]}
            return {
                "grip": pose, "ray": pose,
                "buttons": [{"pressed": False}, {"pressed": True}], "axes": [0, 0],
            }

        samples = []
        for sequence in range(8):
            offset = 0.002 * sequence
            samples.append({
                "sequence": sequence,
                "clientTime": sequence * 11.1,
                "head": {"position": [0, 1.6, 0], "orientation": [0, 0, 0, 1]},
                "left": controller([-0.3 - offset, 1.3, -0.3]),
                "right": controller([0.3 + offset, 1.3, -0.3]),
            })
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "synthetic.ndjson"
            log.write_text(json.dumps({"sessionId": "synthetic", "samples": samples}) + "\n")
            report = replay(log, model)
        self.assertEqual(report["mode"], "OFFLINE_SIMULATION_ONLY")
        self.assertEqual(report["activeSamples"], len(samples))
        self.assertEqual(report["ikFailures"], 0)
        self.assertEqual(report["unsafeCollisionSamples"], 0)
        self.assertTrue(report["acceptedForSimulation"])

    def test_calibration_starts_at_first_valid_deadman_sample(self):
        root = Path(__file__).resolve().parents[2]
        model = root / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
        if not model.exists():
            self.skipTest("official unitree_mujoco checkout is absent")

        def sample(sequence, pressed):
            pose = {"position": [0, 1.3, -0.3], "orientation": [0, 0, 0, 1]}
            controller = {
                "grip": pose, "ray": pose,
                "buttons": [{"pressed": False}, {"pressed": pressed}], "axes": [],
            }
            return {
                "sequence": sequence, "clientTime": sequence * 11.1,
                "head": {"position": [0, 1.6, 0], "orientation": [0, 0, 0, 1]},
                "left": controller, "right": controller,
            }

        samples = [sample(0, False), sample(1, False), sample(2, True)]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calibration.ndjson"
            log.write_text(json.dumps({"sessionId": "calibration", "samples": samples}) + "\n")
            report = replay(log, model)
        self.assertEqual(report["calibrationSequence"], 2)


if __name__ == "__main__":
    unittest.main()
