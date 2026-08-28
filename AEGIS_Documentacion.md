# AEGIS — Documentación General de la Aplicación

> **Para quién es este documento:** Cualquier persona del equipo, aunque no tenga conocimientos técnicos profundos. El objetivo es entender *qué hace* cada parte de la aplicación y *por qué existe*.

---

## ¿Qué es AEGIS?

AEGIS es un **asistente de soporte inteligente** llamado **Aegisito**. Permite a los clientes de AEGIS hacer preguntas en lenguaje natural (como si le preguntaras a una persona) y obtener respuestas precisas basadas en:

- Los **manuales PDF** de los programas de AEGIS.
- Los **videotutoriales de YouTube** del canal oficial.

La clave es que Aegisito **no inventa respuestas**. Solo responde con información que está en los manuales o vídeos, y siempre indica de dónde ha sacado cada dato (página del PDF o minuto del vídeo).

---

## Las partes de la aplicación

La aplicación tiene dos grandes bloques: el **Frontend** (lo que ve el usuario) y el **Backend** (lo que trabaja por dentro, invisible para el usuario).

### 🖥️ Frontend (lo que ve el usuario)

Es la interfaz web hecha con **Next.js** (un framework de React). El usuario escribe su pregunta aquí y ve la respuesta de Aegisito. También puede ver los documentos cargados, subir nuevos PDFs o sincronizar vídeos de YouTube.

### ⚙️ Backend (el motor)

Es el cerebro de la aplicación. Está hecho en **Python** con **FastAPI** (el servidor web). Tiene varios componentes que trabajan juntos:

---

## Los componentes del Backend, explicados

### 1. 🗄️ PostgreSQL — La agenda de la oficina

**Qué es:** Una base de datos relacional, como una hoja de Excel muy potente.

**Para qué sirve:** Guarda el registro de todo lo que ha pasado en la aplicación:
- Qué documentos PDF se han subido y en qué estado están (pendiente, procesando, completado, fallido).
- El historial completo de conversaciones de los usuarios con Aegisito.
- Las sesiones de chat de cada usuario.

**Analogía:** Es como el archivador físico de la oficina donde se guarda el historial de trámites.

---

### 2. 🔵 Qdrant — La biblioteca inteligente

**Qué es:** Una base de datos de vectores. Los vectores son listas de números que representan el *significado* de un texto.

**Para qué sirve:** Guarda todos los fragmentos de texto de los manuales y vídeos en forma de "huella matemática". Cuando el usuario hace una pregunta, la app convierte esa pregunta a su huella matemática y busca en Qdrant qué fragmentos tienen una huella parecida. Es como una búsqueda por significado, no solo por palabras clave.

**Analogía:** Es como una biblioteca donde los libros están organizados por *tema y significado*, no por orden alfabético. Si buscas "cómo cerrar el año contable", encuentra todos los fragmentos que hablan de eso aunque no usen esas palabras exactas.

---

### 3. 🔴 Redis — La pizarra de tareas

**Qué es:** Una base de datos muy rápida que vive en la memoria del ordenador (RAM).

**Para qué sirve:** Actúa como una **cola de trabajo**. Cuando se sube un PDF, la app no lo procesa en el momento (tardaría y bloquearía la página). En su lugar, apunta la tarea en Redis y dice "hay un PDF pendiente de procesar". Los workers de Celery ven esa nota y se ponen a trabajar.

**Analogía:** Es la pizarra donde el jefe deja los post-its con las tareas del día para que las procese el equipo.

---

### 4. 🟡 Celery Workers — Los empleados en la trastienda

**Qué es:** Procesos de Python que trabajan en segundo plano, separados del servidor web.

**Para qué sirven:** Hacen el trabajo pesado sin bloquear la aplicación. Cuando llega un PDF de 50 páginas, procesarlo lleva tiempo. El worker lo hace de forma silenciosa mientras el usuario puede seguir navegando sin esperar.

**Tareas que hacen:**
- Leer el PDF página a página y extraer el texto.
- Si una página es una imagen escaneada (sin texto seleccionable), usar **OCR** para reconocer el texto visualmente.
- Cortar el texto en fragmentos (chunks) de unos 500 caracteres.
- Convertir cada fragmento a su "huella matemática" (embedding).
- Guardar todo en Qdrant.

**Analogía:** Son los empleados del almacén que digitalizan los documentos físicos, los catalogan y los archivan en la biblioteca inteligente.

---

### 5. 🤖 FastEmbed — El traductor de texto a números

**Qué es:** Una librería de modelos de inteligencia artificial que corre localmente en el servidor.

**Para qué sirve:** Convierte textos (frases, párrafos) en vectores numéricos. Usa dos modelos:
- **Modelo denso (BAAI/bge-small):** Captura el significado semántico general. Entiende que "cierre de ejercicio" y "fin de año contable" hablan de lo mismo.
- **Modelo esparso (SPLADE):** Captura palabras clave exactas. Si buscas un nombre específico o un número de artículo, lo encuentra aunque el modelo denso no lo relacione.

**Analogía:** Es el intérprete que traduce texto humano al idioma matemático que entiende Qdrant.

---

### 6. 🧠 LLM (Groq / OpenAI / Ollama) — El escritor de respuestas

**Qué es:** Un modelo de lenguaje grande (como ChatGPT). Puede ser en la nube (Groq, OpenAI) o local (Ollama).

**Para qué sirve:** Es el último paso. Una vez que el sistema ha encontrado los fragmentos relevantes de los manuales, se los envía al LLM junto con la pregunta del usuario. El LLM los lee, entiende el contexto y redacta una respuesta clara en español, con las citas correspondientes.

**Lo que NO hace:** Inventar información. Si no está en los fragmentos que le mandan, tiene instrucciones de admitirlo y no improvisar.

**Analogía:** Es el redactor que, dado un montón de fotocopias relevantes de un manual, sintetiza la respuesta correcta de forma clara y cita de dónde ha sacado cada dato.

---

### 7. 🔀 CRAG Engine — El director de orquesta

**Qué es:** CRAG son las siglas de "Corrective Retrieval-Augmented Generation". Es el módulo central que coordina todo el proceso de respuesta.

**Para qué sirve:** No hace una búsqueda simple. Toma decisiones inteligentes:

1. **Busca** los fragmentos más relevantes (usando búsqueda híbrida + re-ranking).
2. **Evalúa** si lo que encontró es suficientemente bueno.
3. Si los resultados son malos, **reformula la pregunta** automáticamente y vuelve a buscar.
4. Si sigue sin encontrar nada relevante, da una respuesta honesta diciendo que no tiene esa información.
5. Si encontró buenos resultados, **genera la respuesta** citando las fuentes.

**Analogía:** Es el director de orquesta que coordina a todos los músicos (búsqueda, re-ranking, LLM) y decide cuándo el resultado es lo suficientemente bueno para servirlo al usuario.

---

### 8. 📊 Re-Ranker (BGE Reranker) — El verificador de calidad

**Qué es:** Otro modelo de IA local que evalúa qué tan relevante es cada fragmento para una pregunta concreta.

**Para qué sirve:** La búsqueda inicial en Qdrant devuelve hasta 30 candidatos. El re-ranker los lee uno por uno comparándolos con la pregunta y los puntúa de 0 a 1. Luego solo se quedan los 10 mejores. Esto es más lento pero mucho más preciso que confiar solo en la búsqueda.

**Analogía:** Si la biblioteca te da 30 libros que pueden contener la respuesta, el re-ranker es el experto que los hojea todos y te dice cuáles 10 son realmente los más útiles.

---

### 9. 🛡️ App Security — El módulo de seguridad

**Qué es:** Un conjunto de comprobaciones de seguridad que protegen la aplicación.

**Para qué sirve:**
- **Validación de archivos:** Cuando alguien sube un PDF, comprueba que realmente sea un PDF (no un virus disfrazado de PDF). Lee los primeros bytes del archivo para verificarlo.
- **Limpieza de nombres de archivo:** Elimina caracteres peligrosos de los nombres de archivo para evitar que alguien acceda a zonas del servidor que no debe.
- **Sanitización de datos sensibles:** Antes de guardar el texto de un PDF en la base de datos, elimina automáticamente emails, DNIs, IBANs y otras informaciones personales.
- **Protección del prompt:** Protege al LLM contra ataques donde alguien podría meter instrucciones maliciosas dentro de un PDF para intentar manipular a Aegisito.
- **Rate Limiting:** Si alguien intenta subir 20 PDFs en un minuto desde la misma IP, la aplicación lo frena temporalmente.

---

## El flujo completo: desde que arranca la app hasta que ves un vídeo

### Fase 1: Arranque del servidor 🚀

Cuando se lanza la aplicación (con `uvicorn`), ocurre esto en orden:

1. **FastAPI arranca** y carga toda la configuración desde el archivo `.env` (contraseñas, modelos, puertos...).
2. **Se conecta a PostgreSQL** y crea las tablas si no existen (documentos, sesiones, mensajes).
3. **Se conecta a Qdrant** y verifica que la colección de vectores existe. Si no existe o tiene una estructura antigua, la recrea.
4. **Se crea el directorio de uploads** donde se guardarán los PDFs subidos.
5. **Se cargan los modelos de IA en memoria** (embeddings densos, esparsos y re-ranker). Esto tarda unos segundos la primera vez.
6. El servidor queda **listo para recibir peticiones** en el puerto 8000.

---

### Fase 2: Sincronización de un vídeo de YouTube 🎬

Cuando el administrador pulsa "Sincronizar YouTube":

1. **La app consulta el feed RSS del canal** de YouTube. Este feed es público y lista los últimos vídeos publicados.
2. Para cada vídeo nuevo (que no esté ya en la base de datos):
   - Se crea un **registro en PostgreSQL** con estado "PENDIENTE".
   - Se encola una **tarea en Redis** para procesar el vídeo.
3. Los **workers de Celery** recogen la tarea de Redis y:
   - Esperan entre 10 y 20 segundos (para no ser bloqueados por YouTube como un bot).
   - **Descargan la transcripción automática** del vídeo desde YouTube (los subtítulos generados automáticamente).
   - Dividen la transcripción en **bloques de 90 segundos** (cada bloque es un fragmento indexable).
   - Generan los **vectores matemáticos** de cada bloque.
   - **Guardan todo en Qdrant** con el timestamp de inicio de cada bloque (para poder decir "min. 3:45").
   - Actualizan el estado en PostgreSQL a "COMPLETADO".

4. Ahora el vídeo está indexado y disponible para responder preguntas.

---

### Fase 3: El usuario hace una pregunta sobre el vídeo 💬

Supongamos que el usuario escribe: *"¿Cómo se hace el cierre de ejercicio?"*

**Paso 1 — Recepción de la pregunta:**
- El frontend envía la pregunta al backend (`POST /api/v1/chat/query`).
- El backend recupera el historial de conversación previo de esa sesión (últimas 6 respuestas).

**Paso 2 — Limpieza de la pregunta (CRAG):**
- El CRAG Engine detecta muletillas conversacionales ("háblame de", "cuéntame sobre"...) y las elimina para quedarse con la esencia de la búsqueda: *"cierre de ejercicio"*.

**Paso 3 — Búsqueda híbrida (doble búsqueda en paralelo):**
- Se hacen **dos búsquedas simultáneas** en Qdrant:
  - Una con la pregunta original completa.
  - Otra con la versión limpia (solo las palabras clave).
- Cada búsqueda usa **dos métodos a la vez** dentro de Qdrant:
  - **Búsqueda semántica (densa):** Encuentra fragmentos por significado aunque usen palabras distintas.
  - **Búsqueda por palabras clave (esparsa):** Encuentra fragmentos que contienen exactamente esas palabras.
- Qdrant fusiona ambos resultados con un algoritmo llamado **RRF** (da más puntuación a los fragmentos que aparecen bien posicionados en ambas búsquedas).
- Resultado: hasta 60 fragmentos candidatos (de PDFs y/o vídeos).

**Paso 4 — Deduplicación:**
- Se eliminan fragmentos repetidos de las dos búsquedas paralelas.

**Paso 5 — Re-Ranking:**
- El modelo BGE Reranker evalúa los ~60 fragmentos uno por uno comparándolos con la pregunta original.
- Selecciona los **10 mejores** por relevancia real.

**Paso 6 — Evaluación CRAG:**
- Se comprueba si el mejor fragmento tiene una puntuación suficientemente alta (umbral de relevancia).
- Si la puntuación es demasiado baja → el CRAG Engine **reformula la pregunta** con el LLM y repite la búsqueda.
- Si tras la reformulación sigue sin haber resultados → responde con un mensaje honesto de "no tengo esa información".
- Si la puntuación es buena → continúa al siguiente paso.

**Paso 7 — Construcción del contexto seguro:**
- Los 10 fragmentos se estructuran en un bloque XML con etiquetas claras:
  ```
  <context>
    <chunk id="1" source="manual_facturacion.pdf" page="23">
      Texto del fragmento aquí...
    </chunk>
    <chunk id="2" source="Tutorial cierre contable" timestamp="3:45" type="youtube">
      Transcripción del vídeo aquí...
    </chunk>
  </context>
  ```
- Se genera un mapa de citas: qué formato usar para referenciar cada fragmento.

**Paso 8 — Generación de la respuesta con el LLM:**
- Se envía al LLM (Groq en producción) el paquete completo:
  - El historial reciente de la conversación.
  - La pregunta del usuario.
  - El mapa de citas.
  - El contexto con los 10 fragmentos.
  - Las instrucciones de Aegisito (citar siempre, no inventar, tono amigable...).
- El LLM genera la respuesta en español, citando cada dato con su fuente exacta.

**Paso 9 — Respuesta al usuario:**
- La respuesta se guarda en PostgreSQL (historial de conversación).
- Se devuelve al frontend con:
  - La respuesta de Aegisito con citas inline.
  - Las fuentes usadas (nombre del PDF/vídeo, página/timestamp, puntuación de relevancia).
  - Las métricas de tiempo (cuánto tardó cada fase).
  - El estado del flujo CRAG (si reformuló la pregunta o no).

**El usuario ve la respuesta en pantalla** con las citas del PDF o los minutos del vídeo de YouTube correspondientes.

---

## Diagrama simplificado del flujo de una pregunta

```
Usuario escribe pregunta
        ↓
  FastAPI recibe la petición
        ↓
  CRAG Engine toma el control
        ↓
  ┌─────────────────────────────┐
  │   Búsqueda híbrida          │
  │   (semántica + keywords)    │
  │   en Qdrant                 │
  └──────────────┬──────────────┘
                 ↓
  ┌─────────────────────────────┐
  │   Re-Ranking               │
  │   (BGE Reranker evalúa     │
  │   relevancia real)          │
  └──────────────┬──────────────┘
                 ↓
  ¿Resultados suficientemente buenos?
     NO → Reformular pregunta → volver a buscar
     SÍ → continuar
                 ↓
  ┌─────────────────────────────┐
  │   LLM genera respuesta      │
  │   con citas de las fuentes  │
  └──────────────┬──────────────┘
                 ↓
  Guardar en PostgreSQL (historial)
                 ↓
  Usuario recibe respuesta con citas
```

---

## Estructura de archivos del proyecto

```
AEGIS/
├── backend/                    ← El motor (Python)
│   ├── app/
│   │   ├── api/v1/             ← Los endpoints (puertas de entrada)
│   │   │   ├── chat.py         ← Preguntas y conversación
│   │   │   ├── documents.py    ← Subir/gestionar PDFs y YouTube
│   │   │   └── health.py       ← Comprobación de estado del sistema
│   │   ├── app_security/       ← Módulo de seguridad
│   │   │   ├── file_validator.py  ← Validación de PDFs
│   │   │   ├── prompt_guard.py    ← Protección LLM + borrado de datos sensibles
│   │   │   └── rate_limit.py      ← Límite de peticiones por IP
│   │   ├── core/
│   │   │   └── config.py       ← Toda la configuración (lee variables de entorno)
│   │   ├── db/
│   │   │   ├── models.py       ← Definición de tablas de PostgreSQL
│   │   │   ├── postgres.py     ← Conexión a PostgreSQL
│   │   │   ├── qdrant.py       ← Conexión a Qdrant
│   │   │   └── redis.py        ← Conexión a Redis
│   │   ├── services/
│   │   │   ├── crag_engine.py  ← El director de orquesta (lógica CRAG)
│   │   │   ├── retrieval.py    ← Búsqueda híbrida en Qdrant
│   │   │   ├── reranker.py     ← Re-ranking de resultados
│   │   │   ├── vector_store.py ← Generación de embeddings e inserción en Qdrant
│   │   │   ├── llm.py          ← Conexión con Groq/OpenAI/Ollama
│   │   │   └── chat_service.py ← Gestión de sesiones y mensajes
│   │   ├── workers/
│   │   │   ├── celery_app.py   ← Configuración de Celery (la cola de tareas)
│   │   │   └── ingestion.py    ← Procesamiento de PDFs y vídeos de YouTube
│   │   └── main.py             ← Punto de entrada de FastAPI
│   ├── Dockerfile              ← Imagen Docker del servidor web
│   └── Dockerfile.worker       ← Imagen Docker del worker Celery
├── frontend/                   ← La interfaz web (Next.js / React)
├── docker-compose.yml          ← Levanta PostgreSQL, Qdrant y Redis juntos
└── start_aegis.bat           ← Script para arrancar todo en Windows
```

---

## Glosario rápido

| Término | Qué significa en lenguaje humano |
|---|---|
| **Embedding / Vector** | Una lista de números que representan el "significado" matemático de un texto |
| **Chunk** | Un fragmento de texto de unas 500 palabras, la unidad mínima que se indexa |
| **RAG** | Técnica de buscar información real antes de generar una respuesta con IA |
| **CRAG** | Versión mejorada de RAG que corrige sus propios errores reformulando la pregunta |
| **Re-Ranking** | Segunda pasada de evaluación para quedarse solo con los fragmentos más relevantes |
| **LLM** | Modelo de lenguaje grande (como ChatGPT) que genera texto coherente |
| **Worker** | Un proceso que trabaja en segundo plano sin bloquear la web |
| **Cola de tareas** | Lista de trabajos pendientes que los workers van procesando en orden |
| **Prompt** | El mensaje completo que se envía al LLM (incluye contexto, instrucciones y pregunta) |
| **OCR** | Reconocimiento óptico de caracteres: leer texto de imágenes escaneadas |
| **API Key** | Contraseña especial para usar servicios externos (Groq, OpenAI) |
| **PII** | Información personal identificable (emails, DNIs, IBANs...) |
