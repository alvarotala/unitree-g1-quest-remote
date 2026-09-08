# Fase 4 — supervisor físico y `rt/arm_sdk`

La Fase 4 comienza con lógica C++ sin DDS ni publishers. El primer objetivo es
demostrar que ninguna condición individual puede habilitar comandos y que toda
pérdida de seguridad desarma o genera `FAULT` localmente.

## Estado actual

Implementado y probado sin robot:

- estados `DISCONNECTED`, `DISARMED`, `ARMING`, `ARMED` y `FAULT`;
- habilitación local independiente del Quest;
- armado después de 1 s de condiciones válidas continuas;
- dead-man, tracking, TTL de Quest y LowState reciente;
- `FAULT` enclavado ante LowState u objetivo inválido;
- reset de fallo únicamente con habilitación local apagada;
- interpolación iniciada desde posiciones medidas;
- límites iniciales de 0.25 rad/s y 0.5 rad/s²;
- rechazo de saltos mayores a 0.15 rad respecto del comando anterior.

Compilar y ejecutar las pruebas en cualquier computadora:

```bash
./production/build_phase4_safety.sh
```

## Dry-run con LowState real

En PC2 puede compilarse el ejecutable read-only:

```bash
./production/build_phase4_dry_run.sh
./build/phase4/g1_arm_dry_run --interface eth0 --duration 8
```

El modo normal debe permanecer `DISCONNECTED` y mostrar `WOULD_PUBLISH=no`.
Para ejercitar la máquina de estados con señales Quest simuladas, sin publicar:

```bash
./build/phase4/g1_arm_dry_run \
  --interface eth0 --duration 8 --exercise-arming
```

Para usar tracking y ambos grips reales del Quest, iniciar primero el servidor
WebXR actualizado y luego el dry-run con habilitacion local explicita:

```bash
python3 web/server.py --ip 192.168.100.209

# En otra terminal de PC2:
./build/phase4/g1_arm_dry_run \
  --interface eth0 --duration 30 --quest-live --local-enable
```

El servidor envia por `/tmp/g1_quest_safety.sock` únicamente sesión, secuencia,
tracking y dead-man. El socket es local, tiene permisos `0600` y no atraviesa
ninguna interfaz de red. Un datagrama con más de 250 ms desarma el supervisor.
`--local-enable` pertenece al proceso de PC2: el Quest no puede sustituirlo.
El dry-run devuelve su estado mediante un archivo local efímero; el panel VR
muestra estado, motivo, grips individuales, tracking, edades y `WOULD_PUBLISH`.

El dry-run de locomocion interpreta el stick izquierdo como avance/lateral y
el stick derecho horizontal como giro, con zona muerta de 15% y limites
iniciales de 0.15 m/s, 0.10 m/s y 0.25 rad/s. Ambos grips son el dead-man. Las
intenciones de modo requieren ambos triggers: `X=Damp`, `Y=ZeroTorque`,
`A=StandUp`, `B=BalanceStand` (botones 4/5 del perfil `xr-standard`). En el
dry-run solo se visualizan y no se invoca ninguna API. `Damp` y `ZeroTorque`
necesitan además
una habilitación local específica porque pueden provocar la caída del G1.

## Locomoción real desde VR

La locomoción real está aislada en `g1_vr_locomotion`; ejecutar el servidor o
el dry-run nunca la inicia. Compilarla en PC2 tampoco envía comandos:

```bash
./production/build_phase4_locomotion.sh
```

El binario exige habilitación local y la frase exacta `G1_VR_MOTION`. Antes de
armar requiere tracking, LowState válido, ambos grips y los sticks centrados
durante un segundo. Después renueva `SetVelocity(vx, vy, omega, 0.25)` cada
100 ms. Al soltar un grip, perder tracking, vencer el stream, recibir una señal
de salida o terminar el proceso llama `StopMove()`; la duración corta limita
también un fallo abrupto del proceso.

`StandUp` y `BalanceStand` requieren ambos triggers más A o B durante 1.5 s,
con sticks centrados. `Damp` y `ZeroTorque` están bloqueados salvo que el proceso
se inicie además con `--allow-fall-modes --authorize-fall-modes G1_CAN_FALL`;
pueden hacer caer inmediatamente un robot sin soporte.

El dry-run y el binario live no pueden ejecutarse juntos: ambos poseen
`/tmp/g1_quest_safety.sock`. Detener uno antes de iniciar el otro. Cuando el
live está activo, el panel VR muestra `LIVE LOCOMOTION · COMANDOS REALES`.

Para operación sin sesión SSH abierta se usan los scripts administrados. Se
ejecutan únicamente después de poner al G1 de pie en suelo plano, despejar el
área y disponer de un observador junto al control Unitree:

```bash
./production/start_vr_live.sh --confirm-standing G1_STANDING_CLEAR
./production/status_vr_live.sh
./production/stop_vr_live.sh
```

El arranque deja WebXR y locomoción bajo `nohup`, guarda PID en `run/` y logs
en `logs/services/`. Puede hacerse por SSH sobre Wi-Fi a `192.168.100.209`; el
cable de la Mac no forma parte del control. La parada termina primero la
locomoción para que ejecute `StopMove()` y después el servidor WebXR.

### Entrada a locomoción en firmware 1.5.3

En el G1 EDU+ 29 DOF probado, las versiones API cliente/servidor coinciden en
`1.0.0.0`, pero la app deja el robot en FSM `802`. En software 1.5.3,
`LocoClient.Start()` solicita FSM `500` y puede retornar éxito aunque el estado
no cambie. La vía experimental verificada por la comunidad para llegar al
control caminable es `Damp/FSM 1 -> StandUp/FSM 4 -> FSM 501`, comprobando el
estado tras cada etapa y reintentando 501.

La transición se mantiene separada del servicio background porque `Damp` puede
hacer caer el robot. Para la primera prueba, poner el control oficial en modo
movimiento (`R2+A`, no el modo debug `L2+R2`), sujetar físicamente el G1 con
gantry/soporte, disponer de observador y parada de emergencia, y ejecutar en
foreground:

```bash
./production/enter_fsm501.sh G1_SUPPORTED_CLEAR
./build/phase4/g1_loco_readonly_probe --interface eth0
```

La prueba no envía velocidad: termina con `StopMove()` y debe imprimir
`CONFIRMADO: FSM 501 activo`. Solo después, y mientras el probe siga mostrando
`GetFsmId ... value=501`, se puede iniciar `start_vr_live.sh`. El servicio live
no ejecuta la transición física y se bloquea ante cualquier FSM distinto de
501.

La cámara frontal se inspeccionó primero sin iniciar streams:

```bash
./production/camera_probe.sh
```

La salida determina si el G1 expone V4L2 directamente o si ya existe un
servicio de video. No se reutiliza la API Go2 sin evidencia de compatibilidad.
`videohub_pc4` posee `/dev/video4`; su interfaz se inspecciona sin modificarla:

```bash
./production/video_hub_probe.sh
```

El hub emite H.264 1280×720 a 15 FPS en RTP multicast
`230.1.1.1:1720` por `eth0`. La recepción pasiva y las capacidades WebRTC se
validan con:

```bash
./production/rtp_camera_probe.sh --duration 10
./production/webrtc_capability_probe.sh
```

El gateway de `web/server.py` reutiliza ese H.264 sin transcodificar y sin
abrir ningún dispositivo V4L2. El video se muestra tanto en la página 2D como
en un panel dentro de VR.

La suite inspecciona el fuente y falla si aparecen APIs de publisher, LowCmd o
el topic de comandos. La publicación real requerirá otro ejecutable, otra
opción explícita y una prueba con el G1 correctamente soportado.
