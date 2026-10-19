# Voz Amiga: ritmo e interpretación

Se prepararon dos versiones del audio aportado, cuyo contenido es una invitación promocional de Mantralia seguida de una afirmación.

| Versión guardada en la biblioteca | Duración | Trabajo realizado |
| --- | --- | --- |
| Mantralia · Voz Amiga · Original con pausas y calidez | 24,18 s | Conserva la voz y las palabras grabadas. Añade 0,90 s entre cinco frases y aplica ecualización suave, compresión ligera y ganancia controlada. |
| Mantralia · Voz Amiga · Nueva toma latina | 25,35 s | Nueva interpretación con el perfil sintético original «Mantralia · Narradora original cercana», diseñado por texto con dirección de acento colombiano. MiniMax, emoción fluent, velocidad 0,99 y tono 0. |

La primera versión modifica el ritmo y la mezcla; no resintetiza palabras ni cambia la curva melódica de la voz original. La segunda permite una nueva interpretación de las frases. No se subió la grabación aportada como referencia para clonar una identidad.

## Dirección y archivos

El guion, las pausas y las indicaciones editoriales están en `guion-entonacion-amiga.json`. La apertura distingue «contrato», «pago» y «oportunidad»; la reflexión reduce la intensidad; la invitación se mantiene cercana; una pausa separa la afirmación final. Las indicaciones editoriales no son parámetros que MiniMax garantice ejecutar: los controles enviados son los documentados en ese JSON.

Los másteres están en `data/mantralia/entonacion-amiga/original-entonacion-calida.wav` y `data/mantralia/entonacion-amiga/nueva-toma-latina.wav`.

## Persistencia y validación

- Original ajustado: `08f7d12e-366b-4286-950a-648cda443e12`.
- Nueva toma terminada: `3ccd324e-1dfb-4c19-99c9-d7c10addbcf3`.
- Generación MiniMax anterior a la mezcla final: `7d9212b8-b485-44ee-a6db-a6c19d253435`.

Ambos másteres se importaron mediante `/generate/import`, figuran en `/library` y se descargaron mediante `/library/{id}/audio`. Sus SHA-256 coinciden con los archivos locales. Los recibos `.library.json` conservan la comprobación y permiten repetir el registro sin duplicarlos.

Se comprobó que los audios contienen muestras finitas y no tienen muestras saturadas. Las cinco inserciones del original se hicieron en intervalos silenciosos, sin eliminar voz. La transcripción automática de la nueva toma reconoce el mensaje completo, incluida la afirmación final. Esta comprobación no sustituye la escucha: la aprobación subjetiva del acento, el énfasis y la entonación queda pendiente.
