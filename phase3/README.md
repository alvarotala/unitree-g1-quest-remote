# Fase 3 — retargeting y MuJoCo offline

Esta fase se ejecuta en la Mac y no contiene SDK2, CycloneDDS, publishers ni
conexiones al robot. Convierte un log NDJSON de Quest en una trayectoria de 14
articulaciones y permite visualizarla con el modelo oficial G1 de 29 DOF.

La Fase 2 fue cerrada por decisión del proyecto con pausas y pérdidas de tracking
documentadas. Este replay las conserva como entradas inválidas/watchdog en vez
de ocultarlas. La Fase 4 permanece fuera del alcance de esta simulación.

## Preparación local

Desde `unitree-g1-experiments`:

```bash
git clone --depth 1 https://github.com/unitreerobotics/unitree_mujoco.git
cd unitree-g1-quest-remote
python3 -m venv .venv-phase3
.venv-phase3/bin/python -m pip install -r requirements-phase3.txt
```

El modelo esperado es
`../unitree_mujoco/unitree_robots/g1/scene_29dof.xml`.

## Copiar y analizar un log

La ruta corta descarga, procesa y abre el visualizador con un solo comando:

```bash
./production/phase3_view_log.sh --speed 2 quest-ID.ndjson
```

El reporte y la trayectoria reciben el ID del log para no sobrescribir pruebas
anteriores. Si una captura no mantuvo ambos grips, puede inspeccionarse solo en
simulacion con `--ignore-deadman`; sin esa opcion, un replay rechazado no abre
el visualizador.

```bash
./production/phase3_view_log.sh \
  --ignore-deadman --speed 2 quest-ID.ndjson
```

La forma manual equivalente es:

```bash
rsync -av \
  unitree@192.168.123.164:~/unitree-g1-quest-remote/logs/quest-ID.ndjson \
  logs/

.venv-phase3/bin/python -m phase3.replay \
  logs/quest-ID.ndjson \
  --output logs/phase3-report.json \
  --trajectory logs/phase3-trajectory.npz
```

Por defecto, la simulación solo está activa mientras ambos botones grip
(`buttons[1]`) están presionados. Para investigar un log antiguo que no mantuvo
el dead-man, se permite exclusivamente offline:

```bash
.venv-phase3/bin/python -m phase3.replay \
  logs/quest-ID.ndjson \
  --simulation-ignore-deadman \
  --trajectory logs/phase3-trajectory.npz
```

Visualizar:

```bash
.venv-phase3/bin/mjpython -m phase3.view_trajectory \
  logs/phase3-trajectory.npz
```

El visor recorta por defecto los segundos anteriores al primer dead-man y los
posteriores al ultimo. Para revisar toda la sesion WebXR se puede agregar
`--full-session`. La calibracion neutral se toma exactamente del primer frame
con tracking valido y ambos grips presionados.

En macOS la ventana MuJoCo requiere `mjpython`; el visor intenta relanzarse
automáticamente si se invoca con el Python normal, pero usar el comando anterior
es la ruta explícita recomendada.

## Controles implementados

- conversión WebXR (`+X` derecha, `+Y` arriba, `-Z` frente) a G1
  (`+X` frente, `+Y` izquierda, `+Z` arriba);
- calibración neutral relativa al visor;
- escala cartesiana conservadora de 0.25 para adaptar el espacio Quest al
  alcance del brazo G1;
- IK damped-least-squares para 7 DOF por brazo, priorizando posición y
  aplicando por defecto el 35% de la rotación relativa de los controles para
  evitar que orientaciones humanas inalcanzables retuerzan todo el brazo;
- preferencia secundaria por la postura neutral del G1 para evitar soluciones
  extremas cuando varias configuraciones alcanzan la misma posición de mano;
- margen de límites articulares del modelo oficial;
- separación mínima de 25 mm entre brazos y torso, cabeza o pelvis, y entre
  ambos brazos; cada paso se recorta antes del contacto y queda registrado;
- límite de velocidad de 1 rad/s y aceleración de 3 rad/s²;
- filtro pasa-bajos de 5 Hz;
- watchdog de 100 ms;
- rearme mediante soltar y volver a presionar el dead-man después de pérdida;
- reporte de tracking inválido, watchdog, error IK y singularidades.
- rechazo de cualquier trayectoria que conserve una autocollision peligrosa.

Estos valores son deliberadamente conservadores y todavía no constituyen una
autorización para controlar hardware.
