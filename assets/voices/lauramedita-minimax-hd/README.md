# lauramedita · MiniMax HD · Referencia B

Voz de meditación en español. El usuario eligió la comparación **B · Referencia limpiada** y aprobó la nueva prueba con texto distinto de la referencia el 21 de octubre de 2026.

El paquete conserva por separado:

- `original.mp3`: grabación completa aportada por el usuario.
- `reference.wav`: fragmento original utilizado para crear B, sin cambio de tono o velocidad. La limpieza la realiza MiniMax al clonar; este archivo conserva la referencia previa al procesamiento del proveedor.
- `comparison-b.wav`: comparación B elegida por el usuario.
- `preview.wav`: nueva locución con la misma voz B y el texto indicado en `voice.json`.

Configuración guardada: `speech-2.8-hd`, español, velocidad `1.0`, tono `0`, emoción automática y sin efectos añadidos. La clonación usa `need_noise_reduction=true` y `need_volume_normalization=true`; esas opciones se conservan al guardar, exportar, importar y recuperar un clon caducado. La caché distingue una referencia con limpieza de la misma referencia sin limpieza.

## Instalar

Actualiza primero el servidor Voicebox para que admita `minimax_clone_options` y ejecuta desde la raíz del repositorio:

```sh
.venv/bin/python scripts/install_library_voice.py --bundle assets/voices/lauramedita-minimax-hd --server http://127.0.0.1:17494
```

Para la aplicación de escritorio, utiliza su servidor `http://127.0.0.1:17493`. El instalador registra la referencia, la configuración y la muestra ya generada sin llamar a MiniMax; repetirlo conserva el perfil y evita duplicar la misma muestra. Las nuevas generaciones requieren la clave y el saldo de MiniMax de cada instalación. El clon remoto se crea en esa cuenta; no se incluyen credenciales ni identificadores remotos.

La aprobación corresponde a estas muestras. El ritmo, las pausas y las inflexiones de textos nuevos pueden variar y requieren escucha. La coincidencia de una transcripción automática comprueba el contenido, no una prosodia idéntica.

Documentación del proveedor: [clonación y limpieza de referencia](https://platform.minimax.io/docs/api-reference/voice-cloning-clone).
