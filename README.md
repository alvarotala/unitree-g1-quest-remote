# Unitree G1 Quest Remote

Control remoto experimental de un Unitree G1 EDU+ de 29 DOF desde Meta Quest.

La primera fase verifica telemetría real sin enviar órdenes. La arquitectura
operativa adoptada para todas las fases es:

```text
Meta Quest → router Wi-Fi portátil → PC2 → unitree_sdk2/CycloneDDS → G1
```

El gateway y toda la seguridad se ejecutan en PC2 aarch64. No se requiere una
computadora externa durante la operación. La red Quest permanece separada de
la red DDS interna del robot. Ver
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Seguridad actual

El ejecutable principal solamente crea un `ChannelSubscriber` de
`rt/lowstate`. No incluye publishers, mensajes de comando ni clientes que
cambien el modo del robot.

En PC2 no hay que ejecutar `apt install`, `apt upgrade`, `pip install` ni
`make install`. Se reutilizan SDK2 y CycloneDDS ya instalados por Unitree.

## Copiar a PC2 desde la estación de desarrollo

Ejemplo desde la estación donde está este repositorio:

```bash
rsync -av \
  --exclude '.git/' --exclude 'build/' \
  --exclude '__pycache__/' --exclude '.DS_Store' \
  "/Users/alvaro/Documents/unitree-g1-experiments/unitree-g1-quest-remote/" \
  unitree@192.168.123.164:~/unitree-g1-quest-remote/
```

La dirección corresponde a la PC2 ya probada en la red interna. Esta conexión
se usa para despliegue y diagnóstico; la estación de desarrollo no forma parte
de la arquitectura operativa.

## Compilar en PC2

```bash
ssh unitree@192.168.123.164
cd ~/unitree-g1-quest-remote
chmod +x production/build.sh
./production/build.sh
```

El script usa `/home/unitree/unitree_sdk2-main`, compila y ejecuta pruebas. No
instala ni modifica nada fuera del proyecto.

## Ejecutar el diagnóstico

Identificar primero la interfaz con `ip -br -4 addr`. En la unidad de referencia
es `eth0`. Con el robot encendido y apoyado de forma segura:

```bash
./build/cpp_lowstate_diagnostic/g1_lowstate_diagnostic \
  --interface eth0 --duration 8 --joints optional
```

Esto muestra cintura roll/pitch y muñecas pitch/yaw, las seis articulaciones
que distinguen los 29 DOF. Para todos los motores usar `--joints all`.

Si no llega el topic principal, probar:

```bash
./build/cpp_lowstate_diagnostic/g1_lowstate_diagnostic \
  --interface eth0 --topic rt/lf/lowstate --joints optional
```

## Pruebas locales sin SDK ni robot

```bash
cmake -S cpp_lowstate_diagnostic -B build/local-tests \
  -DBUILD_UNITREE_DIAGNOSTIC=OFF
cmake --build build/local-tests
ctest --test-dir build/local-tests --output-on-failure
```

Las pruebas validan el layout de 29 DOF, placeholders, valores no finitos y la
ausencia de capacidades de publicación en el ejecutable.

## Python anterior

`g1_readonly_diagnostic.py` se conserva como alternativa para una computadora
que ya tenga `unitree_sdk2_python`; no es la ruta recomendada para PC2.

## Próxima fase

Después de una captura correcta construiremos el receptor de poses de Quest
en PC2, completamente desacoplado del movimiento. Ver
[`docs/ROADMAP.md`](docs/ROADMAP.md) y la
[`arquitectura canónica`](docs/ARCHITECTURE.md).

## App WebXR en la Mac (desarrollo)

Para probar el transporte directamente desde un Quest conectado al mismo Wi-Fi:

```bash
python3 web/server.py
```

El comando muestra una URL HTTPS con la IP LAN. Esta app es de solo lectura:
captura tracking y guarda telemetría en `logs/`, pero no contiene SDK2, DDS ni
endpoints de movimiento. Ver [`web/README.md`](web/README.md).
