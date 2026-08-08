#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace g1_quest {

constexpr std::size_t kJointCount = 29;
constexpr std::size_t kDdsMotorSlots = 35;
extern const std::array<const char*, kJointCount> kJointNames;
extern const std::array<std::size_t, 6> kOptional29DofIndices;

struct MotorTelemetry {
  std::uint8_t mode = 0;
  float q = 0.0F;
  float dq = 0.0F;
  float ddq = 0.0F;
  float tau_est = 0.0F;
  std::array<std::int16_t, 2> temperature{};
  float voltage = 0.0F;
  std::array<std::uint32_t, 2> sensor{};
  std::uint32_t motor_state = 0;
};

enum class VariantEvidence { Confirmed29Dof, Partial29Dof, Inconclusive };

bool HasTelemetry(const MotorTelemetry& motor);
bool HasFiniteValues(const MotorTelemetry& motor);
VariantEvidence Classify29Dof(
    const std::array<MotorTelemetry, kDdsMotorSlots>& motors,
    std::vector<std::size_t>& detected_indices);
const char* VariantEvidenceText(VariantEvidence evidence);
std::vector<std::size_t> JointIndices(const std::string& selection);

}  // namespace g1_quest

