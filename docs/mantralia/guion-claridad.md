# Claridad para avanzar — locución profesional

## Enfoque editorial y persuasivo

Formato de podcast breve o pieza promocional editorial. Voz femenina latina, preferentemente colombiana, profesional, cálida y creíble. Ritmo conectado y expresivo, con dicción clara. La intención es captar atención, generar identificación y facilitar una decisión concreta. No es una sesión de meditación.

El enfoque de neuromarketing se traduce aquí en recursos de escritura: reconocer una tensión cotidiana, plantear una pregunta relevante, visualizar beneficios concretos y cerrar con una acción pequeña. No se presentan como efectos neurológicos demostrados ni se promete prosperidad por escuchar el audio.

El texto original se conserva. Se añade un gancho inicial y un cierre breve. Las frases sobre respirar y repetir forman parte de la narración; no se añaden inhalaciones, exhalaciones ni silencios para practicar.

## Dirección de voz

Mujer adulta colombiana, acento bogotano suave y nativo; registro medio a medio grave. Sonido de presentadora de podcast: cercano, seguro y articulado. Variar la entonación según el sentido. Énfasis breve en claridad, oportunidades, actuar, una y cuándo. Evitar susurro, monotonía, solemnidad y tono de venta exagerado. La voz de referencia determina el acento; escuchar la toma antes de aprobar.

Configuración MiniMax: speech-2.8-hd, emoción fluent, velocidad 1.06, tono 0. Sin reescritura de personalidad. Fish: dirección editorial y emociones por párrafo; sin una emoción global que contradiga las indicaciones. Las notas de interpretación se mantienen fuera del texto hablado.

## Guion con interpretación

### 1. confident

**Interpretación:** Reconocimiento cercano. Dar peso a esfuerzo y claridad; despertar interés sin dramatizar.

A veces, no te falta esfuerzo. Te falta claridad para saber hacia dónde dirigirlo.

**Pausa editorial:** 0.45 segundos.

### 2. curious

**Interpretación:** Curiosidad y complicidad. La pregunta invita a pensar, con ritmo de conversación profesional.

Pregúntate con calma: ¿Qué necesito hoy para dar mi próximo paso con más claridad? Date un momento. Deja que aparezca una respuesta, aunque todavía sea pequeña.

**Pausa editorial:** 0.7 segundos.

### 3. hopeful

**Interpretación:** Apertura y posibilidad. Marcar oportunidades y actuar con convicción, sin solemnidad.

Si deseas hacer una petición al universo, puedes comenzar con estas palabras: Universo, deseo nuevas oportunidades para mi vida. Ayúdame a reconocerlas y a encontrar el valor para actuar.

**Pausa editorial:** 0.35 segundos.

### 4. warm

**Interpretación:** Proyección de un beneficio concreto: tranquilidad, vínculos y crecimiento. Sonrisa leve, audible pero contenida.

Quiero construir una prosperidad que me permita vivir con tranquilidad, compartir con quienes amo y desarrollar mis capacidades.

**Pausa editorial:** 0.35 segundos.

### 5. confident

**Interpretación:** Agencia y confianza. Ligero impulso al enumerar aprender, pedir apoyo y dar un paso.

Hoy estoy dispuesto a aprender, a pedir apoyo y a dar un paso hacia lo que deseo. Puedes adaptar esta petición hasta sentir que expresa lo que llevas dentro.

**Pausa editorial:** 0.45 segundos.

### 6. engaging

**Interpretación:** Aterrizar el deseo en situaciones reconocibles. Variar la entonación entre ejemplos, sin recitar una lista.

Ahora piensa en una acción que esté a tu alcance. Quizá enviar esa propuesta que tienes pendiente. Preparar una conversación importante. Retomar una idea que habías dejado de lado. O descansar para decidir con más calma.

**Pausa editorial:** 0.45 segundos.

### 7. confident

**Interpretación:** Compromiso concreto. Énfasis en una y cuándo. Afirmaciones firmes y conectadas, sin cantadito.

Elige una y piensa cuándo vas a hacerla. Después, repite suavemente: Mis capacidades tienen valor. Mi esfuerzo merece una dirección. Puedo aprender y avanzar a mi ritmo.

**Pausa editorial:** 0.55 segundos.

### 8. encouraging

**Interpretación:** Cierre invitacional y resolutivo. Elevar ligeramente la energía en empieza y terminar con cadencia descendente.

Respira una vez más, sin forzar. Cuando estés listo, escribe tu intención y el paso que has elegido para hoy. No necesitas tener todas las respuestas. Empieza por una decisión que puedas convertir en acción.

**Pausa editorial:** 0.6 segundos.

## Producción y revisión

214 palabras. Ocho pausas breves, 3.9 segundos en total; el resto de las pausas procede de la puntuación y de la interpretación del motor. Orientación de ritmo: 135–155 palabras por minuto, La toma generada dura **99.527 segundos (1:40)**; descontando los silencios programados, el ritmo aproximado es de **134 palabras por minuto**. Sin respiraciones audibles añadidas.

La primera versión de 3:13 corresponde al tratamiento de meditación descartado. El nuevo archivo es `data/mantralia/claridad-podcast-minimax.wav`; permanece separado para poder comparar.

Fish Audio permanece pendiente de una prueba sonora: la cuenta autenticó correctamente, pero la creación de voz devolvió HTTP 402 por falta de créditos de API, separados del saldo de plataforma. [Administrar créditos Fish](https://fish.audio/app/developers).

## Uso en Voicebox

En el generador, selecciona MiniMax o Fish Audio y un perfil de locutora latina. Con el campo de texto vacío, pulsa **Cargar guion de podcast**. La plantilla aplica español y velocidad 1.06; MiniMax usa emoción Fluido. Un texto ya escrito no se sobrescribe.

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 17493 --env-file .env
# En otra terminal; generar consume créditos:
.venv/bin/python scripts/render_mantralia.py --engine minimax
# Solo exportar guiones, sin consumo:
.venv/bin/python scripts/render_mantralia.py --export-scripts
```

La fuente editable es `app/src/lib/constants/mantralia-claridad.json`. Las versiones listas para el motor están en `claridad-minimax.txt` y `claridad-fish.txt`. `--preview` produce solo el inicio; `--profile` permite elegir otro perfil. El cliente espera el resultado y guarda WAV y metadatos.

Las claves `MINIMAX_API_KEY` y `FISH_AUDIO_API_KEY` permanecen en el backend. Los motores cloud reciben el texto y la referencia vocal. Audio, base de datos y credenciales están excluidos de Git.

Verificación de esta versión: WAV mono de 32 kHz, pico 0.85 sin saturación digital; transcripción automática con gancho, pregunta, petición, beneficios, afirmaciones y cierre presentes. La escucha del acento, dicción y expresividad queda pendiente. TypeScript y compilación web correctos.
