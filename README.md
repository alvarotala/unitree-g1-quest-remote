# Diagnóstico de solo lectura — Unitree G1 EDU+ 29 DOF

Este repositorio comienza con una prueba segura para verificar la comunicación
DDS con el G1 antes de implementar el control remoto desde Meta Quest.

`g1_readonly_diagnostic.py` **solo se suscribe** al topic `rt/lowstate`. No crea
publishers, no envía `LowCmd` y no cambia el modo de movimiento.

## Requisitos

- Una computadora con Ubuntu conectada por Ethernet al G1.
- Python 3.8 o posterior.
- La versión actual de
  [`unitree_sdk2_python`](https://github.com/unitreerobotics/unitree_sdk2_python),
  instalada desde el repositorio oficial siguiendo su README.

Ejemplo de instalación del SDK:

```bash
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
python3 -m pip install -e .
```

Si la instalación informa que no encuentra CycloneDDS, sigue las instrucciones
de instalación de CycloneDDS incluidas en el README oficial del SDK.

## Uso

Primero identifica el nombre de la interfaz Ethernet:

```bash
python3 g1_readonly_diagnostic.py --list-interfaces
```

Luego ejecuta una captura de ocho segundos, sustituyendo `eth0` por la interfaz
correcta:

```bash
python3 g1_readonly_diagnostic.py --interface eth0
```

Para mostrar solamente las seis articulaciones que distinguen al G1 de 29 DOF:

```bash
python3 g1_readonly_diagnostic.py --interface eth0 --joints optional
```

Para capturar hasta pulsar `Ctrl+C`:

```bash
python3 g1_readonly_diagnostic.py --interface eth0 --duration 0
```

El programa muestra:

- frecuencia aproximada de recepción;
- `mode_pr`, `mode_machine` y `tick`;
- orientación, giróscopo, acelerómetro y temperatura de la IMU;
- posición, velocidad, torque estimado, temperatura y modo de los 29 motores;
- evidencia de telemetría para cintura roll/pitch y muñecas pitch/yaw.

El mensaje DDS reserva 35 slots de motor para la familia `unitree_hg`. Por ello,
tener una lista de 35 elementos no confirma por sí solo la variante del robot:
el diagnóstico comprueba si los índices opcionales entregan señal real.

## Si no llegan mensajes

1. Confirma que el G1 esté encendido.
2. Revisa el cable y que la interfaz figure como `up`.
3. Confirma que elegiste la interfaz Ethernet conectada al robot, no Wi-Fi ni
   `lo`.
4. Revisa la configuración IP recomendada por Unitree.
5. Ejecuta nuevamente con un tiempo de espera mayor:

```bash
python3 g1_readonly_diagnostic.py --interface eth0 --timeout 15
```

Esta prueba no requiere desactivar `ai_sport` ni entrar en modo debug.

## Pruebas locales

Las pruebas usan mensajes simulados y no necesitan un robot ni el SDK:

```bash
python3 -m unittest discover -s tests -v
```
