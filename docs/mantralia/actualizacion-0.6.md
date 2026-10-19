# Actualización personalizada a Voicebox 0.6.0

Integración de `jamiepine/voicebox` en `8af7efe`, conservando los cambios de
Mantralia de `52ee2b9`. La rama oficial contiene código posterior a las notas
de 0.6.0; la última descarga estable publicada al revisar era 0.5.0.

Se conservan MiniMax, Fish Audio, sus ajustes del servidor, controles de
prosodia, silencios exactos, sonidos, frecuencias, biblioteca de audio y el
paquete `assets/voices/deseos-timbre-calido-variante-2`. La generación MLX
mantiene la referencia seleccionada incluso cuando falla la inferencia;
ahora también utiliza el hilo único y la liberación de memoria de upstream.

## Datos y recuperación

Existen dos bibliotecas independientes: `data/` en el proyecto y
`~/Library/Application Support/sh.voicebox.app/` en la aplicación de escritorio.
La actualización conserva cada una en su ubicación. El servidor del proyecto
puede usar el puerto 17494 mientras la aplicación de escritorio utiliza 17493.

Antes de actualizar se creó un respaldo privado fuera del repositorio con el
historial Git, la configuración, bases SQLite consistentes, perfiles, audios y
la aplicación anterior. Las migraciones se ejecutaron dos veces sobre copias
de ambas bases, comprobando integridad y preservación de todos los valores
originales. Los archivos de audio y referencias se compararon mediante SHA-256.

## Validación

- 165 pruebas de backend aprobadas y 8 omitidas por sus prerrequisitos.
- Comprobación de TypeScript y compilaciones web y Tauri aprobadas.
- API 0.6.0 verificada sobre una copia de datos: perfiles, muestras, biblioteca
  y ajustes de MiniMax/Fish. El audio de Variante 2 coincide byte a byte.
- Nueva regresión de integración: el motor guardado de MiniMax/Fish, idioma,
  emoción, velocidad, tono y silencios se mantienen al generar desde un perfil.
- Web y Tauri utilizan el mismo cliente de consultas que el selector de
  servidor, para invalidar la biblioteca anterior cuando cambia la conexión.
  El cambio entre ambas bibliotecas se comprobó desde la interfaz.
- Servidor autónomo y adaptador MCP compilados para Apple Silicon. Se verificó
  el arranque del binario, la carga de una referencia y su análisis de prosodia,
  la importación del audio y sus bytes, además de la firma de la aplicación.
- Aplicación 0.6.0 instalada manteniendo su biblioteca original. La Variante 2
  también se instaló como perfil y grabación adicionales, conservando las voces
  anteriores y los ajustes existentes de MiniMax. Fish Audio hereda la clave
  del proyecto cuando todavía no había una configurada en la app.

La compilación nativa se prepara en un entorno Python independiente dentro de
`data/tools/`; los modelos y la configuración del entorno de trabajo existente
se conservan. Las claves, bases de datos, copias de recuperación y binarios
generados permanecen fuera de Git.
