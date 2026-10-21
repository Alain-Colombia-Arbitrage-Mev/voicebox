# lauramedita · MiniMax HD

**Dicción en revisión:** el usuario reportó que la muestra se oye en español pero no se entiende con claridad. La coincidencia de una transcripción automática no certifica una locución inteligible. No debe describirse esta muestra como aprobada por escucha. Las nuevas comparaciones usan texto distinto de la referencia, velocidad 1× y audio sin reverberación añadida.

Referencia original en español. La muestra usa `speech-2.8-hd`, `language_boost=Spanish`, velocidad `0.92`, tono `0` y emoción automática. Se creó un clon nuevo desde la grabación original sin añadir un fragmento de audio/texto transcrito automáticamente. No contiene credenciales ni identificadores de clones remotos.

La referencia dura 27.716 s y la muestra 28.456 s. La transcripción local coincide con el guion en español, salvo una detección residual al final. Esta comprobación no certifica identidad, acento regional ni prosodia idéntica: las pausas e inflexiones pueden variar entre generaciones y textos.

```sh
.venv/bin/python scripts/install_library_voice.py --bundle assets/voices/lauramedita-minimax-hd --server http://127.0.0.1:17494
```

El instalador agrega la referencia, conserva velocidad/tono/emoción y registra una muestra ya generada con su idioma y motor, sin llamar a MiniMax. Usa una biblioteca sin otro perfil del mismo nombre o configura el perfil existente para MiniMax. El original permanece separado de la muestra sintetizada.

Documentación del proveedor: [clonación](https://platform.minimax.io/docs/api-reference/voice-cloning-clone) y [síntesis](https://platform.minimax.io/docs/api-reference/speech-t2a-http).
