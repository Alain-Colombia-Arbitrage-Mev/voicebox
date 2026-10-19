# Deseos · Timbre cálido · Variante 2 · MiniMax HD

Voz masculina cálida para narración reflexiva en español. El paquete contiene
`preview.wav` (la toma completa de 30,85 segundos), `reference.wav` (14,45 segundos
con tres frases completas) y `voice.json` con textos, procedencia y checksums.
El acento y la naturalidad siguen sujetos a evaluación mediante escucha.

Desde la raíz del repositorio, con Voicebox en ejecución:

```sh
.venv/bin/python scripts/install_library_voice.py
```

El instalador crea el perfil en **Voces**, selecciona **MiniMax** como motor y
añade el audio a la biblioteca. Puede ejecutarse otra vez sin duplicar el perfil
ni la grabación. No realiza llamadas a MiniMax ni consume saldo al instalar.

Para generar otro texto, selecciona esta voz y el idioma español. La primera
generación necesita una clave de MiniMax configurada en Voicebox y creará una
voz remota a partir de la referencia; esa operación y la síntesis consumen saldo.
Las nuevas locuciones reinterpretan la prosodia de la muestra. No conservan
necesariamente los tiempos exactos ni la mezcla original de timbres.

Los audios proceden de la Variante 2 creada en esta sesión por petición del
usuario. No se incluyen credenciales, bases de datos ni identificadores de voces
remotas ligados a una cuenta.
