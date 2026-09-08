#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char** argv) {
  try {
    if (argc != 3 || std::string(argv[1]) != "--interface")
      throw std::invalid_argument("uso: g1_loco_readonly_probe --interface IFACE");
    unitree::robot::ChannelFactory::Instance()->Init(0, argv[2]);
    unitree::robot::g1::LocoClient client;
    client.Init();
    client.SetTimeout(1.0f);
    int fsm_id = -1, fsm_mode = -1, balance_mode = -1;
    const int fsm_result = client.GetFsmId(fsm_id);
    const int mode_result = client.GetFsmMode(fsm_mode);
    const int balance_result = client.GetBalanceMode(balance_mode);
    std::cout << "G1 LocoClient read-only probe\n"
              << "SEGURIDAD: solo Get*; no cambia modos ni velocidad.\n"
              << "clientApiVersion: " << client.GetApiVersion() << '\n'
              << "serverApiVersion: " << client.GetServerApiVersion() << '\n'
              << "GetFsmId: result=" << fsm_result << " value=" << fsm_id << '\n'
              << "GetFsmMode: result=" << mode_result << " value=" << fsm_mode << '\n'
              << "GetBalanceMode: result=" << balance_result
              << " value=" << balance_mode << '\n';
    return (fsm_result == 0 && mode_result == 0 && balance_result == 0) ? 0 : 1;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    return 1;
  }
}
