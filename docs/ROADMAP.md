# Arquitectura y fases de seguridad

## Configuración confirmada

- Unitree G1 EDU+ de 29 DOF, firmware `v1.5.3`.
- Manos simples pasivas.
- PC2 aarch64 con SDK2 C++ y CycloneDDS ya instalados por Unitree.
- SDK2 oficial con soporte G1/HG verificado en
  `/home/unitree/unitree_sdk2-g1`; se transfirió a PC2 sin instalarlo en el
  sistema. El SDK preinstalado `unitree_sdk2-main` solo contiene IDL de Go2.
- Arquitectura canónica: Quest → router Wi-Fi portátil → PC2 → DDS → G1.
- Gateway, retargeting y supervisor de seguridad ejecutados en PC2.

Las manos no tienen actuadores. El primer alcance de Quest será el seguimiento
de los dos brazos de 7 DOF; cintura y piernas permanecen bajo control nativo.
La red Quest estará separada de la red DDS interna según
[`ARCHITECTURE.md`](ARCHITECTURE.md). No se incorporará una computadora externa
al camino de control.

## Fase 1 — telemetría DDS de solo lectura

Completada. `g1_lowstate_diagnostic` confirmó telemetría G1 de 29 DOF a
aproximadamente 1042 Hz, seis articulaciones opcionales activas, valores finitos
y cero errores en los motores inspeccionados. No contiene publishers ni
clientes de cambio de modo.

## Fase 2 — transporte Quest sin movimiento

Completada por decisión del proyecto. El receptor HTTPS registró poses,
controles, RTT, jitter y secuencias sobre `pepe`, ligado exclusivamente a
`wlan0`, con forwarding desactivado y estado permanente `DISARMED`. La captura
de cierre obtuvo 0% de pérdida, cero duplicados y cero paquetes fuera de orden.
Se aceptaron como desviaciones conocidas una pausa WebXR de 2355.8 ms y tracking
intermitente (izquierdo 32.926%, derecho 71.781%); deben permanecer visibles en
simulación y no se reinterpretan como una prueba nominal perfecta. Ver
[`PHASE2_TEST_PLAN.md`](PHASE2_TEST_PLAN.md).

## Fase 3 — retargeting y simulación

Activa. El primer replay usa el modelo oficial G1 29 DOF en
MuJoCo e implementa coordenadas, calibración neutral, IK de 7 DOF por brazo,
límites, velocidad, aceleración, filtrado, singularidades, watchdog y dead-man.
Ver [`../phase3/README.md`](../phase3/README.md). No importa SDK2 ni se comunica
con el robot. El replay `msnihs1o-0079336a`, con escala cartesiana 0.25, fue
aceptado para simulación: error p95 de 8.65 mm, error máximo de 71.64 mm, cero
fallos IK, cero alertas finales de singularidad y un watchdog correspondiente a
la pausa WebXR conocida. Falta inspección visual de la trayectoria. Fase 4
sigue fuera del alcance actual.

## Fase 4 — brazos reales mediante `rt/arm_sdk`

Se añadirá un ejecutable separado con activación explícita, mantener-presionado,
interpolación desde postura actual, límites conservadores, timeout de red,
parada local y prueba inicial con el robot soportado y sin caminar. El
diagnóstico seguirá siendo un binario separado e incapaz de mover el robot.
Solo PC2 podrá publicar `rt/arm_sdk`; ante pérdida de Quest o del router, el
supervisor local forzará una salida controlada a `DISARMED`.
