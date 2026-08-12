#include "g1_quest/supervisor.hpp"

#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>

using namespace std::chrono_literals;

namespace {
void Expect(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
}  // namespace

int main() {
  try {
    using g1_quest::SafetyState;
    const auto start = g1_quest::TimePoint{};
    g1_quest::SafetySupervisor supervisor;
    g1_quest::SafetyInputs inputs;
    Expect(supervisor.Update(inputs, start) == SafetyState::Disconnected,
           "debe iniciar desconectado");

    inputs.quest_connected = true;
    inputs.lowstate_valid = true;
    inputs.lowstate_age = 1ms;
    Expect(supervisor.Update(inputs, start) == SafetyState::Disarmed,
           "una sesion sin habilitacion debe quedar desarmada");

    inputs.local_enable = true;
    inputs.deadman = true;
    inputs.tracking_valid = true;
    inputs.target_valid = true;
    inputs.quest_age = 1ms;
    Expect(supervisor.Update(inputs, start) == SafetyState::Arming,
           "debe entrar en ARMING");
    Expect(!supervisor.command_enabled(), "ARMING no debe habilitar comandos");
    Expect(supervisor.Update(inputs, start + 999ms) == SafetyState::Arming,
           "no debe armar antes del tiempo continuo");
    Expect(supervisor.Update(inputs, start + 1000ms) == SafetyState::Armed,
           "debe armar despues del tiempo continuo");
    Expect(supervisor.command_enabled(), "ARMED debe habilitar comandos");

    inputs.deadman = false;
    Expect(supervisor.Update(inputs, start + 1001ms) == SafetyState::Disarmed,
           "soltar dead-man debe desarmar");
    Expect(!supervisor.command_enabled(), "DISARMED no debe habilitar comandos");

    inputs.deadman = true;
    inputs.target_valid = false;
    supervisor.Update(inputs, start + 1100ms);
    Expect(supervisor.state() == SafetyState::Fault,
           "objetivo invalido debe enclavar FAULT");
    inputs.local_fault_reset = true;
    Expect(supervisor.Update(inputs, start + 1200ms) == SafetyState::Fault,
           "FAULT no debe resetear con habilitacion activa");
    inputs.local_enable = false;
    Expect(supervisor.Update(inputs, start + 1300ms) == SafetyState::Disarmed,
           "reset local con habilitacion apagada debe desarmar");

    g1_quest::ArmCommandLimiter limiter;
    g1_quest::ArmVector measured{}, target{};
    limiter.Seed(measured);
    target.fill(0.1);
    Expect(limiter.ValidateTarget(target), "objetivo cercano debe ser valido");
    const auto first = limiter.Step(target, 0.01);
    Expect(std::abs(first[0] - 0.00005) < 1e-12,
           "el primer paso debe respetar aceleracion");
    target.fill(0.2);
    Expect(!limiter.ValidateTarget(target), "salto inseguro debe rechazarse");

    std::cout << "Phase 4 safety logic: OK\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Phase 4 safety logic: FAIL: " << error.what() << '\n';
    return 1;
  }
}
