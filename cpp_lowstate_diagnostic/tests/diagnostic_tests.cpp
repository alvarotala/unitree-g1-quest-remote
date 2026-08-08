#include "g1_quest/diagnostic.hpp"

#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Expect(bool condition, const std::string& message) {
  if (!condition) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
g1_quest::MotorTelemetry ActiveMotor() {
  g1_quest::MotorTelemetry motor;
  motor.mode = 1; motor.q = 0.1F; motor.temperature = {31, 32};
  motor.voltage = 48.0F; return motor;
}
void VerifyReadOnlySource() {
  std::ifstream input(QUEST_MAIN_SOURCE);
  Expect(input.good(), "puede leer main.cpp");
  const std::string source((std::istreambuf_iterator<char>(input)), {});
  const std::vector<std::string> forbidden = {
      "channel_" "publisher.hpp", "Channel" "Publisher",
      "Low" "Cmd_", "Motion" "Switcher"};
  for (const auto& token : forbidden)
    Expect(source.find(token) == std::string::npos,
           "main no contiene capacidad prohibida: " + token);
}
}  // namespace

int main() {
  using g1_quest::VariantEvidence;
  Expect(g1_quest::kJointNames.size() == 29, "layout de 29 articulaciones");
  std::array<g1_quest::MotorTelemetry, g1_quest::kDdsMotorSlots> motors{};
  for (auto& motor : motors) motor = ActiveMotor();
  std::vector<std::size_t> detected;
  Expect(g1_quest::Classify29Dof(motors, detected) ==
             VariantEvidence::Confirmed29Dof && detected.size() == 6,
         "confirma seis articulaciones opcionales");
  for (const auto index : g1_quest::kOptional29DofIndices) motors[index] = {};
  Expect(g1_quest::Classify29Dof(motors, detected) ==
             VariantEvidence::Inconclusive,
         "no confunde placeholders con motores");
  auto invalid = ActiveMotor(); invalid.q = std::nanf("");
  Expect(!g1_quest::HasFiniteValues(invalid), "rechaza NaN");
  Expect(g1_quest::JointIndices("arms").size() == 14, "dos brazos de 7 DOF");
  Expect(g1_quest::JointIndices("optional").size() == 6, "seis opcionales");
  bool rejected = false;
  try { (void)g1_quest::JointIndices("bad"); }
  catch (const std::invalid_argument&) { rejected = true; }
  Expect(rejected, "rechaza seleccion desconocida");
  VerifyReadOnlySource();
  std::cout << "diagnostic_tests: OK\n";
  return 0;
}

