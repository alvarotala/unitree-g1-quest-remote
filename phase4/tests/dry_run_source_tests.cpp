#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

int main() {
  try {
    std::ifstream input(DRY_RUN_SOURCE);
    if (!input) throw std::runtime_error("no se pudo leer dry_run_main.cpp");
    const std::string source((std::istreambuf_iterator<char>(input)),
                             std::istreambuf_iterator<char>());
    for (const char* forbidden : {"channel_publisher", "ChannelPublisher", "rt/arm_sdk",
                                  "LowCmd_", "motor_cmd()"}) {
      if (source.find(forbidden) != std::string::npos)
        throw std::runtime_error(std::string("API prohibida en dry-run: ") + forbidden);
    }
    if (source.find("ChannelSubscriber") == std::string::npos)
      throw std::runtime_error("el dry-run debe ser suscriptor");
    std::cout << "Phase 4 dry-run source is subscriber-only: OK\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Phase 4 dry-run source: FAIL: " << error.what() << '\n';
    return 1;
  }
}
