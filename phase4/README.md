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
`A=StandUp`, `B=BalanceStand` (botones 4/5 del perfil `xr-standard`). En este
incremento solo se visualizan; ninguna
API de locomocion se invoca todavía. `Damp` y `ZeroTorque` necesitarán además
una habilitación local específica porque pueden provocar la caída del G1.

Antes de integrar la cámara se inspecciona PC2 sin iniciar streams:

```bash
./production/camera_probe.sh
```

La salida determina si el G1 expone V4L2 directamente o si ya existe un
servicio de video. No se reutiliza la API Go2 sin evidencia de compatibilidad.
Si `videohub_pc4` ya posee la cámara, su interfaz se inspecciona sin modificarla:

```bash
./production/video_hub_probe.sh
```

La suite inspecciona el fuente y falla si aparecen APIs de publisher, LowCmd o
el topic de comandos. La publicación real requerirá otro ejecutable, otra
opción explícita y una prueba con el G1 correctamente soportado.
