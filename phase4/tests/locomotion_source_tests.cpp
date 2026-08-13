#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>

int main() {
  try {
    std::ifstream input(LOCOMOTION_SOURCE);
    const std::string source((std::istreambuf_iterator<char>(input)), {});
    for (const char* required : {"G1_VR_MOTION", "--local-enable", "StopMove()",
                                 "SetVelocity", "kVelocityDurationSeconds",
                                 "G1_CAN_FALL", "kModeHold"})
      if (source.find(required) == std::string::npos)
        throw std::runtime_error(std::string("falta barrera: ") + required);
    for (const char* forbidden : {"864000", "ChannelPublisher", "rt/arm_sdk"})
      if (source.find(forbidden) != std::string::npos)
        throw std::runtime_error(std::string("patron inseguro: ") + forbidden);
    std::cout << "Live locomotion source safety barriers: OK\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Live locomotion source safety barriers: FAIL: " << error.what() << '\n';
    return 1;
  }
}
