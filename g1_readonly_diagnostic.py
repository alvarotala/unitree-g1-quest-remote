#!/usr/bin/env python3
"""Diagnóstico de solo lectura para un Unitree G1 EDU+ de 29 DOF.

Este programa únicamente crea un ChannelSubscriber para ``rt/lowstate``.
No importa ChannelPublisher, LowCmd ni MotionSwitcherClient y, por tanto,
no publica órdenes ni cambia el modo de movimiento del robot.
"""

from __future__ import print_function

import argparse
import math
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


LOWSTATE_TOPIC = "rt/lowstate"
EXPECTED_JOINT_COUNT = 29

JOINT_NAMES: Tuple[str, ...] = (
    "left_hip_pitch",
    "left_hip_roll",
    "left_hip_yaw",
    "left_knee",
    "left_ankle_pitch",
    "left_ankle_roll",
    "right_hip_pitch",
    "right_hip_roll",
    "right_hip_yaw",
    "right_knee",
    "right_ankle_pitch",
    "right_ankle_roll",
    "waist_yaw",
    "waist_roll",
    "waist_pitch",
    "left_shoulder_pitch",
    "left_shoulder_roll",
    "left_shoulder_yaw",
    "left_elbow",
    "left_wrist_roll",
    "left_wrist_pitch",
    "left_wrist_yaw",
    "right_shoulder_pitch",
    "right_shoulder_roll",
    "right_shoulder_yaw",
    "right_elbow",
    "right_wrist_roll",
    "right_wrist_pitch",
    "right_wrist_yaw",
)

# Estas articulaciones no existen en el G1 de 23 DOF. Telemetría válida en
# estos índices aporta evidencia de que el robot es la variante de 29 DOF.
OPTIONAL_29_DOF_INDICES: Tuple[int, ...] = (13, 14, 20, 21, 27, 28)
ARM_INDICES: Tuple[int, ...] = tuple(range(15, 29))


@dataclass(frozen=True)
class InterfaceInfo:
    name: str
    state: str
    ipv4: Optional[str]
    loopback: bool


@dataclass(frozen=True)
class ReceiveSnapshot:
    message_count: int
    elapsed_s: float
    rate_hz: float
    latest: Optional[Any]
    last_age_s: Optional[float]


class LowStateCollector:
    """Acumula estadísticas sin modificar los mensajes DDS recibidos."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._first_at: Optional[float] = None
        self._last_at: Optional[float] = None
        self._latest: Optional[Any] = None

    def on_message(self, message: Any) -> None:
        now = time.monotonic()
        with self._lock:
            if self._first_at is None:
                self._first_at = now
            self._last_at = now
            self._latest = message
            self._count += 1

    def snapshot(self) -> ReceiveSnapshot:
        now = time.monotonic()
        with self._lock:
            count = self._count
            first_at = self._first_at
            last_at = self._last_at
            latest = self._latest

        elapsed = 0.0 if first_at is None or last_at is None else last_at - first_at
        rate = 0.0 if count < 2 or elapsed <= 0.0 else (count - 1) / elapsed
        age = None if last_at is None else max(0.0, now - last_at)
        return ReceiveSnapshot(count, elapsed, rate, latest, age)


def _linux_ipv4_address(interface: str) -> Optional[str]:
    if not sys.platform.startswith("linux"):
        return None

    try:
        import fcntl
        import struct

        request = struct.pack("256s", interface[:15].encode("utf-8"))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            response = fcntl.ioctl(sock.fileno(), 0x8915, request)
        return socket.inet_ntoa(response[20:24])
    except (ImportError, OSError):
        return None


def list_network_interfaces() -> List[InterfaceInfo]:
    interfaces: List[InterfaceInfo] = []
    for _, name in socket.if_nameindex():
        loopback = name == "lo" or name.startswith("lo")
        state_path = os.path.join("/sys/class/net", name, "operstate")
        try:
            with open(state_path, "r", encoding="utf-8") as state_file:
                state = state_file.read().strip()
        except OSError:
            state = "desconocido"
        interfaces.append(
            InterfaceInfo(
                name=name,
                state=state,
                ipv4=_linux_ipv4_address(name),
                loopback=loopback,
            )
        )
    return interfaces


def print_network_interfaces(interfaces: Sequence[InterfaceInfo]) -> None:
    print("Interfaces de red detectadas:")
    if not interfaces:
        print("  (ninguna)")
        return
    print("  nombre           estado        IPv4             observación")
    for item in interfaces:
        note = "loopback; no usar" if item.loopback else ""
        print(
            "  {name:<16} {state:<13} {ipv4:<16} {note}".format(
                name=item.name,
                state=item.state,
                ipv4=item.ipv4 or "-",
                note=note,
            )
        )


def _numeric_values(value: Any) -> Iterable[float]:
    if isinstance(value, (list, tuple)):
        for item in value:
            try:
                yield float(item)
            except (TypeError, ValueError):
                continue
    else:
        try:
            yield float(value)
        except (TypeError, ValueError):
            return


def motor_has_telemetry(motor: Any) -> bool:
    """Busca evidencia conservadora de que un slot representa un motor real."""

    scalar_fields = ("mode", "q", "dq", "ddq", "tau_est", "vol", "motorstate")
    array_fields = ("temperature", "sensor")
    for field in scalar_fields:
        for value in _numeric_values(getattr(motor, field, 0)):
            if math.isfinite(value) and abs(value) > 1e-8:
                return True
    for field in array_fields:
        for value in _numeric_values(getattr(motor, field, ())):
            if math.isfinite(value) and abs(value) > 1e-8:
                return True
    return False


def motor_values_are_finite(motor: Any) -> bool:
    for field in ("q", "dq", "ddq", "tau_est", "vol"):
        try:
            if not math.isfinite(float(getattr(motor, field))):
                return False
        except (AttributeError, TypeError, ValueError):
            return False
    return True


def classify_29_dof(motor_states: Sequence[Any]) -> Tuple[str, List[int]]:
    if len(motor_states) < EXPECTED_JOINT_COUNT:
        return "INCOMPATIBLE: se recibieron menos de 29 slots de motor", []

    detected = [
        index
        for index in OPTIONAL_29_DOF_INDICES
        if motor_has_telemetry(motor_states[index])
    ]
    if len(detected) == len(OPTIONAL_29_DOF_INDICES):
        return "CONFIRMADO: telemetría consistente con G1 de 29 DOF", detected
    if detected:
        return "PARCIAL: solo algunas articulaciones opcionales tienen señal", detected
    return (
        "INCONCLUSO: hay 29 slots, pero las articulaciones opcionales no muestran señal",
        detected,
    )


def _float_list(value: Any, length: int) -> List[float]:
    result: List[float] = []
    for item in list(value)[:length]:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            result.append(float("nan"))
    while len(result) < length:
        result.append(float("nan"))
    return result


def build_report(message: Any, snapshot: ReceiveSnapshot) -> Dict[str, Any]:
    motor_states = list(getattr(message, "motor_state", ()))
    variant, detected_optional = classify_29_dof(motor_states)
    first_29 = motor_states[:EXPECTED_JOINT_COUNT]
    nonfinite = [
        index for index, motor in enumerate(first_29) if not motor_values_are_finite(motor)
    ]

    imu = getattr(message, "imu_state", None)
    return {
        "message_count": snapshot.message_count,
        "rate_hz": snapshot.rate_hz,
        "last_age_s": snapshot.last_age_s,
        "mode_pr": int(getattr(message, "mode_pr", 0)),
        "mode_machine": int(getattr(message, "mode_machine", 0)),
        "tick": int(getattr(message, "tick", 0)),
        "motor_slots": len(motor_states),
        "variant": variant,
        "detected_optional_indices": detected_optional,
        "nonfinite_joint_indices": nonfinite,
        "imu_rpy_rad": _float_list(getattr(imu, "rpy", ()), 3),
        "imu_gyro_rad_s": _float_list(getattr(imu, "gyroscope", ()), 3),
        "imu_accel_m_s2": _float_list(getattr(imu, "accelerometer", ()), 3),
        "imu_quaternion": _float_list(getattr(imu, "quaternion", ()), 4),
        "imu_temperature": getattr(imu, "temperature", None),
        "motor_states": first_29,
    }


def _degrees(values: Sequence[float]) -> List[float]:
    return [math.degrees(value) for value in values]


def _selected_joint_indices(selection: str) -> Sequence[int]:
    if selection == "arms":
        return ARM_INDICES
    if selection == "optional":
        return OPTIONAL_29_DOF_INDICES
    if selection == "none":
        return ()
    return tuple(range(EXPECTED_JOINT_COUNT))


def print_report(report: Dict[str, Any], joint_selection: str = "all") -> None:
    print("\n=== Diagnóstico final de rt/lowstate ===")
    print(
        "Mensajes: {count} | frecuencia estimada: {rate:.1f} Hz | "
        "última muestra: {age:.3f} s".format(
            count=report["message_count"],
            rate=report["rate_hz"],
            age=report["last_age_s"] or 0.0,
        )
    )
    print(
        "mode_pr: {mode_pr} | mode_machine: {mode_machine} | tick: {tick}".format(
            **report
        )
    )
    print("Slots DDS: {0} | {1}".format(report["motor_slots"], report["variant"]))
    detected_names = [
        JOINT_NAMES[index] for index in report["detected_optional_indices"]
    ]
    print(
        "Articulaciones opcionales con señal: {0}".format(
            ", ".join(detected_names) if detected_names else "ninguna"
        )
    )

    rpy_deg = _degrees(report["imu_rpy_rad"])
    print(
        "IMU RPY: roll={0:+.2f}°, pitch={1:+.2f}°, yaw={2:+.2f}°".format(
            *rpy_deg
        )
    )
    print(
        "IMU gyro [rad/s]: {0:+.3f}, {1:+.3f}, {2:+.3f}".format(
            *report["imu_gyro_rad_s"]
        )
    )
    print(
        "IMU accel [m/s²]: {0:+.3f}, {1:+.3f}, {2:+.3f} | temp: {3}".format(
            *report["imu_accel_m_s2"],
            report["imu_temperature"],
        )
    )

    nonfinite = report["nonfinite_joint_indices"]
    if nonfinite:
        print("ALERTA: valores no finitos en índices: {0}".format(nonfinite))
    else:
        print("Valores q/dq/ddq/tau/vol finitos en las 29 articulaciones: sí")

    indices = _selected_joint_indices(joint_selection)
    if not indices:
        return

    print("\n idx articulación                 q [deg]   dq [rad/s]  tau_est   temp       mode")
    print(" --- -------------------------- --------- ----------- --------- ---------- ----")
    motor_states = report["motor_states"]
    for index in indices:
        if index >= len(motor_states):
            print(" {0:>3} {1:<26} SIN DATOS".format(index, JOINT_NAMES[index]))
            continue
        motor = motor_states[index]
        temperatures = "/".join(
            str(int(value)) for value in getattr(motor, "temperature", ())
        )
        print(
            " {idx:>3} {name:<26} {q:>+9.2f} {dq:>+11.3f} "
            "{tau:>+9.3f} {temp:<10} {mode:>4}".format(
                idx=index,
                name=JOINT_NAMES[index],
                q=math.degrees(float(getattr(motor, "q", float("nan")))),
                dq=float(getattr(motor, "dq", float("nan"))),
                tau=float(getattr(motor, "tau_est", float("nan"))),
                temp=temperatures or "-",
                mode=int(getattr(motor, "mode", 0)),
            )
        )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnóstico de solo lectura para G1 EDU+ 29 DOF. "
            "Se suscribe a rt/lowstate y nunca publica comandos."
        )
    )
    parser.add_argument(
        "-i",
        "--interface",
        help="interfaz Ethernet conectada al G1, por ejemplo eth0 o enp3s0",
    )
    parser.add_argument(
        "--list-interfaces",
        action="store_true",
        help="muestra las interfaces disponibles y termina",
    )
    parser.add_argument(
        "--domain-id",
        type=int,
        default=0,
        help="DDS domain ID (predeterminado: 0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="segundos de captura; 0 mantiene la captura hasta Ctrl+C (predeterminado: 8)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="espera máxima del primer mensaje en segundos (predeterminado: 5)",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=1.0,
        help="intervalo del indicador de recepción en segundos (predeterminado: 1)",
    )
    parser.add_argument(
        "--joints",
        choices=("all", "arms", "optional", "none"),
        default="all",
        help="articulaciones incluidas en la tabla final (predeterminado: all)",
    )
    args = parser.parse_args(argv)
    if args.duration < 0:
        parser.error("--duration no puede ser negativo")
    if args.timeout <= 0:
        parser.error("--timeout debe ser mayor que cero")
    if args.progress_interval <= 0:
        parser.error("--progress-interval debe ser mayor que cero")
    return args


def _wait_for_first_message(
    collector: LowStateCollector, timeout_s: float
) -> ReceiveSnapshot:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snapshot = collector.snapshot()
        if snapshot.message_count:
            return snapshot
        time.sleep(0.05)
    return collector.snapshot()


def run_diagnostic(args: argparse.Namespace) -> int:
    interfaces = list_network_interfaces()
    if args.list_interfaces:
        print_network_interfaces(interfaces)
        return 0

    if not args.interface:
        print_network_interfaces(interfaces)
        print("\nIndica la interfaz conectada al G1 con --interface NOMBRE.", file=sys.stderr)
        return 2

    interface_names = {item.name for item in interfaces}
    if args.interface not in interface_names:
        print(
            "La interfaz '{0}' no existe en este equipo.".format(args.interface),
            file=sys.stderr,
        )
        print_network_interfaces(interfaces)
        return 2

    try:
        from unitree_sdk2py.core.channel import (
            ChannelFactoryInitialize,
            ChannelSubscriber,
        )
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    except ImportError as exc:
        print(
            "No se pudo importar unitree_sdk2py: {0}\n"
            "Instala el SDK oficial desde su repositorio y vuelve a ejecutar.".format(
                exc
            ),
            file=sys.stderr,
        )
        return 1

    print("MODO SEGURO: solo suscripción; no se publicarán comandos.")
    print(
        "Inicializando DDS domain={0} en interfaz={1}...".format(
            args.domain_id, args.interface
        )
    )
    try:
        ChannelFactoryInitialize(args.domain_id, args.interface)
        collector = LowStateCollector()
        subscriber = ChannelSubscriber(LOWSTATE_TOPIC, LowState_)
        subscriber.Init(collector.on_message, 10)
    except Exception as exc:
        print("No se pudo inicializar DDS: {0}".format(exc), file=sys.stderr)
        return 2

    first = _wait_for_first_message(collector, args.timeout)
    if first.message_count == 0:
        print(
            "No llegó ningún mensaje de {topic} en {timeout:.1f} s.\n"
            "Comprueba el cable Ethernet, la interfaz elegida, la configuración "
            "IP y que el G1 esté encendido.".format(
                topic=LOWSTATE_TOPIC, timeout=args.timeout
            ),
            file=sys.stderr,
        )
        return 3

    print("Primer LowState recibido. Capturando telemetría...")
    started = time.monotonic()
    next_progress = started
    interrupted = False
    try:
        while args.duration == 0 or time.monotonic() - started < args.duration:
            now = time.monotonic()
            if now >= next_progress:
                snapshot = collector.snapshot()
                print(
                    "  recibidos={0:>6}  tasa={1:>7.1f} Hz  edad={2:.3f} s".format(
                        snapshot.message_count,
                        snapshot.rate_hz,
                        snapshot.last_age_s or 0.0,
                    )
                )
                next_progress = now + args.progress_interval
            time.sleep(0.05)
    except KeyboardInterrupt:
        interrupted = True
        print("\nCaptura interrumpida por el usuario.")

    snapshot = collector.snapshot()
    if snapshot.latest is None:
        print("No hay una muestra final disponible.", file=sys.stderr)
        return 3

    report = build_report(snapshot.latest, snapshot)
    print_report(report, args.joints)
    if snapshot.last_age_s is not None and snapshot.last_age_s > 1.0:
        print("\nALERTA: la telemetría dejó de actualizarse hace más de un segundo.")
        return 4
    if report["nonfinite_joint_indices"]:
        return 4
    return 0 if not interrupted or snapshot.message_count > 0 else 130


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_diagnostic(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
