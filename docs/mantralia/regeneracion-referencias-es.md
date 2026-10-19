# Regeneración desde referencias en español

Las voces diseñadas por texto fueron rechazadas por el usuario por percibirse anglófonas. Se eliminaron 8 perfiles, 16 registros de audio, 112 archivos locales de producción y las 8 voces de Voice Design en MiniMax. Se verificó su ausencia en perfiles, biblioteca y catálogo remoto. Los MP3 originales de Downloads se conservaron. El inventario y los guiones retirados, sin audio, están en `voces-retiradas.json`.

## Cambio de método

Se usan las grabaciones originales aportadas por el usuario, «Argentina…» y «laura-meditA…», como referencias acústicas. Los perfiles nuevos se identifican por la referencia utilizada. Su nombre no certifica una nacionalidad ni un acento aprobado.

El intento inicial con MiniMax creó la referencia de Argentina, pero la síntesis devolvió el código 1008, `insufficient balance`. La consulta de saldo de Fish Audio devolvió `credit: 0.00` y `has_free_credit: false`.

Para continuar se habilitó el motor local Qwen3-TTS 1.7B en Apple Silicon, usando los pesos ya descargados en el equipo. Las generaciones locales se ejecutan con idioma Spanish, audio y transcripción de referencia. No tienen un fallback que sustituya la voz condicionada por una voz genérica si falla la referencia. No usan Voice Design ni consumen saldo de MiniMax o Fish.

Las dependencias se instalaron únicamente en `.venv`, siguiendo el pin de `mlx-audio==0.4.1` y la restricción de transformers 4.57.6 del repositorio; no se modificaron archivos de dependencias ni se descargaron otros pesos de voz. El entorno declara incompatibilidades entre algunas versiones exigidas por los paquetes MLX y transformers; la validación relevante es la carga e inferencia local realizadas, no una afirmación de compatibilidad general de todas sus funciones.

## Producción

`scripts/regenerate_spanish_references.py --engine qwen` conserva guiones, procedencia y registros de generación. La referencia de Argentina se recorta a 24,4 segundos para respetar el límite de 30 segundos de Voicebox. Laura utiliza su grabación completa, de aproximadamente 18,6 segundos.

Se regeneran narración, Voz Amiga, intención y claridad con Argentina, y calma con Laura. Cada máster terminado se guarda en la biblioteca; sus recibos `.library.json` comprueban la descarga idéntica al archivo local. Los registros `*-local-job.json` identifican el perfil y la referencia empleados.

Las frases se generan con su contexto completo. Los marcadores anteriores de pausa fija se retiran; los resultados nuevos no conservan las duraciones exactas de silencio anteriores. El parámetro de velocidad de MLX no está garantizado por esta versión del modelo; los valores de velocidad y emoción del perfil no se presentan como controles aplicados a la generación local. La mezcla final es cálida para narración y suave para calma.

Los archivos se guardan en `data/regeneracion-referencias-es/`. Las verificaciones de señal y transcripción no certifican el acento. La aprobación de la pronunciación y la interpretación queda pendiente de escucha del usuario.

## Resultado verificado

Se terminaron los cinco másteres y se comprobaron sus descargas en la biblioteca mediante SHA-256. Narración dura 32,72 s; Voz Amiga, 21,52 s; Intención, 24,08 s; Claridad, 75,62 s; Calma, 16,72 s. Los perfiles nuevos tienen idioma `es`, motor predeterminado `qwen` y una muestra de referencia cada uno. El detalle está en `regeneracion-verificada.json`.

Se corrigió además el backend MLX para que la ausencia de referencia, un modelo incompatible o un fallo de inferencia se propaguen como error en lugar de generar otra voz. Las tres pruebas de regresión de `backend/tests/test_mlx_voice_reference_required.py` pasaron. El servidor se reinició y confirmó backend MLX activo. La interfaz muestra los dos perfiles nuevos y sus referencias en español.

La transcripción automática reconoce los cinco guiones, con algunas variantes de palabras en la toma larga. No confirma que todas las palabras se hayan pronunciado perfectamente. Antes de una publicación, revisar por escucha el texto, la dicción, el acento y el ritmo; la velocidad de estas tomas difiere de las anteriores.

Documentación de referencia: https://github.com/Blaizzy/mlx-audio
