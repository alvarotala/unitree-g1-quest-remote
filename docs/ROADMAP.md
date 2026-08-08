# Arquitectura y fases de seguridad

## Configuración confirmada

- Unitree G1 EDU+ de 29 DOF, firmware `v1.5.3`.
- Manos simples pasivas.
- PC2 aarch64 con SDK2 C++ y CycloneDDS ya instalados por Unitree.
- SDK verificado en `/home/unitree/unitree_sdk2-main`.

Las manos no tienen actuadores. El primer alcance de Quest será el seguimiento
de los dos brazos de 7 DOF; cintura y piernas permanecen bajo control nativo.

## Fase 1 — telemetría DDS de solo lectura

Estado actual. `g1_lowstate_diagnostic` escucha `rt/lowstate` y verifica tasa
DDS, IMU, 29 estados articulares, articulaciones opcionales y valores no
finitos. No contiene publishers ni clientes de cambio de modo.

## Fase 2 — transporte Quest sin movimiento

Crear un receptor que solo registre poses del visor y controladores, botones,
secuencia, timestamps, latencia, jitter y pérdida. La pérdida del stream debe
producir `DISARMED`; todavía no habrá publicación DDS hacia el robot.

## Fase 3 — retargeting y simulación

Convertir poses a objetivos articulares y validar en MuJoCo: coordenadas,
calibración neutral, límites, velocidad, aceleración, filtrado, singularidades,
watchdog y dead-man switch.

## Fase 4 — brazos reales mediante `rt/arm_sdk`

Se añadirá un ejecutable separado con activación explícita, mantener-presionado,
interpolación desde postura actual, límites conservadores, timeout de red,
parada local y prueba inicial con el robot soportado y sin caminar. El
diagnóstico seguirá siendo un binario separado e incapaz de mover el robot.

