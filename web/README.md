# WebXR transport probe

Servidor HTTPS sin dependencias externas para la fase de transporte Quest. La
app captura poses y controles WebXR y guarda lotes NDJSON en `../logs/`. No
importa SDK2, no abre DDS y no contiene endpoints de movimiento.

```bash
python3 web/server.py
```

El servidor escucha en todas las interfaces y muestra la URL LAN. WebXR exige
un contexto seguro, por eso genera un certificado TLS local válido por 30 días.
En el Quest hay que aceptar una vez la advertencia del certificado local.
