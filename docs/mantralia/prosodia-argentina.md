# Prosodia natural: anticipación, pregunta y pausa

## Original con pausas redistribuidas

Se mantienen las palabras, la voz y la interpretación de la grabación entregada.
Se amplían doce espacios entre frases, localizando zonas de baja energía para
no cortar sílabas. Se añaden 2.97 segundos: de 36.258 a 39.228 segundos.
La mezcla aplica ecualización y compresión suaves, con pico máximo -1 dBFS.
No se cambia la altura, no se estira el tiempo ni se inventan palabras o
respiraciones. Esta edición mejora el espacio entre ideas, pero no reinterpreta
las curvas de pregunta de una voz ya grabada.

Archivo: `data/mantralia/prosodia-argentina/original-pausas-naturales.wav`.
Plan reproducible: `plan-prosodia-argentina.json`.

```bash
.venv/bin/python scripts/retime_speech_pauses.py INPUT.mp3 \
  --plan docs/mantralia/plan-prosodia-argentina.json --output OUTPUT.wav
```

## Nueva interpretación con voz original

Voz femenina sintética diseñada por texto, con dirección de español argentino
rioplatense. No se sube el archivo entregado como referencia para clonar a su
hablante. El mensaje se conserva con puntuación editorial, normalización de la
transcripción y una conjunción para conectar la enumeración.

Dirección: cercanía, empatía y claridad. Alternar preguntas, imágenes concretas
y una invitación resolutiva. Evitar el mismo final ascendente en cada oración,
pausas iguales entre todas las frases y un tono de venta exagerado.

- **“¿Ya imaginaste ese momento?”** Pregunta auténtica y cercana; subida ligera
  en la curva interrogativa. Pausa de 0.65 s para dejar aparecer la imagen.
- **“El contrato firmado. La confirmación…”** Evocar una escena concreta;
  enumeración conectada, con un énfasis distinto en cada imagen. Pausa 0.45 s.
- **“Pero pasan los días…”** Bajar ligeramente la energía y reconocer la espera;
  sin dramatizar. Pausa 0.35 s.
- **“Revisas… repasas… ¿qué pudiste hacer diferente?”** Unir los ejemplos y
  cerrar con una pregunta reflexiva; sin tono de reproche. Pausa 0.75 s.
- **Antes de volver a revisar.** Respiración breve y discreta antes del cambio
  de intención. Hablar con calma y claridad; no susurrar. Pausa 0.5 s.
- **“En Mantralia…”** Invitación concreta, con énfasis en acompañarte, intención
  y hoy. Pausa 0.35 s.
- **Cierre.** Segunda respiración discreta antes de “Abre Mantralia”. Dar peso a
  “un espacio” y “próximo paso”; acabar con cadencia descendente. Pausa 0.5 s.

Guion completo y dirección: `voces-prosodia-argentina.json`.
MiniMax: emoción `fluent`, velocidad 0.96, tono 0. Marcadores de silencio local
exacto; dos interjecciones nativas `(breath)`, que no son texto para pronunciar.
Las notas anteriores son dirección humana, separada de la locución.

Archivo: `data/mantralia/prosodia-argentina/nueva-toma-prosodia.wav`.
La toma está guardada en la biblioteca y el perfil original en Voicebox.
La pronunciación argentina, naturalidad, preguntas y respiraciones requieren
escucha; una transcripción automática no verifica estos aspectos expresivos.

```bash
# Backend en ejecución; consume crédito MiniMax si no existe un resultado:
PYTHONPATH=. .venv/bin/python scripts/create_original_podcast_voices.py \
  --spec docs/mantralia/voces-prosodia-argentina.json
```

## Verificación

- Original editado: 39.228 s, 44.1 kHz; las doce inserciones suman 2.97 s.
  Todos los cortes se ubican en regiones con RMS por debajo de -69 dBFS.
  Se conservan los frames del audio hablado y no se resintetiza la voz.
- Nueva interpretación: 39.553 s, 32 kHz; trabajo completado en Voicebox.
- WAV finitos, pico máximo 0.891, sin saturación digital.
- Transcripción automática: pregunta/contexto inicial, espera, reflexión,
  meditación, intención y cierre presentes. No se detectan las indicaciones
  `(breath)` o los marcadores de pausa leídos como palabras.
- La transcripción verifica contenido; no certifica curvas interrogativas,
  intensidad de respiraciones, acento argentino ni naturalidad subjetiva.
