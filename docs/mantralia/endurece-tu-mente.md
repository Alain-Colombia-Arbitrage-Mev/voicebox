# Endurece tu mente: mezcla mejorada

Se procesó localmente el archivo aportado «Endurece tu mente - Discurso Motivacional». Dura 629,68 segundos (10 minutos y 30 segundos), con dos canales y frecuencia de muestreo de 44,1 kHz. La voz, las palabras, las pausas y el tono grabado se conservan. No se realizó síntesis ni clonación de voz.

Se aplicó el preset `motivational` de `scripts/refine_podcast_audio.py`:

- Filtro de graves a 55 Hz.
- Ajustes suaves de graves y medios bajos para reducir su peso en la mezcla completa.
- Realce de 0,8 dB alrededor de 2,2 kHz para favorecer la presencia vocal.
- Atenuación suave de agudos y compresión ligera, con ataque de 25 ms y recuperación de 200 ms.
- Ganancia limitada por una estimación de pico con sobremuestreo de cuatro veces, con techo de −1,5 dBFS.

El archivo de salida es `data/mantralia/endurece-tu-mente/endurece-tu-mente-mezcla-mejorada.wav`, WAV PCM de 24 bits. No se separaron voz y acompañamiento: los ajustes afectan a la mezcla original completa.

## Validación

El máster contiene exactamente los mismos 27.768.832 fotogramas de audio que la fuente decodificada, y conserva ambos canales. No hay muestras saturadas ni valores no finitos. Su pico de muestra es aproximadamente −1,55 dBFS; el pico estimado con sobremuestreo es −1,5 dBFS. El RMS final es −20,85 dBFS. La ganancia se limitó por los picos, por lo que no se alcanzó el objetivo RMS del preset; no se afirma que la versión resulte más fuerte que la original.

Se revisaron transcripciones automáticas de fragmentos al inicio, en el centro y cerca del final para identificar el contenido motivacional. No son una transcripción corregida del discurso ni una evaluación auditiva. La claridad y el balance percibidos quedan pendientes de escucha.

Se guardó el máster terminado en la biblioteca con el título «Mantralia · Endurece tu mente · Mezcla mejorada». El recibo `.library.json` conserva su identificador, SHA-256 y la comprobación de descarga idéntica al archivo local.
