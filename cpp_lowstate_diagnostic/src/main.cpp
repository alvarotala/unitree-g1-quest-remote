#include "g1_quest/diagnostic.hpp"

#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/robot/channel/channel_subscriber.hpp>

#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
using LowState = unitree_hg::msg::dds_::LowState_;
constexpr double kRadToDeg = 57.29577951308232;
std::atomic<bool> g_stop{false};
void HandleSignal(int) { g_stop.store(true); }

struct Options {
  std::string interface;
  std::string topic = "rt/lowstate";
  std::string joints = "all";
  int domain_id = 0;
  int first_timeout_ms = 15000;
  int dds_timeout_ms = 1000;
  double duration_s = 8.0;
};

void PrintHelp(const char* program) {
  std::cout << "Uso: " << program << " --interface IFACE [opciones]\n\n"
            << "Diagnostico de solo lectura para G1 EDU+ 29 DOF.\n\n"
            << "  --topic rt/lowstate|rt/lf/lowstate\n"
            << "  --domain-id N\n  --duration SEGUNDOS (0 hasta Ctrl+C)\n"
            << "  --first-message-timeout-ms N\n  --dds-timeout-ms N\n"
            << "  --joints all|arms|optional|none\n";
}
std::string Value(int argc, char** argv, int& i) {
  if (++i >= argc) throw std::invalid_argument("falta valor de opcion");
  return argv[i];
}
int Integer(const std::string& text, const std::string& option) {
  std::size_t used = 0; long value = 0;
  try { value = std::stol(text, &used, 10); }
  catch (...) { throw std::invalid_argument(option + " requiere un entero"); }
  if (used != text.size() || value < 0 || value > 1000000)
    throw std::invalid_argument("valor invalido para " + option);
  return static_cast<int>(value);
}
double Number(const std::string& text, const std::string& option) {
  std::size_t used = 0; double value = 0.0;
  try { value = std::stod(text, &used); }
  catch (...) { throw std::invalid_argument(option + " requiere un numero"); }
  if (used != text.size() || !std::isfinite(value) || value < 0.0)
    throw std::invalid_argument("valor invalido para " + option);
  return value;
}
Options ParseOptions(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "-h" || arg == "--help") { PrintHelp(argv[0]); std::exit(0); }
    if (arg == "-i" || arg == "--interface") o.interface = Value(argc, argv, i);
    else if (arg == "--topic") o.topic = Value(argc, argv, i);
    else if (arg == "--joints") o.joints = Value(argc, argv, i);
    else if (arg == "--domain-id") o.domain_id = Integer(Value(argc, argv, i), arg);
    else if (arg == "--first-message-timeout-ms")
      o.first_timeout_ms = Integer(Value(argc, argv, i), arg);
    else if (arg == "--dds-timeout-ms") o.dds_timeout_ms = Integer(Value(argc, argv, i), arg);
    else if (arg == "--duration") o.duration_s = Number(Value(argc, argv, i), arg);
    else throw std::invalid_argument("opcion desconocida: " + arg);
  }
  if (o.interface.empty()) throw std::invalid_argument("--interface es obligatoria");
  if (o.interface.find_first_of("\r\n") != std::string::npos)
    throw std::invalid_argument("interfaz invalida");
  if (o.topic != "rt/lowstate" && o.topic != "rt/lf/lowstate")
    throw std::invalid_argument("topic no permitido");
  (void)g1_quest::JointIndices(o.joints);
  if (o.first_timeout_ms <= 0) throw std::invalid_argument("timeout inicial invalido");
  if (o.dds_timeout_ms < 100) throw std::invalid_argument("timeout DDS minimo: 100 ms");
  return o;
}

struct Snapshot {
  std::array<std::uint32_t, 2> version{};
  std::uint8_t mode_pr = 0, mode_machine = 0;
  std::uint32_t tick = 0;
  std::array<float, 3> rpy{}, gyro{}, accel{};
  std::int16_t imu_temperature = 0;
  std::array<g1_quest::MotorTelemetry, g1_quest::kDdsMotorSlots> motors{};
  Clock::time_point first_at{}, received_at{};
  std::uint64_t count = 0;
};

class Receiver {
 public:
  void Start(int domain, const std::string& interface, const std::string& topic) {
    unitree::robot::ChannelFactory::Instance()->Init(domain, interface);
    subscriber_.reset(new unitree::robot::ChannelSubscriber<LowState>(topic));
    subscriber_->InitChannel(std::bind(&Receiver::OnMessage, this, std::placeholders::_1), 1);
  }
  std::optional<Snapshot> Latest() const {
    std::lock_guard<std::mutex> lock(mutex_); return latest_;
  }
 private:
  void OnMessage(const void* raw) {
    const auto& message = *static_cast<const LowState*>(raw);
    Snapshot next;
    next.version = message.version(); next.mode_pr = message.mode_pr();
    next.mode_machine = message.mode_machine(); next.tick = message.tick();
    next.rpy = message.imu_state().rpy(); next.gyro = message.imu_state().gyroscope();
    next.accel = message.imu_state().accelerometer();
    next.imu_temperature = message.imu_state().temperature();
    for (std::size_t i = 0; i < next.motors.size(); ++i) {
      const auto& s = message.motor_state()[i]; auto& t = next.motors[i];
      t.mode = s.mode(); t.q = s.q(); t.dq = s.dq(); t.ddq = s.ddq();
      t.tau_est = s.tau_est(); t.temperature = s.temperature();
      t.voltage = s.vol(); t.sensor = s.sensor(); t.motor_state = s.motorstate();
    }
    next.received_at = Clock::now();
    std::lock_guard<std::mutex> lock(mutex_);
    next.count = latest_ ? latest_->count + 1 : 1;
    next.first_at = latest_ ? latest_->first_at : next.received_at;
    latest_ = next;
  }
  mutable std::mutex mutex_;
  std::optional<Snapshot> latest_;
  unitree::robot::ChannelSubscriberPtr<LowState> subscriber_;
};

double Seconds(Clock::duration d) { return std::chrono::duration<double>(d).count(); }
double Rate(const Snapshot& s) {
  const double elapsed = Seconds(s.received_at - s.first_at);
  return s.count > 1 && elapsed > 0.0 ? (s.count - 1) / elapsed : 0.0;
}
void PrintReport(const Snapshot& s, const Options& o) {
  std::vector<std::size_t> detected;
  const auto evidence = g1_quest::Classify29Dof(s.motors, detected);
  std::cout << "\n=== Diagnostico final de " << o.topic << " ===\nMensajes: "
            << s.count << " | tasa: " << std::fixed << std::setprecision(1)
            << Rate(s) << " Hz | edad: " << std::setprecision(3)
            << Seconds(Clock::now() - s.received_at) << " s\nversion: "
            << s.version[0] << '.' << s.version[1] << " | mode_pr: "
            << unsigned(s.mode_pr) << " | mode_machine: " << unsigned(s.mode_machine)
            << " | tick: " << s.tick << '\n' << g1_quest::VariantEvidenceText(evidence)
            << "\nOpcionales con senal:";
  if (detected.empty()) std::cout << " ninguna";
  for (const auto i : detected) std::cout << ' ' << g1_quest::kJointNames[i];
  std::cout << "\nIMU RPY [deg]: " << std::showpos << std::setprecision(2)
            << s.rpy[0] * kRadToDeg << ", " << s.rpy[1] * kRadToDeg << ", "
            << s.rpy[2] * kRadToDeg << "\nIMU gyro [rad/s]: " << std::setprecision(3)
            << s.gyro[0] << ", " << s.gyro[1] << ", " << s.gyro[2]
            << "\nIMU accel [m/s2]: " << s.accel[0] << ", " << s.accel[1]
            << ", " << s.accel[2] << " | temp raw: " << std::noshowpos
            << s.imu_temperature << '\n';
  bool finite = true;
  for (std::size_t i = 0; i < g1_quest::kJointCount; ++i)
    finite = finite && g1_quest::HasFiniteValues(s.motors[i]);
  std::cout << (finite ? "29 articulaciones con valores finitos: si\n"
                       : "ALERTA: hay valores no finitos\n");
  const auto indices = g1_quest::JointIndices(o.joints);
  if (indices.empty()) return;
  std::cout << "\n idx articulacion                 q[deg]    dq       tau   temp  mode error\n";
  for (const auto i : indices) {
    const auto& m = s.motors[i];
    std::cout << std::setw(4) << i << ' ' << std::left << std::setw(27)
              << g1_quest::kJointNames[i] << std::right << std::showpos
              << std::fixed << std::setprecision(2) << std::setw(8) << m.q * kRadToDeg
              << std::setprecision(3) << std::setw(9) << m.dq << std::setw(9)
              << m.tau_est << std::noshowpos << ' ' << m.temperature[0] << '/'
              << m.temperature[1] << std::setw(6) << unsigned(m.mode)
              << std::setw(6) << m.motor_state << '\n';
  }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    const auto o = ParseOptions(argc, argv);
    std::signal(SIGINT, HandleSignal); std::signal(SIGTERM, HandleSignal);
    std::cout << "G1 Quest LowState Diagnostic\nSEGURIDAD: solo suscriptor DDS; "
                 "no publica comandos.\nInterfaz: " << o.interface
              << " | topic: " << o.topic << '\n';
    Receiver receiver; receiver.Start(o.domain_id, o.interface, o.topic);
    const auto deadline = Clock::now() + std::chrono::milliseconds(o.first_timeout_ms);
    while (!g_stop.load() && Clock::now() < deadline && !receiver.Latest())
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    if (!receiver.Latest()) throw std::runtime_error("no llego LowState");
    std::cout << "Primer LowState recibido. Capturando...\n";
    const auto started = Clock::now(); auto progress = started;
    while (!g_stop.load() && (o.duration_s == 0.0 ||
           Seconds(Clock::now() - started) < o.duration_s)) {
      const auto latest = receiver.Latest(); const auto now = Clock::now();
      if (latest && Seconds(now - latest->received_at) * 1000.0 > o.dds_timeout_ms)
        throw std::runtime_error("telemetria DDS detenida");
      if (latest && now >= progress) {
        std::cout << "  recibidos=" << latest->count << " tasa=" << std::fixed
                  << std::setprecision(1) << Rate(*latest) << " Hz\n";
        progress = now + std::chrono::seconds(1);
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    const auto latest = receiver.Latest();
    if (!latest) throw std::runtime_error("sin muestra final");
    PrintReport(*latest, o);
    for (std::size_t i = 0; i < g1_quest::kJointCount; ++i)
      if (!g1_quest::HasFiniteValues(latest->motors[i])) return 4;
    return 0;
  } catch (const std::invalid_argument& e) {
    std::cerr << "Argumentos: " << e.what() << '\n'; return 2;
  } catch (const std::exception& e) {
    std::cerr << "Error: " << e.what() << '\n'; return 3;
  }
}

