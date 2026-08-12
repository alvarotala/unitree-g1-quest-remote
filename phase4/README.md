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

Todavía no existe un publisher en este directorio. El siguiente incremento será
un ejecutable separado que primero se ejecute en modo `--dry-run`, lea
`rt/lowstate` y muestre los comandos que habría enviado. La publicación real
requerirá otra opción explícita y una prueba con el G1 correctamente soportado.
