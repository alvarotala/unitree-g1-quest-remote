#pragma once

#include <array>
#include <chrono>
#include <cstddef>
#include <string>

namespace g1_quest {

constexpr std::size_t kArmJointCount = 14;
using ArmVector = std::array<double, kArmJointCount>;
using TimePoint = std::chrono::steady_clock::time_point;

enum class SafetyState { Disconnected, Disarmed, Arming, Armed, Fault };

struct SafetyInputs {
  bool quest_connected = false;
  bool local_enable = false;
  bool local_fault_reset = false;
  bool deadman = false;
  bool tracking_valid = false;
  bool lowstate_valid = false;
  bool target_valid = false;
  std::chrono::milliseconds quest_age{1000000};
  std::chrono::milliseconds lowstate_age{1000000};
};

struct SafetyConfig {
  std::chrono::milliseconds arming_hold{1000};
  std::chrono::milliseconds quest_timeout{250};
  std::chrono::milliseconds lowstate_timeout{100};
};

class SafetySupervisor {
 public:
  explicit SafetySupervisor(SafetyConfig config = {});
  SafetyState Update(const SafetyInputs& inputs, TimePoint now);
  SafetyState state() const { return state_; }
  bool command_enabled() const { return state_ == SafetyState::Armed; }
  const std::string& reason() const { return reason_; }

 private:
  bool Ready(const SafetyInputs& inputs) const;
  void Set(SafetyState state, const char* reason);
  SafetyConfig config_;
  SafetyState state_ = SafetyState::Disconnected;
  TimePoint arming_since_{};
  std::string reason_ = "sin sesion Quest";
};

struct LimiterConfig {
  double max_velocity = 0.25;
  double max_acceleration = 0.5;
  double max_target_jump = 0.15;
};

class ArmCommandLimiter {
 public:
  explicit ArmCommandLimiter(LimiterConfig config = {});
  void Seed(const ArmVector& measured);
  bool ValidateTarget(const ArmVector& target) const;
  ArmVector Step(const ArmVector& target, double dt_seconds);
  const ArmVector& position() const { return position_; }

 private:
  LimiterConfig config_;
  ArmVector position_{};
  ArmVector velocity_{};
  bool seeded_ = false;
};

const char* SafetyStateName(SafetyState state);

}  // namespace g1_quest
