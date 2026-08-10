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
`make install`. Se reutiliza CycloneDDS instalado por Unitree y una copia local
del SDK2 oficial con los mensajes `unitree/idl/hg` requeridos por G1.

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

## Preparar SDK2 para G1 sin Internet en PC2

El SDK preinstalado en `/home/unitree/unitree_sdk2-main` de la unidad de
referencia solo contiene mensajes `unitree/idl/go2`; no incluye
`unitree/idl/hg/LowState_.hpp` y no sirve para compilar el diagnóstico G1. No se
debe modificar ni reemplazar.

En una computadora con Internet, descargar el SDK oficial en paralelo:

```bash
cd ~/Documents/unitree-g1-experiments
git clone --depth 1 \
  https://github.com/unitreerobotics/unitree_sdk2.git \
  unitree_sdk2-g1
```

Después de conectarse a la red de PC2, transferirlo sin necesidad de Internet
en el robot:

```bash
rsync -avh --progress \
  --exclude '.git/' \
  unitree_sdk2-g1/ \
  unitree@192.168.123.164:/home/unitree/unitree_sdk2-g1/
```

Validar en PC2 antes de compilar:

```bash
test -f /home/unitree/unitree_sdk2-g1/include/unitree/idl/hg/LowState_.hpp \
  && echo "SDK G1 correcto" \
  || echo "Falta LowState G1"

find /home/unitree/unitree_sdk2-g1/lib \
  -name libunitree_sdk2.a -print
```

En PC2 aarch64 debe aparecer, como mínimo,
`lib/aarch64/libunitree_sdk2.a`. Estos pasos solo copian e inspeccionan archivos;
no se comunican con el robot ni instalan el SDK en el sistema.

## Compilar en PC2

```bash
ssh unitree@192.168.123.164
cd ~/unitree-g1-quest-remote
chmod +x production/build.sh
./production/build.sh
```

El script usa `/home/unitree/unitree_sdk2-g1`, compila y ejecuta las pruebas.
No instala ni modifica nada fuera del proyecto. Para usar otra copia compatible
del SDK, indicar su ruta explícitamente:

```bash
UNITREE_SDK_ROOT=/ruta/al/unitree_sdk2 ./production/build.sh
```

Las advertencias `named variadic macros` procedentes de headers del SDK oficial
no impiden generar el ejecutable. En CMake 3.16, ejecutar `ctest --test-dir ...`
puede terminar buscando pruebas en el directorio equivocado; el script evita
ese problema entrando primero al directorio de compilación.

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
(cd build/local-tests && ctest --output-on-failure)
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
