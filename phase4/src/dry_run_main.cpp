#include "g1_quest/supervisor.hpp"

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
using LowState = unitree_hg::msg::dds_::LowState_;
constexpr std::array<std::size_t, g1_quest::kArmJointCount> kArmIndices = {
    15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28};
std::atomic<bool> g_stop{false};
void HandleSignal(int) { g_stop.store(true); }

struct Options {
  std::string interface;
  double duration_s = 8.0;
  bool exercise_arming = false;
  bool quest_live = false;
  bool local_enable = false;
  std::string quest_socket = "/tmp/g1_quest_safety.sock";
};

void Help(const char* program) {
  std::cout << "Uso: " << program
            << " --interface IFACE [--duration S] [--exercise-arming]\n"
            << "  --quest-live --local-enable [--quest-socket PATH]\n"
            << "Solo lee LowState; no contiene publisher ni envia comandos.\n";
}

Options Parse(int argc, char** argv) {
  Options options;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "-h" || arg == "--help") { Help(argv[0]); std::exit(0); }
    if (arg == "--exercise-arming") { options.exercise_arming = true; continue; }
    if (arg == "--quest-live") { options.quest_live = true; continue; }
    if (arg == "--local-enable") { options.local_enable = true; continue; }
    if (arg != "--interface" && arg != "--duration" && arg != "--quest-socket")
      throw std::invalid_argument("opcion desconocida: " + arg);
    if (++i >= argc) throw std::invalid_argument("falta valor para " + arg);
    if (arg == "--interface") options.interface = argv[i];
    else if (arg == "--duration") options.duration_s = std::stod(argv[i]);
    else options.quest_socket = argv[i];
  }
  if (options.interface.empty()) throw std::invalid_argument("--interface es obligatoria");
  if (!std::isfinite(options.duration_s) || options.duration_s <= 0.0)
    throw std::invalid_argument("--duration debe ser positivo");
  if (options.exercise_arming && options.quest_live)
    throw std::invalid_argument("--exercise-arming y --quest-live son excluyentes");
  if (options.quest_live && !options.local_enable)
    throw std::invalid_argument("--quest-live requiere --local-enable explicito");
  return options;
}

struct QuestSignal {
  std::string session;
  std::uint64_t sequence = 0;
  bool tracking = false;
  bool deadman = false;
  bool left_grip = false;
  bool right_grip = false;
  Clock::time_point received_at{};
};

class QuestSocketReceiver {
 public:
  explicit QuestSocketReceiver(const std::string& path) : path_(path) {
    sockaddr_un address{};
    if (path_.empty() || path_.size() >= sizeof(address.sun_path))
      throw std::invalid_argument("ruta de socket Quest invalida");
    fd_ = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    if (fd_ < 0) throw std::runtime_error("no se pudo crear socket Quest");
    unlink(path_.c_str());
    address.sun_family = AF_UNIX;
    std::copy(path_.begin(), path_.end(), address.sun_path);
    address.sun_path[path_.size()] = '\0';
    if (bind(fd_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0) {
      close(fd_); fd_ = -1;
      throw std::runtime_error("no se pudo enlazar socket Quest: " + path_);
    }
    chmod(path_.c_str(), S_IRUSR | S_IWUSR);
  }
  ~QuestSocketReceiver() {
    if (fd_ >= 0) close(fd_);
    unlink(path_.c_str());
  }
  std::optional<QuestSignal> Poll() {
    char buffer[256];
    for (;;) {
      const auto size = recv(fd_, buffer, sizeof(buffer) - 1, 0);
      if (size < 0) break;
      buffer[size] = '\0';
      std::string version, session, extra;
      unsigned long long sequence = 0;
      int tracking = -1, deadman = -1, left_grip = -1, right_grip = -1;
      std::istringstream stream(buffer);
      if (!(stream >> version >> session >> sequence >> tracking >> deadman >>
            left_grip >> right_grip) ||
          (stream >> extra) || version != "G1Q1" ||
          (tracking != 0 && tracking != 1) || (deadman != 0 && deadman != 1) ||
          (left_grip != 0 && left_grip != 1) ||
          (right_grip != 0 && right_grip != 1))
        continue;
      if (latest_ && latest_->session == session && sequence <= latest_->sequence)
        continue;
      latest_ = QuestSignal{session, sequence, tracking == 1, deadman == 1,
                            left_grip == 1, right_grip == 1, Clock::now()};
    }
    return latest_;
  }
 private:
  std::string path_;
  int fd_ = -1;
  std::optional<QuestSignal> latest_;
};

class SupervisorStatusFile {
 public:
  explicit SupervisorStatusFile(
      std::string path = "/tmp/g1_quest_supervisor_status.json") : path_(std::move(path)) {}
  ~SupervisorStatusFile() { unlink(path_.c_str()); }
  void Write(g1_quest::SafetyState state, const std::string& reason,
             bool would_publish, bool local_enable,
             const std::optional<QuestSignal>& quest,
             std::chrono::milliseconds quest_age,
             std::chrono::milliseconds lowstate_age) {
    const std::string temporary = path_ + "." + std::to_string(getpid());
    std::ofstream output(temporary, std::ios::trunc);
    if (!output) return;
    output << "{\"state\":\"" << g1_quest::SafetyStateName(state)
           << "\",\"reason\":\"" << reason
           << "\",\"wouldPublish\":" << (would_publish ? "true" : "false")
           << ",\"localEnable\":" << (local_enable ? "true" : "false")
           << ",\"tracking\":" << (quest && quest->tracking ? "true" : "false")
           << ",\"deadman\":" << (quest && quest->deadman ? "true" : "false")
           << ",\"leftGrip\":" << (quest && quest->left_grip ? "true" : "false")
           << ",\"rightGrip\":" << (quest && quest->right_grip ? "true" : "false")
           << ",\"questAgeMs\":" << (quest ? quest_age.count() : -1)
           << ",\"lowstateAgeMs\":" << lowstate_age.count() << "}\n";
    output.close();
    chmod(temporary.c_str(), S_IRUSR | S_IWUSR);
    rename(temporary.c_str(), path_.c_str());
  }
 private:
  std::string path_;
};

struct Snapshot {
  g1_quest::ArmVector q{};
  bool finite = false;
  bool motor_errors = false;
  Clock::time_point received_at{};
  std::uint64_t count = 0;
};

class Receiver {
 public:
  void Start(const std::string& interface) {
    unitree::robot::ChannelFactory::Instance()->Init(0, interface);
    subscriber_.reset(new unitree::robot::ChannelSubscriber<LowState>("rt/lowstate"));
    subscriber_->InitChannel(std::bind(&Receiver::OnMessage, this, std::placeholders::_1), 1);
  }
  std::optional<Snapshot> Latest() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return latest_;
  }
 private:
  void OnMessage(const void* raw) {
    const auto& message = *static_cast<const LowState*>(raw);
    Snapshot next;
    next.finite = true;
    for (std::size_t i = 0; i < kArmIndices.size(); ++i) {
      const auto& motor = message.motor_state()[kArmIndices[i]];
      next.q[i] = motor.q();
      next.finite = next.finite && std::isfinite(next.q[i]) && std::isfinite(motor.dq());
      next.motor_errors = next.motor_errors || motor.motorstate() != 0;
    }
    next.received_at = Clock::now();
    std::lock_guard<std::mutex> lock(mutex_);
    next.count = latest_ ? latest_->count + 1 : 1;
    latest_ = next;
  }
  mutable std::mutex mutex_;
  std::optional<Snapshot> latest_;
  unitree::robot::ChannelSubscriberPtr<LowState> subscriber_;
};

double Seconds(Clock::duration duration) {
  return std::chrono::duration<double>(duration).count();
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const auto options = Parse(argc, argv);
    std::signal(SIGINT, HandleSignal);
    std::signal(SIGTERM, HandleSignal);
    std::cout << "G1 Phase 4 arm dry-run\n"
              << "SEGURIDAD: solo LowState; cero publishers; cero comandos.\n"
              << "Interfaz: " << options.interface
              << " | Quest: " << (options.quest_live ? "real" :
                                    options.exercise_arming ? "simulado" : "desconectado")
              << " | habilitacion local: "
              << ((options.local_enable || options.exercise_arming) ? "si" : "no") << '\n';

    std::unique_ptr<QuestSocketReceiver> quest_receiver;
    if (options.quest_live) {
      quest_receiver = std::make_unique<QuestSocketReceiver>(options.quest_socket);
      std::cout << "Socket Quest local: " << options.quest_socket << '\n';
    }

    Receiver receiver;
    receiver.Start(options.interface);
    const auto first_deadline = Clock::now() + std::chrono::seconds(15);
    while (!g_stop.load() && Clock::now() < first_deadline && !receiver.Latest())
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    auto latest = receiver.Latest();
    if (!latest) throw std::runtime_error("no llego LowState");

    g1_quest::ArmCommandLimiter limiter;
    limiter.Seed(latest->q);
    g1_quest::SafetySupervisor supervisor;
    g1_quest::SafetyState previous = supervisor.state();
    const auto started = Clock::now();
    auto next_print = started;
    auto next_status = started;
    SupervisorStatusFile status_file;
    while (!g_stop.load() && Seconds(Clock::now() - started) < options.duration_s) {
      const auto now = Clock::now();
      latest = receiver.Latest();
      if (!latest) throw std::runtime_error("LowState desaparecio");
      const auto age = std::chrono::duration_cast<std::chrono::milliseconds>(
          now - latest->received_at);
      const bool lowstate_ok = latest->finite && !latest->motor_errors && age.count() >= 0;
      const auto quest = quest_receiver ? quest_receiver->Poll() : std::nullopt;
      const auto quest_age = quest
          ? std::chrono::duration_cast<std::chrono::milliseconds>(now - quest->received_at)
          : std::chrono::milliseconds(1000000);
      g1_quest::SafetyInputs inputs;
      inputs.quest_connected = options.exercise_arming ||
          (quest && quest_age <= std::chrono::milliseconds(250));
      inputs.local_enable = options.exercise_arming || options.local_enable;
      inputs.deadman = options.exercise_arming || (quest && quest->deadman);
      inputs.tracking_valid = options.exercise_arming || (quest && quest->tracking);
      inputs.target_valid = limiter.ValidateTarget(limiter.position());
      inputs.quest_age = options.exercise_arming ? std::chrono::milliseconds(0) : quest_age;
      inputs.lowstate_valid = lowstate_ok;
      inputs.lowstate_age = age;
      const auto state = supervisor.Update(inputs, now);
      if (now >= next_status) {
        status_file.Write(state, supervisor.reason(), supervisor.command_enabled(),
                          inputs.local_enable, quest, quest_age, age);
        next_status = now + std::chrono::milliseconds(50);
      }
      if (state != previous) {
        std::cout << "Estado: " << g1_quest::SafetyStateName(previous) << " -> "
                  << g1_quest::SafetyStateName(state) << " | " << supervisor.reason() << '\n';
        previous = state;
      }
      if (now >= next_print) {
        std::cout << "LowState=" << latest->count << " edad=" << age.count()
                  << " ms | estado=" << g1_quest::SafetyStateName(state)
                  << " | WOULD_PUBLISH=" << (supervisor.command_enabled() ? "si" : "no")
                  << " | Quest=" << (quest ? quest->session : "-")
                  << " seq=" << (quest ? std::to_string(quest->sequence) : "-")
                  << " edad=" << (quest ? std::to_string(quest_age.count()) : "-") << " ms"
                  << " | q brazos [rad]=" << std::fixed << std::setprecision(3);
        for (const double q : limiter.position()) std::cout << ' ' << q;
        std::cout << '\n';
        next_print = now + std::chrono::seconds(1);
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    std::cout << "Dry-run finalizado. Mensajes publicados: 0\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    return 1;
  }
}
