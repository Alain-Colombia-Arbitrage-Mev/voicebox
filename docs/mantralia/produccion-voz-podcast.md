# Audio promocional: mezcla y voces originales

## Mezcla del archivo entregado

Se conserva la interpretación, el texto, el ritmo y la identidad del hablante.
El procesamiento es local: filtro de graves por debajo de 65 Hz, un refuerzo
suave de cuerpo a 180 Hz, limpieza a 320 Hz, agudos algo más suaves, compresión
ligera y nivel controlado. No se cambia la altura ni se estira el tiempo.

Archivo: `data/mantralia/referencia-podcast/audio-mezcla-calida.wav`.
Duración decodificada: 30.198 s; mono, 44.1 kHz, PCM de 24 bits.
Nivel RMS aproximado: -19.2 dBFS (original -22.1); pico 0.644, sin saturación.
Esto modifica el color y la presencia de la grabación. No puede reescribir los
énfasis o la emoción que ya interpretó el hablante.

```bash
.venv/bin/python scripts/refine_podcast_audio.py INPUT.mp3 --output OUTPUT.wav
```

## Alternativas de locución

Se diseñan dos identidades sintéticas originales por descripción textual:

- **Narrador original cercano:** hombre adulto, español colombiano nativo,
  registro ligero a medio, dicción clara, conexión emocional y seguridad.
- **Narradora original cercana:** mujer adulta, español colombiano nativo,
  registro medio con cuerpo, calidez luminosa e intención editorial.

Ambas usan un ritmo conectado de podcast y énfasis persuasivo moderado.
La grabación entregada no se sube como referencia ni se usa para clonar a su
hablante. La cercanía buscada es de formato y recursos generales de narración.
El acento y la calidad expresiva requieren escucha.

Las muestras usan una adaptación breve del mensaje de Mantralia, distinta de
la transcripción automática: se conserva deseo → intención → acción y el CTA.
Texto exacto: `data/mantralia/referencia-podcast/guion-alternativas.txt`.
Los perfiles y las generaciones se guardan en la biblioteca local de Voicebox.

La [implementación oficial de MiniMax Voice Design](https://github.com/MiniMax-AI/MiniMax-MCP/blob/main/minimax_mcp/server.py)
utiliza `prompt` y `preview_text`. El helper solo proporciona esas descripciones
originales; reutiliza IDs guardados y no contiene claves en el código.

```bash
# Requiere el backend Voicebox en ejecución y consume crédito MiniMax:
PYTHONPATH=. .venv/bin/python scripts/create_original_podcast_voices.py
```

La voz y el audio generado se conservan en archivos separados de la mezcla
original. Los metadatos indican su procedencia sintética y la revisión auditiva
pendiente. Ni las credenciales ni los archivos de audio se incluyen en Git.

## Resultados

- Mezcla cálida: `audio-mezcla-calida.wav`, 30.198 s, 44.1 kHz.
- Narrador original: `narrador-cercano.wav`, 25.136 s, 32 kHz.
- Narradora original: `narradora-cercana.wav`, 25.751 s, 32 kHz.

Las dos generaciones finalizaron correctamente y sus perfiles tienen una
referencia sintética propia guardada. Verificación: archivos finitos, sin
saturación digital y transcripción automática de los bloques del mensaje.
Los resultados de QA están junto a cada WAV; la escucha sigue pendiente.
