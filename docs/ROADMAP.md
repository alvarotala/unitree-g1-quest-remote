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

En validación. El receptor HTTPS registra poses del visor y controladores,
botones, secuencia, timestamps, RTT, jitter y pérdida; impone una sola sesión,
escucha únicamente en la IP Quest indicada y permanece siempre `DISARMED`. Se
deben completar la captura nominal y las pruebas de pérdida/red descritas en
[`PHASE2_TEST_PLAN.md`](PHASE2_TEST_PLAN.md). Todavía no hay publicación DDS
hacia el robot.

## Fase 3 — retargeting y simulación

Convertir poses a objetivos articulares y validar en MuJoCo: coordenadas,
calibración neutral, límites, velocidad, aceleración, filtrado, singularidades,
watchdog y dead-man switch. El retargeting definitivo se ejecutará en PC2 y
recibirá intención cartesiana; Quest no enviará comandos de motor.

## Fase 4 — brazos reales mediante `rt/arm_sdk`

Se añadirá un ejecutable separado con activación explícita, mantener-presionado,
interpolación desde postura actual, límites conservadores, timeout de red,
parada local y prueba inicial con el robot soportado y sin caminar. El
diagnóstico seguirá siendo un binario separado e incapaz de mover el robot.
Solo PC2 podrá publicar `rt/arm_sdk`; ante pérdida de Quest o del router, el
supervisor local forzará una salida controlada a `DISARMED`.
