#include "g1_quest/supervisor.hpp"

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
using LowState = unitree_hg::msg::dds_::LowState_;
constexpr std::array<std::size_t, 14> kArmIndices = {
    15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28};
constexpr auto kQuestTimeout = std::chrono::milliseconds(250);
constexpr auto kModeHold = std::chrono::milliseconds(1500);
constexpr auto kVelocityPeriod = std::chrono::milliseconds(100);
constexpr float kVelocityDurationSeconds = 0.25f;
std::atomic<bool> g_stop{false};
void HandleSignal(int) { g_stop.store(true); }

struct Options {
  std::string interface;
  double duration_s = 60.0;
  bool local_enable = false;
  bool authorize_motion = false;
  bool allow_fall_modes = false;
  std::string quest_socket = "/tmp/g1_quest_safety.sock";
};

void Help(const char* program) {
  std::cout
      << "Uso: " << program << " --interface IFACE --local-enable\n"
      << "  --authorize-motion G1_VR_MOTION [--duration S]\n"
      << "  [--allow-fall-modes --authorize-fall-modes G1_CAN_FALL]\n"
      << "PUBLICA comandos oficiales LocoClient. Robot soportado y area libre.\n";
}

Options Parse(int argc, char** argv) {
  Options options;
  bool fall_phrase = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "-h" || arg == "--help") { Help(argv[0]); std::exit(0); }
    if (arg == "--local-enable") { options.local_enable = true; continue; }
    if (arg == "--allow-fall-modes") { options.allow_fall_modes = true; continue; }
    if (arg != "--interface" && arg != "--duration" &&
        arg != "--quest-socket" && arg != "--authorize-motion" &&
        arg != "--authorize-fall-modes")
      throw std::invalid_argument("opcion desconocida: " + arg);
    if (++i >= argc) throw std::invalid_argument("falta valor para " + arg);
    const std::string value = argv[i];
    if (arg == "--interface") options.interface = value;
    else if (arg == "--duration") options.duration_s = std::stod(value);
    else if (arg == "--quest-socket") options.quest_socket = value;
    else if (arg == "--authorize-motion")
      options.authorize_motion = value == "G1_VR_MOTION";
    else fall_phrase = value == "G1_CAN_FALL";
  }
  if (options.interface.empty()) throw std::invalid_argument("--interface es obligatoria");
  if (!options.local_enable || !options.authorize_motion)
    throw std::invalid_argument(
        "se requieren --local-enable y --authorize-motion G1_VR_MOTION");
  if (options.allow_fall_modes && !fall_phrase)
    throw std::invalid_argument(
        "--allow-fall-modes requiere --authorize-fall-modes G1_CAN_FALL");
  if (!std::isfinite(options.duration_s) || options.duration_s <= 0.0)
    throw std::invalid_argument("--duration debe ser positivo");
  return options;
}

struct QuestSignal {
  std::string session;
  std::uint64_t sequence = 0;
  bool tracking = false, deadman = false;
  bool left_grip = false, right_grip = false;
  double left_x = 0.0, left_y = 0.0, right_x = 0.0, right_y = 0.0;
  bool left_trigger = false, right_trigger = false;
  bool button_x = false, button_y = false, button_a = false, button_b = false;
  Clock::time_point received_at{};
};

class QuestSocketReceiver {
 public:
  explicit QuestSocketReceiver(const std::string& path) : path_(path) {
    sockaddr_un address{};
    if (path.empty() || path.size() >= sizeof(address.sun_path))
      throw std::invalid_argument("ruta de socket Quest invalida");
    fd_ = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (fd_ < 0) throw std::runtime_error("no se pudo crear socket Quest");
    unlink(path.c_str());
    address.sun_family = AF_UNIX;
    std::copy(path.begin(), path.end(), address.sun_path);
    if (bind(fd_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0)
      throw std::runtime_error("no se pudo enlazar socket Quest");
    chmod(path.c_str(), S_IRUSR | S_IWUSR);
  }
  ~QuestSocketReceiver() { if (fd_ >= 0) close(fd_); unlink(path_.c_str()); }

  std::optional<QuestSignal> Poll() {
    char buffer[256];
    for (;;) {
      const auto size = recv(fd_, buffer, sizeof(buffer) - 1, 0);
      if (size < 0) break;
      buffer[size] = '\0';
      std::string version, session, extra;
      unsigned long long sequence = 0;
      int tracking, deadman, lg, rg, lt, rt, x, y, a, b;
      double lx, ly, rx, ry;
      std::istringstream input(buffer);
      if (!(input >> version >> session >> sequence >> tracking >> deadman >>
            lg >> rg >> lx >> ly >> rx >> ry >> lt >> rt >> x >> y >> a >> b) ||
          (input >> extra) || version != "G1Q2" ||
          std::min({tracking, deadman, lg, rg, lt, rt, x, y, a, b}) < 0 ||
          std::max({tracking, deadman, lg, rg, lt, rt, x, y, a, b}) > 1 ||
          !std::isfinite(lx) || !std::isfinite(ly) ||
          !std::isfinite(rx) || !std::isfinite(ry) ||
          std::max({std::abs(lx), std::abs(ly), std::abs(rx), std::abs(ry)}) > 1.001)
        continue;
      if (latest_ && latest_->session == session && sequence <= latest_->sequence) continue;
      latest_ = QuestSignal{session, sequence, tracking == 1, deadman == 1,
                            lg == 1, rg == 1, lx, ly, rx, ry,
                            lt == 1, rt == 1, x == 1, y == 1, a == 1, b == 1,
                            Clock::now()};
    }
    return latest_;
  }
 private:
  std::string path_;
  int fd_ = -1;
  std::optional<QuestSignal> latest_;
};

struct LowSnapshot {
  bool finite = false, motor_errors = false;
  Clock::time_point received_at{};
  std::uint64_t count = 0;
};

class LowStateReceiver {
 public:
  void Start(const std::string& interface) {
    unitree::robot::ChannelFactory::Instance()->Init(0, interface);
    subscriber_.reset(new unitree::robot::ChannelSubscriber<LowState>("rt/lowstate"));
    subscriber_->InitChannel(std::bind(&LowStateReceiver::OnMessage, this,
                                      std::placeholders::_1), 1);
  }
  std::optional<LowSnapshot> Latest() const {
    std::lock_guard<std::mutex> lock(mutex_); return latest_;
  }
 private:
  void OnMessage(const void* raw) {
    const auto& message = *static_cast<const LowState*>(raw);
    LowSnapshot next; next.finite = true;
    for (const auto index : kArmIndices) {
      const auto& motor = message.motor_state()[index];
      next.finite = next.finite && std::isfinite(motor.q()) && std::isfinite(motor.dq());
      next.motor_errors = next.motor_errors || motor.motorstate() != 0;
    }
    next.received_at = Clock::now();
    std::lock_guard<std::mutex> lock(mutex_);
    next.count = latest_ ? latest_->count + 1 : 1; latest_ = next;
  }
  mutable std::mutex mutex_;
  std::optional<LowSnapshot> latest_;
  unitree::robot::ChannelSubscriberPtr<LowState> subscriber_;
};

double Deadzone(double value, double zone = 0.15) {
  if (std::abs(value) <= zone) return 0.0;
  return std::copysign((std::abs(value) - zone) / (1.0 - zone), value);
}
std::array<float, 3> Velocity(const std::optional<QuestSignal>& q) {
  if (!q || !q->tracking || !q->deadman) return {};
  return {static_cast<float>(-0.15 * Deadzone(q->left_y)),
          static_cast<float>( 0.10 * Deadzone(q->left_x)),
          static_cast<float>(-0.25 * Deadzone(q->right_x))};
}
bool SticksCentered(const std::optional<QuestSignal>& q) {
  return q && std::max({std::abs(q->left_x), std::abs(q->left_y),
                        std::abs(q->right_x), std::abs(q->right_y)}) <= 0.15;
}
const char* ModeIntent(const std::optional<QuestSignal>& q) {
  if (!q || !q->left_trigger || !q->right_trigger) return "NONE";
  if (q->button_x) return "DAMP";
  if (q->button_y) return "ZERO_TORQUE";
  if (q->button_a) return "STAND_UP";
  if (q->button_b) return "BALANCE_STAND";
  return "NONE";
}

class StatusFile {
 public:
  ~StatusFile() { unlink(path_.c_str()); }
  void Write(const g1_quest::SafetySupervisor& supervisor,
             const std::optional<QuestSignal>& quest,
             std::chrono::milliseconds quest_age,
             std::chrono::milliseconds low_age,
             const char* mode_intent, const std::array<float, 3>& velocity,
             bool fall_modes, int last_result) {
    const auto temporary = path_ + "." + std::to_string(getpid());
    std::ofstream out(temporary, std::ios::trunc);
    if (!out) return;
    out << "{\"state\":\"" << g1_quest::SafetyStateName(supervisor.state())
        << "\",\"reason\":\"" << supervisor.reason()
        << "\",\"runtimeMode\":\"LIVE_LOCOMOTION\""
        << ",\"wouldPublish\":" << (supervisor.command_enabled() ? "true" : "false")
        << ",\"localEnable\":true"
        << ",\"tracking\":" << (quest && quest->tracking ? "true" : "false")
        << ",\"deadman\":" << (quest && quest->deadman ? "true" : "false")
        << ",\"leftGrip\":" << (quest && quest->left_grip ? "true" : "false")
        << ",\"rightGrip\":" << (quest && quest->right_grip ? "true" : "false")
        << ",\"walkIntent\":[" << velocity[0] << ',' << velocity[1] << ',' << velocity[2] << ']'
        << ",\"modeIntent\":\"" << mode_intent << "\""
        << ",\"fallModesEnabled\":" << (fall_modes ? "true" : "false")
        << ",\"lastApiResult\":" << last_result
        << ",\"questAgeMs\":" << (quest ? quest_age.count() : -1)
        << ",\"lowstateAgeMs\":" << low_age.count() << "}\n";
    out.close(); chmod(temporary.c_str(), S_IRUSR | S_IWUSR);
    rename(temporary.c_str(), path_.c_str());
  }
 private:
  std::string path_ = "/tmp/g1_quest_supervisor_status.json";
};

int ExecuteMode(unitree::robot::g1::LocoClient& client, const std::string& mode,
                bool allow_fall_modes) {
  if (mode == "STAND_UP") return client.StandUp();
  if (mode == "BALANCE_STAND") return client.BalanceStand();
  if (mode == "DAMP" && allow_fall_modes) return client.Damp();
  if (mode == "ZERO_TORQUE" && allow_fall_modes) return client.ZeroTorque();
  return -1001;
}

class StopOnExit {
 public:
  StopOnExit(unitree::robot::g1::LocoClient& client, bool& commanded)
      : client_(client), commanded_(commanded) {}
  ~StopOnExit() {
    if (commanded_) {
      const int result = client_.StopMove();
      std::cerr << "STOP de salida | resultado=" << result << '\n';
    }
  }
 private:
  unitree::robot::g1::LocoClient& client_;
  bool& commanded_;
};
}  // namespace

int main(int argc, char** argv) {
  bool ever_commanded = false;
  try {
    const auto options = Parse(argc, argv);
    std::signal(SIGINT, HandleSignal); std::signal(SIGTERM, HandleSignal);
    std::cout << "G1 VR LIVE LOCOMOTION\n"
              << "PELIGRO: este ejecutable ENVIA comandos LocoClient reales.\n"
              << "Interfaz: " << options.interface
              << " | fall modes: " << (options.allow_fall_modes ? "HABILITADOS" : "bloqueados")
              << "\nCtrl-C local siempre disponible.\n";

    QuestSocketReceiver quest_receiver(options.quest_socket);
    LowStateReceiver low_receiver; low_receiver.Start(options.interface);
    const auto first_deadline = Clock::now() + std::chrono::seconds(15);
    while (!g_stop.load() && Clock::now() < first_deadline && !low_receiver.Latest())
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if (!low_receiver.Latest()) throw std::runtime_error("no llego LowState");

    unitree::robot::g1::LocoClient client; client.Init(); client.SetTimeout(0.5f);
    StopOnExit stop_on_exit(client, ever_commanded);
    g1_quest::SafetySupervisor supervisor;
    StatusFile status_file;
    bool neutral_latched = false;
    auto previous = supervisor.state();
    auto started = Clock::now(), next_velocity = started, next_status = started;
    std::string held_mode = "NONE", executed_mode = "NONE";
    auto mode_since = started;
    int last_result = 0;

    while (!g_stop.load() &&
           std::chrono::duration<double>(Clock::now() - started).count() < options.duration_s) {
      const auto now = Clock::now();
      const auto low = low_receiver.Latest();
      const auto quest = quest_receiver.Poll();
      const auto quest_age = quest ? std::chrono::duration_cast<std::chrono::milliseconds>(
          now - quest->received_at) : std::chrono::milliseconds(1000000);
      const auto low_age = low ? std::chrono::duration_cast<std::chrono::milliseconds>(
          now - low->received_at) : std::chrono::milliseconds(1000000);
      const bool connected = quest && quest_age <= kQuestTimeout;
      if (!connected || !quest->deadman || !quest->tracking) neutral_latched = false;
      if (supervisor.state() != g1_quest::SafetyState::Armed &&
          !SticksCentered(quest)) neutral_latched = false;
      if (connected && quest->deadman && quest->tracking && SticksCentered(quest))
        neutral_latched = true;

      g1_quest::SafetyInputs inputs;
      inputs.quest_connected = connected;
      inputs.local_enable = options.local_enable && neutral_latched;
      inputs.deadman = quest && quest->deadman;
      inputs.tracking_valid = quest && quest->tracking;
      inputs.lowstate_valid = low && low->finite && !low->motor_errors;
      inputs.target_valid = true;
      inputs.quest_age = quest_age; inputs.lowstate_age = low_age;
      const auto state = supervisor.Update(inputs, now);
      const auto velocity = Velocity(quest);
      const std::string mode = ModeIntent(quest);

      if (previous == g1_quest::SafetyState::Armed &&
          state != g1_quest::SafetyState::Armed && ever_commanded) {
        last_result = client.StopMove();
        std::cout << "STOP automatico | resultado=" << last_result << '\n';
      }
      if (state == g1_quest::SafetyState::Armed && now >= next_velocity) {
        last_result = client.SetVelocity(velocity[0], velocity[1], velocity[2],
                                         kVelocityDurationSeconds);
        ever_commanded = true;
        next_velocity = now + kVelocityPeriod;
        if (last_result != 0) throw std::runtime_error("SetVelocity fallo: " + std::to_string(last_result));
      }

      const bool mode_safe = state == g1_quest::SafetyState::Armed && SticksCentered(quest);
      if (!mode_safe || mode == "NONE") {
        held_mode = "NONE"; executed_mode = "NONE"; mode_since = now;
      } else if (mode != held_mode) {
        held_mode = mode; executed_mode = "NONE"; mode_since = now;
      } else if (executed_mode != mode && now - mode_since >= kModeHold) {
        last_result = ExecuteMode(client, mode, options.allow_fall_modes);
        if (last_result == -1001)
          std::cout << "MODO BLOQUEADO: " << mode << " (fall modes deshabilitados)\n";
        else {
          ever_commanded = true;
          std::cout << "MODO EJECUTADO: " << mode << " | resultado=" << last_result << '\n';
          if (last_result != 0) throw std::runtime_error("API de modo fallo: " + std::to_string(last_result));
        }
        executed_mode = mode;
      }

      if (state != previous) {
        std::cout << "Estado: " << g1_quest::SafetyStateName(previous) << " -> "
                  << g1_quest::SafetyStateName(state) << " | " << supervisor.reason() << '\n';
        previous = state;
      }
      if (now >= next_status) {
        status_file.Write(supervisor, quest, quest_age, low_age, mode.c_str(),
                          velocity, options.allow_fall_modes, last_result);
        next_status = now + std::chrono::milliseconds(50);
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if (ever_commanded) {
      const int result = client.StopMove();
      std::cout << "STOP final | resultado=" << result << '\n';
      ever_commanded = false;
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    std::cerr << "Si hubo movimiento, use el control local/remote Unitree para detenerlo.\n";
    return 1;
  }
}
