#!/usr/bin/env python3
"""Visualize an offline 14-DOF trajectory in MuJoCo. No DDS or robot I/O."""

import argparse
import os
from pathlib import Path
import sys
import time

import mujoco
import mujoco.viewer
import numpy as np

from phase3.retarget import ARM_JOINTS


def main():
    if sys.platform == "darwin" and "MJPYTHON_BIN" not in os.environ:
        mjpython = Path(sys.executable).with_name("mjpython")
        if not mjpython.exists():
            raise RuntimeError("mjpython was not found next to the active Python interpreter")
        os.execv(str(mjpython), [str(mjpython), "-m", "phase3.view_trajectory", *sys.argv[1:]])

    project_root = Path(__file__).resolve().parents[1]
    default_model = project_root.parent / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
    parser = argparse.ArgumentParser(description="View a Phase 3 offline trajectory")
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--model", type=Path, default=default_model)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--full-session", action="store_true",
        help="include leading and trailing frames recorded without the dead-man")
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be positive")

    trajectory = np.load(args.trajectory)
    times = trajectory["client_time_ms"]
    arm_q = trajectory["arm_q"]
    if arm_q.ndim != 2 or arm_q.shape[1] != 14 or len(times) != len(arm_q):
        raise ValueError("invalid Phase 3 trajectory")
    if not args.full_session and "active" in trajectory:
        active_indices = np.flatnonzero(trajectory["active"])
        if len(active_indices) == 0:
            raise ValueError("trajectory has no active dead-man frames")
        first, last = int(active_indices[0]), int(active_indices[-1]) + 1
        times = times[first:last]
        arm_q = arm_q[first:last]

    model = mujoco.MjModel.from_xml_path(str(args.model))
    data = mujoco.MjData(model)
    indices = []
    for side in ("left", "right"):
        for name in ARM_JOINTS[side]:
            joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            indices.append(model.jnt_qposadr[joint])

    with mujoco.viewer.launch_passive(model, data) as viewer:
        for index, values in enumerate(arm_q):
            if not viewer.is_running():
                break
            data.qpos[indices] = values
            mujoco.mj_forward(model, data)
            viewer.sync()
            if index + 1 < len(times):
                delay = max(0.0, min(0.05, (times[index + 1] - times[index]) / 1000.0))
                time.sleep(delay / args.speed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
