"""Kinematic retargeting primitives. This module has no DDS or robot I/O."""

from dataclasses import dataclass
import math

import mujoco
import numpy as np


QUEST_TO_G1 = np.array([
    [0.0, 0.0, -1.0],  # Quest -Z forward -> G1 +X forward
    [-1.0, 0.0, 0.0],  # Quest +X right -> G1 -Y left
    [0.0, 1.0, 0.0],   # Quest +Y up -> G1 +Z up
])

ARM_JOINTS = {
    side: ["{}_{}_joint".format(side, name) for name in (
        "shoulder_pitch", "shoulder_roll", "shoulder_yaw", "elbow",
        "wrist_roll", "wrist_pitch", "wrist_yaw")]
    for side in ("left", "right")
}


def quat_xyzw_to_matrix(values):
    x, y, z, w = (float(value) for value in values)
    norm = math.sqrt(x*x + y*y + z*z + w*w)
    if norm < 1e-9:
        raise ValueError("zero quaternion")
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])


def scaled_rotation_matrix(rotation, scale):
    """Scale a rotation along its shortest axis-angle representation."""
    scale = float(scale)
    if scale < 0.0:
        raise ValueError("rotation scale must be non-negative")
    quaternion = np.empty(4)
    mujoco.mju_mat2Quat(quaternion, np.asarray(rotation).reshape(-1))
    if quaternion[0] < 0.0:
        quaternion *= -1.0
    half_angle = math.acos(float(np.clip(quaternion[0], -1.0, 1.0)))
    sine = math.sin(half_angle)
    if sine < 1e-9 or scale == 0.0:
        return np.eye(3)
    axis = quaternion[1:] / sine
    scaled_half_angle = scale * half_angle
    scaled_quaternion = np.concatenate((
        [math.cos(scaled_half_angle)], axis * math.sin(scaled_half_angle)))
    result = np.empty(9)
    mujoco.mju_quat2Mat(result, scaled_quaternion)
    return result.reshape(3, 3)


def tracked_pose(sample, side):
    controller = sample.get(side)
    if not isinstance(controller, dict):
        return None
    return controller.get("grip") or controller.get("ray")


def pose_components(pose):
    if not isinstance(pose, dict):
        raise ValueError("missing pose")
    position = np.asarray(pose.get("position"), dtype=float)
    orientation = pose.get("orientation")
    if position.shape != (3,) or orientation is None or not np.all(np.isfinite(position)):
        raise ValueError("invalid pose")
    return position, quat_xyzw_to_matrix(orientation)


def controller_in_head_frame(sample, side):
    head_position, head_rotation = pose_components(sample.get("head"))
    hand_position, hand_rotation = pose_components(tracked_pose(sample, side))
    return (
        head_rotation.T @ (hand_position - head_position),
        head_rotation.T @ hand_rotation,
    )


def deadman_pressed(sample, button_index=1):
    for side in ("left", "right"):
        controller = sample.get(side)
        buttons = controller.get("buttons") if isinstance(controller, dict) else None
        if not isinstance(buttons, list) or len(buttons) <= button_index:
            return False
        if not isinstance(buttons[button_index], dict) or buttons[button_index].get("pressed") is not True:
            return False
    return True


@dataclass
class Target:
    position: np.ndarray
    rotation: np.ndarray


class Calibration:
    def __init__(self, neutral_sample, neutral_targets, position_scale=0.25,
                 orientation_scale=0.35):
        self.position_scale = position_scale
        self.orientation_scale = orientation_scale
        self.quest_neutral = {
            side: controller_in_head_frame(neutral_sample, side)
            for side in ("left", "right")
        }
        self.robot_neutral = neutral_targets

    def target(self, sample, side):
        position, rotation = controller_in_head_frame(sample, side)
        neutral_position, neutral_rotation = self.quest_neutral[side]
        robot_neutral = self.robot_neutral[side]
        delta_position = QUEST_TO_G1 @ (position - neutral_position)
        delta_rotation = QUEST_TO_G1 @ (rotation @ neutral_rotation.T) @ QUEST_TO_G1.T
        delta_rotation = scaled_rotation_matrix(delta_rotation, self.orientation_scale)
        return Target(
            robot_neutral.position + self.position_scale * delta_position,
            delta_rotation @ robot_neutral.rotation,
        )


class G1Kinematics:
    def __init__(self, model_path):
        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, self.data)
        self.joints = {}
        self.qpos_indices = {}
        self.dof_indices = {}
        self.body_ids = {}
        self.ranges = {}
        for side in ("left", "right"):
            joint_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
                         for name in ARM_JOINTS[side]]
            if any(value < 0 for value in joint_ids):
                raise ValueError("G1 arm joints missing from model")
            self.joints[side] = joint_ids
            self.qpos_indices[side] = np.asarray(
                [self.model.jnt_qposadr[value] for value in joint_ids], dtype=int)
            self.dof_indices[side] = np.asarray(
                [self.model.jnt_dofadr[value] for value in joint_ids], dtype=int)
            self.ranges[side] = np.asarray([self.model.jnt_range[value] for value in joint_ids])
            body_name = "{}_wrist_yaw_link".format(side)
            self.body_ids[side] = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_BODY, body_name)

    def arm_q(self, side):
        return self.data.qpos[self.qpos_indices[side]].copy()

    def set_arm_q(self, side, values):
        self.data.qpos[self.qpos_indices[side]] = values
        mujoco.mj_forward(self.model, self.data)

    def body_target(self, side):
        body = self.body_ids[side]
        return Target(self.data.xpos[body].copy(), self.data.xmat[body].reshape(3, 3).copy())

    def neutral_targets(self):
        return {side: self.body_target(side) for side in ("left", "right")}

    def solve(self, side, target, initial=None, iterations=35, damping=0.04,
              orientation_weight=0.12):
        q = self.arm_q(side) if initial is None else np.asarray(initial, dtype=float).copy()
        ranges = self.ranges[side]
        margin = 0.03
        q = np.clip(q, ranges[:, 0] + margin, ranges[:, 1] - margin)
        body = self.body_ids[side]
        dofs = self.dof_indices[side]
        for _ in range(iterations):
            self.set_arm_q(side, q)
            position_error = target.position - self.data.xpos[body]
            current_quat = self.data.xquat[body].copy()
            target_quat = np.empty(4)
            mujoco.mju_mat2Quat(target_quat, target.rotation.reshape(-1))
            rotation_error = np.empty(3)
            mujoco.mju_subQuat(rotation_error, target_quat, current_quat)
            error = np.concatenate((position_error, orientation_weight * rotation_error))
            if np.linalg.norm(position_error) < 0.003 and np.linalg.norm(rotation_error) < 0.04:
                break
            jac_position = np.zeros((3, self.model.nv))
            jac_rotation = np.zeros((3, self.model.nv))
            mujoco.mj_jacBody(self.model, self.data, jac_position, jac_rotation, body)
            jacobian = np.vstack((
                jac_position[:, dofs], orientation_weight * jac_rotation[:, dofs]))
            singular_values = np.linalg.svd(jacobian, compute_uv=False)
            adaptive_damping = damping + max(0.0, 0.03 - singular_values[-1])
            system = jacobian @ jacobian.T + adaptive_damping**2 * np.eye(6)
            step = jacobian.T @ np.linalg.solve(system, error)
            step = np.clip(step, -0.12, 0.12)
            q = np.clip(q + step, ranges[:, 0] + margin, ranges[:, 1] - margin)
        self.set_arm_q(side, q)
        position_error = float(np.linalg.norm(target.position - self.data.xpos[body]))
        jac_position = np.zeros((3, self.model.nv))
        jac_rotation = np.zeros((3, self.model.nv))
        mujoco.mj_jacBody(self.model, self.data, jac_position, jac_rotation, body)
        final_jacobian = np.vstack((
            jac_position[:, dofs], orientation_weight * jac_rotation[:, dofs]))
        final_sigma = float(np.linalg.svd(final_jacobian, compute_uv=False)[-1])
        return q, position_error, final_sigma


class MotionFilter:
    def __init__(self, initial, max_velocity=1.0, max_acceleration=3.0, cutoff_hz=5.0):
        self.position = np.asarray(initial, dtype=float).copy()
        self.velocity = np.zeros_like(self.position)
        self.max_velocity = max_velocity
        self.max_acceleration = max_acceleration
        self.cutoff_hz = cutoff_hz

    def reset_velocity(self):
        self.velocity.fill(0.0)

    def update(self, desired, dt, lower, upper):
        dt = max(0.001, min(float(dt), 0.05))
        alpha = 1.0 - math.exp(-2.0 * math.pi * self.cutoff_hz * dt)
        filtered_goal = self.position + alpha * (np.asarray(desired) - self.position)
        desired_velocity = np.clip(
            (filtered_goal - self.position) / dt, -self.max_velocity, self.max_velocity)
        velocity_delta = np.clip(
            desired_velocity - self.velocity,
            -self.max_acceleration * dt,
            self.max_acceleration * dt,
        )
        self.velocity = np.clip(
            self.velocity + velocity_delta, -self.max_velocity, self.max_velocity)
        self.position = np.clip(self.position + self.velocity * dt, lower, upper)
        return self.position.copy()
