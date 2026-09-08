#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

int main() {
  try {
    std::ifstream input(LOCO_PROBE_SOURCE);
    const std::string source((std::istreambuf_iterator<char>(input)), {});
    for (const char* forbidden : {"SetVelocity", "Move(", "StopMove", "StandUp",
                                  "BalanceStand", "Damp(", "ZeroTorque", "SetFsm"})
      if (source.find(forbidden) != std::string::npos)
        throw std::runtime_error(std::string("API no read-only: ") + forbidden);
    for (const char* required : {"GetFsmId", "GetFsmMode", "GetBalanceMode",
                                 "GetServerApiVersion"})
      if (source.find(required) == std::string::npos)
        throw std::runtime_error(std::string("consulta ausente: ") + required);
    std::cout << "Loco probe source is read-only: OK\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Loco probe source: FAIL: " << error.what() << '\n';
    return 1;
  }
}
