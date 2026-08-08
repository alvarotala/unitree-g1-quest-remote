#include "g1_quest/diagnostic.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace g1_quest {

const std::array<const char*, kJointCount> kJointNames = {
    "left_hip_pitch", "left_hip_roll", "left_hip_yaw", "left_knee",
    "left_ankle_pitch", "left_ankle_roll", "right_hip_pitch",
    "right_hip_roll", "right_hip_yaw", "right_knee", "right_ankle_pitch",
    "right_ankle_roll", "waist_yaw", "waist_roll", "waist_pitch",
    "left_shoulder_pitch", "left_shoulder_roll", "left_shoulder_yaw",
    "left_elbow", "left_wrist_roll", "left_wrist_pitch", "left_wrist_yaw",
    "right_shoulder_pitch", "right_shoulder_roll", "right_shoulder_yaw",
    "right_elbow", "right_wrist_roll", "right_wrist_pitch", "right_wrist_yaw"};

const std::array<std::size_t, 6> kOptional29DofIndices = {13, 14, 20, 21, 27, 28};

bool HasTelemetry(const MotorTelemetry& motor) {
  const std::array<double, 9> values = {
      static_cast<double>(motor.mode), motor.q, motor.dq, motor.ddq,
      motor.tau_est, motor.voltage, static_cast<double>(motor.motor_state),
      static_cast<double>(motor.temperature[0]),
      static_cast<double>(motor.temperature[1])};
  if (std::any_of(values.begin(), values.end(), [](double value) {
        return std::isfinite(value) && std::abs(value) > 1e-8;
      })) return true;
  return motor.sensor[0] != 0 || motor.sensor[1] != 0;
}

bool HasFiniteValues(const MotorTelemetry& motor) {
  return std::isfinite(motor.q) && std::isfinite(motor.dq) &&
         std::isfinite(motor.ddq) && std::isfinite(motor.tau_est) &&
         std::isfinite(motor.voltage);
}

VariantEvidence Classify29Dof(
    const std::array<MotorTelemetry, kDdsMotorSlots>& motors,
    std::vector<std::size_t>& detected_indices) {
  detected_indices.clear();
  for (const auto index : kOptional29DofIndices) {
    if (HasTelemetry(motors[index])) detected_indices.push_back(index);
  }
  if (detected_indices.size() == kOptional29DofIndices.size())
    return VariantEvidence::Confirmed29Dof;
  if (!detected_indices.empty()) return VariantEvidence::Partial29Dof;
  return VariantEvidence::Inconclusive;
}

const char* VariantEvidenceText(VariantEvidence evidence) {
  switch (evidence) {
    case VariantEvidence::Confirmed29Dof:
      return "CONFIRMADO: telemetria consistente con G1 de 29 DOF";
    case VariantEvidence::Partial29Dof:
      return "PARCIAL: algunas articulaciones opcionales tienen senal";
    case VariantEvidence::Inconclusive:
      return "INCONCLUSO: articulaciones opcionales sin senal";
  }
  return "INCONCLUSO";
}

std::vector<std::size_t> JointIndices(const std::string& selection) {
  if (selection == "none") return {};
  if (selection == "optional")
    return {kOptional29DofIndices.begin(), kOptional29DofIndices.end()};
  std::vector<std::size_t> result;
  if (selection == "arms") {
    for (std::size_t index = 15; index < kJointCount; ++index) result.push_back(index);
    return result;
  }
  if (selection != "all")
    throw std::invalid_argument("seleccion desconocida: " + selection);
  for (std::size_t index = 0; index < kJointCount; ++index) result.push_back(index);
  return result;
}

}  // namespace g1_quest

