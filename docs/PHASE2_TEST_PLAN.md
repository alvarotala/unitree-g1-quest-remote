# Plan de pruebas — Fase 2 Quest sin movimiento

## Objetivo y frontera de seguridad

Validar el transporte Quest → router → PC2 antes de implementar retargeting o
publicación DDS. `web/server.py` no importa SDK2, no abre CycloneDDS, no contiene
endpoints de movimiento y reporta siempre `safetyState: DISARMED`.

El G1 puede permanecer apagado para estas pruebas. Si está encendido, no es
necesario ejecutar `g1_lowstate_diagnostic` al mismo tiempo.

## 1. Preparar la red

PC2 debe tener una interfaz para la red interna del robot y otra para la red
Quest. Identificar ambas:

```bash
ip -br -4 addr
ip route
sysctl net.ipv4.ip_forward
ip -d link show type bridge
```

Criterios:

- `eth0`/`192.168.123.0/24` continúa siendo la red interna del G1;
- Quest y PC2 comparten otra subred dedicada;
- `net.ipv4.ip_forward = 0`;
- no existe un bridge entre ambas interfaces.

Desde otra computadora conectada al mismo Wi-Fi que Quest, verificar que la
red interna del robot no sea alcanzable. El acceso a `192.168.123.164` debe
fallar:

```bash
ping -c 3 192.168.123.164
```

## 2. Iniciar el receptor en PC2

Sustituir el marcador por la dirección real de PC2 en la red Quest:

```bash
cd ~/unitree-g1-quest-remote
python3 -m unittest discover -s tests -v
python3 web/server.py --ip IP_PC2_EN_LA_RED_QUEST
```

En otra terminal de PC2 confirmar que el puerto está ligado solo a esa IP:

```bash
ss -ltn | grep ':8443'
ss -lunp | grep python3
curl -k https://IP_PC2_EN_LA_RED_QUEST:8443/api/status
```

El estado inicial esperado es `linkState: DISCONNECTED` y
`safetyState: DISARMED`. El primer comando debe mostrar únicamente la IP Quest
en TCP 8443; el segundo no debe mostrar sockets UDP del receptor Python.

## 3. Captura nominal

1. Abrir en Quest Browser la URL HTTPS mostrada por PC2.
2. Aceptar el certificado local si el navegador lo solicita.
3. Sujetar ambos controladores y pulsar **Entrar en VR**.
4. Mover lentamente visor y controles durante al menos 60 segundos.
5. Accionar individualmente gatillos, grip, botones y sticks, sin relación con
   el robot.
6. Salir de VR.

Durante la captura deben verse HMD, control izquierdo y control derecho como
`VÁLIDO`; seguridad debe permanecer en `DISARMED`.

Analizar el archivo indicado por la interfaz:

```bash
python3 web/analyze_logs.py logs/quest-ID_DE_SESION.ndjson --check
```

La captura nominal se acepta cuando termina con `Acceptance: PASS`.

## 4. Pérdida y recuperación

Repetir sesiones separadas y provocar cada condición:

1. soltar o esconder cada controlador por separado;
2. salir de VR y cerrar Quest Browser;
3. desactivar y reactivar Wi-Fi en Quest;
4. reiniciar el router portátil;
5. intentar abrir simultáneamente una segunda sesión.

Después de interrumpir el stream durante más de 750 ms, consultar:

```bash
curl -k https://IP_PC2_EN_LA_RED_QUEST:8443/api/status
```

Debe reportar `linkState: DISCONNECTED` y `safetyState: DISARMED`. Una segunda
sesión concurrente recibe HTTP 409; una sesión nueva puede entrar después del
timeout. La recuperación nunca cambia automáticamente a un estado armado.

## 5. Criterio de cierre

La Fase 2 se considera terminada únicamente cuando:

- la captura nominal pasa los umbrales del analizador;
- ambos controladores y sus entradas aparecen en el NDJSON;
- todas las pruebas de pérdida terminan en `DISARMED`;
- el servidor escucha solo en la interfaz Quest;
- IP forwarding está desactivado y no existe bridge hacia la red DDS;
- el proceso no carga `libunitree_sdk2` ni abre puertos DDS.

La Fase 3 seguirá usando estos logs como entrada para retargeting en simulación;
todavía no se habilitará movimiento real.
