#!/usr/bin/env python3
"""Replay Quest NDJSON through offline G1 IK. Never imports SDK2 or DDS."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from phase3.retarget import (
    Calibration, G1Kinematics, MotionFilter, controller_in_head_frame,
    deadman_pressed, tracked_pose,
)


def load_samples(path):
    samples = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if isinstance(record, dict) and isinstance(record.get("samples"), list):
                samples.extend(value for value in record["samples"] if isinstance(value, dict))
    return samples


def valid_tracking(sample):
    if sample.get("head") is None:
        return False
    return all(tracked_pose(sample, side) is not None for side in ("left", "right"))


def replay(log_path, model_path, allow_without_deadman=False, position_scale=0.25,
           watchdog_ms=100.0, trajectory_path=None, orientation_scale=0.35):
    samples = load_samples(log_path)
    neutral_sample = next((
        sample for sample in samples
        if valid_tracking(sample) and
        (allow_without_deadman or deadman_pressed(sample))), None)
    if neutral_sample is None:
        raise ValueError(
            "no sample has valid head, both controllers and the required dead-man")

    kinematics = G1Kinematics(model_path)
    calibration = Calibration(
        neutral_sample, kinematics.neutral_targets(), position_scale, orientation_scale)
    filters = {
        side: MotionFilter(kinematics.arm_q(side)) for side in ("left", "right")
    }
    report = {
        "mode": "OFFLINE_SIMULATION_ONLY",
        "samples": len(samples),
        "calibrationSequence": neutral_sample.get("sequence"),
        "positionScale": position_scale,
        "orientationScale": orientation_scale,
        "activeSamples": 0,
        "disarmedSamples": 0,
        "trackingInvalidSamples": 0,
        "watchdogTrips": 0,
        "ikFailures": 0,
        "singularityWarnings": 0,
        "collisionAvoidanceSamples": 0,
        "unsafeCollisionSamples": 0,
        "minimumBodyClearanceMeters": kinematics.collision_margin,
        "maxPositionErrorMeters": 0.0,
        "maxJointVelocityRadS": 0.0,
    }
    previous_time = None
    trajectory_times = []
    trajectory_q = []
    trajectory_active = []
    needs_deadman_release = False
    was_active = False
    position_errors = []
    for sample in samples:
        client_time = float(sample.get("clientTime", 0.0))
        dt = 1.0 / 90.0 if previous_time is None else max(0.0, (client_time - previous_time) / 1000.0)
        previous_time = client_time
        tracking = valid_tracking(sample)
        deadman = allow_without_deadman or deadman_pressed(sample)
        watchdog = dt * 1000.0 > watchdog_ms
        if watchdog:
            report["watchdogTrips"] += 1
            needs_deadman_release = not allow_without_deadman
        if not tracking:
            report["trackingInvalidSamples"] += 1
            needs_deadman_release = needs_deadman_release or was_active
        if not deadman:
            needs_deadman_release = False
        active = tracking and deadman and not watchdog and not needs_deadman_release
        if not active:
            report["disarmedSamples"] += 1
            was_active = False
            for motion_filter in filters.values():
                motion_filter.reset_velocity()
            trajectory_times.append(client_time)
            trajectory_q.append(np.concatenate(
                [filters[side].position for side in ("left", "right")]))
            trajectory_active.append(False)
            continue
        report["activeSamples"] += 1
        was_active = True
        avoided_collision = False
        for side in ("left", "right"):
            try:
                target = calibration.target(sample, side)
                current = filters[side].position
                desired, error, sigma = kinematics.solve(side, target, current)
                ranges = kinematics.ranges[side]
                previous = filters[side].position.copy()
                filtered = filters[side].update(
                    desired, dt, ranges[:, 0] + 0.03, ranges[:, 1] - 0.03)
                filtered, avoided = kinematics.collision_safe_step(
                    side, previous, filtered)
                avoided_collision = avoided_collision or avoided
                filters[side].position = filtered
                filters[side].velocity = (filtered - previous) / max(dt, 0.001)
                velocity = np.max(np.abs(filtered - previous)) / max(dt, 0.001)
                report["maxJointVelocityRadS"] = max(report["maxJointVelocityRadS"], float(velocity))
                report["maxPositionErrorMeters"] = max(report["maxPositionErrorMeters"], error)
                position_errors.append(error)
                if sigma < 0.015:
                    report["singularityWarnings"] += 1
                kinematics.set_arm_q(side, filtered)
            except (ValueError, np.linalg.LinAlgError):
                report["ikFailures"] += 1
                was_active = False
                break
        if avoided_collision:
            report["collisionAvoidanceSamples"] += 1
        if kinematics.unsafe_collision_pairs():
            report["unsafeCollisionSamples"] += 1
        trajectory_times.append(client_time)
        trajectory_q.append(np.concatenate(
            [filters[side].position for side in ("left", "right")]))
        trajectory_active.append(True)
    report["acceptedForSimulation"] = (
        report["activeSamples"] > 0 and report["ikFailures"] == 0 and
        report["maxPositionErrorMeters"] <= 0.08 and
        report["unsafeCollisionSamples"] == 0)
    report["positionErrorP95Meters"] = (
        float(np.percentile(position_errors, 95)) if position_errors else None)
    if trajectory_path is not None:
        np.savez_compressed(
            trajectory_path,
            client_time_ms=np.asarray(trajectory_times),
            arm_q=np.asarray(trajectory_q),
            active=np.asarray(trajectory_active, dtype=bool),
        )
        report["trajectory"] = str(trajectory_path)
    return report


def main():
    project_root = Path(__file__).resolve().parents[1]
    default_model = project_root.parent / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
    parser = argparse.ArgumentParser(description="Offline Quest-to-G1 retargeting replay")
    parser.add_argument("log", type=Path)
    parser.add_argument("--model", type=Path, default=default_model)
    parser.add_argument("--position-scale", type=float, default=0.25)
    parser.add_argument(
        "--orientation-scale", type=float, default=0.35,
        help="fraction of controller rotation applied to the G1 wrist")
    parser.add_argument("--watchdog-ms", type=float, default=100.0)
    parser.add_argument(
        "--simulation-ignore-deadman", action="store_true",
        help="allow replay without both grip buttons; simulation only")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trajectory", type=Path, help="write a 14-DOF offline .npz trajectory")
    args = parser.parse_args()
    report = replay(
        args.log, args.model,
        allow_without_deadman=args.simulation_ignore_deadman,
        position_scale=args.position_scale,
        watchdog_ms=args.watchdog_ms,
        trajectory_path=args.trajectory,
        orientation_scale=args.orientation_scale)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["acceptedForSimulation"] else 1


if __name__ == "__main__":
    sys.exit(main())
