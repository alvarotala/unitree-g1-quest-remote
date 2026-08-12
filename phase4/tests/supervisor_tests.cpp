#include "g1_quest/supervisor.hpp"

#include <cassert>
#include <chrono>
#include <cmath>
#include <iostream>

using namespace std::chrono_literals;

int main() {
  using g1_quest::SafetyState;
  const auto start = g1_quest::TimePoint{};
  g1_quest::SafetySupervisor supervisor;
  g1_quest::SafetyInputs inputs;
  assert(supervisor.Update(inputs, start) == SafetyState::Disconnected);

  inputs.quest_connected = true;
  inputs.lowstate_valid = true;
  inputs.lowstate_age = 1ms;
  assert(supervisor.Update(inputs, start) == SafetyState::Disarmed);

  inputs.local_enable = true;
  inputs.deadman = true;
  inputs.tracking_valid = true;
  inputs.target_valid = true;
  inputs.quest_age = 1ms;
  assert(supervisor.Update(inputs, start) == SafetyState::Arming);
  assert(!supervisor.command_enabled());
  assert(supervisor.Update(inputs, start + 999ms) == SafetyState::Arming);
  assert(supervisor.Update(inputs, start + 1000ms) == SafetyState::Armed);
  assert(supervisor.command_enabled());

  inputs.deadman = false;
  assert(supervisor.Update(inputs, start + 1001ms) == SafetyState::Disarmed);
  assert(!supervisor.command_enabled());

  inputs.deadman = true;
  inputs.target_valid = false;
  supervisor.Update(inputs, start + 1100ms);
  assert(supervisor.state() == SafetyState::Fault);
  inputs.local_fault_reset = true;
  assert(supervisor.Update(inputs, start + 1200ms) == SafetyState::Fault);
  inputs.local_enable = false;
  assert(supervisor.Update(inputs, start + 1300ms) == SafetyState::Disarmed);

  g1_quest::ArmCommandLimiter limiter;
  g1_quest::ArmVector measured{}, target{};
  limiter.Seed(measured);
  target.fill(0.1);
  assert(limiter.ValidateTarget(target));
  const auto first = limiter.Step(target, 0.01);
  assert(std::abs(first[0] - 0.00005) < 1e-12);
  target.fill(0.2);
  assert(!limiter.ValidateTarget(target));

  std::cout << "Phase 4 safety logic: OK\n";
  return 0;
}
