#include "g1_quest/supervisor.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace g1_quest {

SafetySupervisor::SafetySupervisor(SafetyConfig config) : config_(config) {}

bool SafetySupervisor::Ready(const SafetyInputs& i) const {
  return i.quest_connected && i.local_enable && i.deadman && i.tracking_valid &&
         i.lowstate_valid && i.target_valid &&
         i.quest_age <= config_.quest_timeout &&
         i.lowstate_age <= config_.lowstate_timeout;
}

void SafetySupervisor::Set(SafetyState state, const char* reason) {
  state_ = state;
  reason_ = reason;
}

SafetyState SafetySupervisor::Update(const SafetyInputs& i, TimePoint now) {
  if (state_ == SafetyState::Fault) {
    if (i.local_fault_reset && !i.local_enable)
      Set(i.quest_connected ? SafetyState::Disarmed : SafetyState::Disconnected,
          "fault restablecido localmente");
    return state_;
  }
  if (!i.quest_connected) {
    Set(SafetyState::Disconnected, "sesion Quest desconectada");
    return state_;
  }
  if (!i.lowstate_valid || i.lowstate_age > config_.lowstate_timeout) {
    Set(SafetyState::Fault, "LowState invalido o vencido");
    return state_;
  }
  if (!i.target_valid && i.local_enable && i.deadman) {
    Set(SafetyState::Fault, "objetivo articular invalido");
    return state_;
  }
  if (!i.local_enable) {
    Set(SafetyState::Disarmed, "habilitacion local desactivada");
    return state_;
  }
  if (!i.deadman || !i.tracking_valid || i.quest_age > config_.quest_timeout) {
    Set(SafetyState::Disarmed, "dead-man, tracking o stream no valido");
    return state_;
  }
  if (state_ != SafetyState::Arming && state_ != SafetyState::Armed) {
    state_ = SafetyState::Arming;
    reason_ = "verificando condiciones continuas";
    arming_since_ = now;
  }
  if (state_ == SafetyState::Arming && Ready(i) && now - arming_since_ >= config_.arming_hold)
    Set(SafetyState::Armed, "condiciones de armado confirmadas");
  return state_;
}

ArmCommandLimiter::ArmCommandLimiter(LimiterConfig config) : config_(config) {}

void ArmCommandLimiter::Seed(const ArmVector& measured) {
  if (!std::all_of(measured.begin(), measured.end(), [](double q) { return std::isfinite(q); }))
    throw std::invalid_argument("postura medida no finita");
  position_ = measured;
  velocity_.fill(0.0);
  seeded_ = true;
}

bool ArmCommandLimiter::ValidateTarget(const ArmVector& target) const {
  if (!seeded_) return false;
  for (std::size_t i = 0; i < target.size(); ++i)
    if (!std::isfinite(target[i]) || std::abs(target[i] - position_[i]) > config_.max_target_jump)
      return false;
  return true;
}

ArmVector ArmCommandLimiter::Step(const ArmVector& target, double dt) {
  if (!ValidateTarget(target)) throw std::invalid_argument("salto de objetivo inseguro");
  dt = std::clamp(dt, 0.001, 0.02);
  for (std::size_t i = 0; i < target.size(); ++i) {
    const double desired_velocity = std::clamp(
        (target[i] - position_[i]) / dt, -config_.max_velocity, config_.max_velocity);
    const double delta = std::clamp(
        desired_velocity - velocity_[i],
        -config_.max_acceleration * dt, config_.max_acceleration * dt);
    velocity_[i] = std::clamp(
        velocity_[i] + delta, -config_.max_velocity, config_.max_velocity);
    position_[i] += velocity_[i] * dt;
  }
  return position_;
}

const char* SafetyStateName(SafetyState state) {
  switch (state) {
    case SafetyState::Disconnected: return "DISCONNECTED";
    case SafetyState::Disarmed: return "DISARMED";
    case SafetyState::Arming: return "ARMING";
    case SafetyState::Armed: return "ARMED";
    case SafetyState::Fault: return "FAULT";
  }
  return "UNKNOWN";
}

}  // namespace g1_quest
