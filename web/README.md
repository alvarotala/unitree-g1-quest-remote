# WebXR transport probe — Fase 2

Servidor HTTPS sin dependencias externas para la fase de transporte Quest. La
app captura poses y controles WebXR y guarda lotes NDJSON en `../logs/`. No
importa SDK2, no abre DDS y no contiene endpoints de movimiento.

En PC2, identificar primero la interfaz de la red Quest. No usar la dirección
de `eth0` en `192.168.123.0/24`, que pertenece a la red interna del G1:

```bash
ip -br -4 addr
python3 web/server.py --ip IP_PC2_EN_LA_RED_QUEST
```

El servidor escucha solamente en la IP indicada y muestra la URL que debe
abrirse en Quest Browser. WebXR exige un contexto seguro, por eso genera un
certificado TLS local válido por 30 días. En Quest hay que aceptar una vez la
advertencia del certificado local y luego pulsar **Entrar en VR**.

La pantalla y los logs muestran frecuencia, RTT HTTPS, jitter, pérdida de
secuencias, tracking del visor/controladores y botones. El estado de seguridad
permanece siempre en `DISARMED`; si no hay stream reciente, el enlace cambia a
`DISCONNECTED`. Solo se admite una sesión Quest activa a la vez.

En Fase 4, cuando existe un consumidor local, el servidor replica únicamente
sesión, secuencia, validez de tracking y ambos grips a través del socket Unix
`/tmp/g1_quest_safety.sock`. Continúa sin importar SDK2, abrir DDS o aceptar
comandos de motor; si el socket no existe, el servidor funciona normalmente.

Para inspeccionar el estado desde PC2:

```bash
curl -k https://IP_PC2_EN_LA_RED_QUEST:8443/api/status
```

Para analizar una captura de al menos 30 segundos con ambos controles visibles:

```bash
python3 web/analyze_logs.py logs/quest-ID_DE_SESION.ndjson --check
```

Los umbrales conservadores iniciales son: al menos 60 Hz, jitter máximo de
5 ms, pérdida máxima de 1%, RTT p95 máximo de 100 ms, cero duplicados/fuera de
orden, visor válido al menos 99% y cada controlador al menos 95%. Ver el plan
completo en [`../docs/PHASE2_TEST_PLAN.md`](../docs/PHASE2_TEST_PLAN.md).
