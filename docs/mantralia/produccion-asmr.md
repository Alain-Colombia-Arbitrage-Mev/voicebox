# Voces de ASMR para meditación y calma

## Mezcla del archivo original

Se conserva el texto y la interpretación del archivo entregado. La mezcla
suaviza los agudos, reduce resonancia baja y aplica compresión ligera. Nivel
objetivo RMS -24 dBFS y techo de pico -3 dBFS. Estos valores describen el archivo,
no el volumen físico de reproducción ni una garantía de efecto relajante.

Sin cambio de altura o velocidad, sin música, eco, movimiento estéreo ni
respiraciones añadidas. El archivo original se procesa localmente; no se sube
como referencia vocal. Ecualizar no convierte una interpretación hablada en un
susurro; las dos interpretaciones nuevas se generan por separado.

Resultado: `data/mantralia/asmr-calma/original-mezcla-suave.wav`, mono 44.1 kHz,
24 bits, 18.599 s. La mezcla tiene RMS -24 dBFS y pico 0.550, sin saturación.

```bash
.venv/bin/python scripts/refine_podcast_audio.py INPUT.mp3 \
  --preset asmr --output OUTPUT.wav
```

## Dos voces originales

- **Susurro ASMR original:** mujer adulta, dirección de acento colombiano,
  susurro discreto, dicción clara, cercanía de micrófono y volumen uniforme.
  MiniMax: emoción `calm`, velocidad 0.94, tono 0. La voz se diseña con
  textura susurrada; no se fuerza una segunda capa de susurro que reduzca
  la inteligibilidad.
- **Calma ASMR original:** mujer adulta, dirección de acento colombiano,
  voz suave y aireada que conserva cuerpo y sonoridad. MiniMax: emoción `calm`,
  velocidad 0.86, tono 0.

Son identidades sintéticas diseñadas por descripción, con referencias propias
generadas por MiniMax; no se busca reproducir a la hablante del archivo. El
acento, el grado de susurro y la naturalidad requieren escuchar las muestras.

La fuente editable está en `voces-asmr.json`: dirección vocal, texto y parámetros.
Las muestras usan las afirmaciones del original, con normalización gramatical de
la transcripción automática ("El universo anhela mi éxito" y "Somos vasijas").
Las afirmaciones se interpretan como texto de la práctica, no como promesas de
resultados. Se añaden seis pausas de 1.5–3 segundos, 12.5 segundos en total; no
se añaden respiraciones audibles. Las indicaciones no se pronuncian.

```bash
# Backend Voicebox en ejecución; consume crédito MiniMax:
PYTHONPATH=. .venv/bin/python scripts/create_original_podcast_voices.py \
  --spec docs/mantralia/voces-asmr.json
```

Los perfiles y generaciones se guardan en Voicebox. Se conserva el audio bruto
y una mezcla suave para comparar a un nivel parecido. El script reutiliza los
IDs de voz y los trabajos guardados para evitar duplicar solicitudes tras una
interrupción. Las credenciales y los archivos de audio quedan fuera de Git.

## Resultados verificados

- Original suavizado: 18.599 s, mono 44.1 kHz.
- ASMR íntimo calibrado: `susurro-asmr.wav`, 31.401 s, mono 32 kHz.
- Voz suave con cuerpo: `voz-suave-asmr.wav`, 32.406 s, mono 32 kHz.

Las dos muestras nuevas incluyen 12.5 segundos de pausas. Los WAV son finitos
y no tienen saturación digital. La transcripción automática reconoce las
afirmaciones principales de ambas tomas. La prueba inicial de susurro extremo
se conserva separada como `susurro-prueba-inicial`; se eligió la calibración
más clara. Acento, naturalidad y efecto subjetivo de calma pendientes de escucha.
