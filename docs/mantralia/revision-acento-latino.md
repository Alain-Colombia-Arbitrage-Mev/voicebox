# Revisión del acento

El usuario rechazó las voces entregadas porque le suenan anglófonas. La descripción «latina» o «colombiana» en un prompt no es evidencia de que el resultado tenga ese acento.

Se generaron dos pruebas originales de dirección bogotana, sin referencias de terceros, y se guardaron en la biblioteca con los títulos:

- Mantralia · Prueba de acento Bogotá · Conversacional.
- Mantralia · Prueba de acento Bogotá · Resonante.

El guion y los dos briefs se conservan en `pruebas-acento-colombiano.json`. Los prompts de diseño están redactados en español y especifican vocales españolas, r/rr españolas, seseo y melodía bogotana moderada. Ambas pruebas leen el mismo texto completo, sin marcadores que provoquen una síntesis independiente de fragmentos breves. Se usan idioma `es` (language_boost `Spanish`), velocidad 1, tono 0 y emoción `calm`; con la configuración actual, esto utiliza `speech-2.8-hd`. En las anteriores tomas con `fluent`, el backend seleccionaba `speech-2.6-hd`. Estos cambios no demuestran por sí mismos la corrección del acento.

Los másteres están en `data/mantralia/pruebas-acento-colombiano/`; sus recibos `.library.json` verifican que las descargas de la biblioteca coinciden exactamente con los archivos locales. La transcripción automática solo comprueba contenido; no valida el acento.

Estado: pendiente de escucha y selección del usuario. No sustituir los audios largos por estas voces hasta comprobar que la pronunciación cumple la referencia deseada. Si el diseño por texto sigue dando una pronunciación extranjera, hace falta una muestra de voz nativa autorizada o una voz de catálogo cuyo acento se haya escuchado y aprobado.

Referencia técnica de parámetros: https://platform.minimax.io/docs/api-reference/speech-t2a-http
