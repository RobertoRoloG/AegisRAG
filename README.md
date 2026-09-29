# AEGIS - Asistente RAG Multifuente Inteligente (Pack Portable y VPS 24/7)

Este es el backend y el panel de control del asistente inteligente RAG (*Retrieval-Augmented Generation*) para **AEGIS**.

El sistema es completamente **portable y escalable**. Puede funcionar tanto en servidores de producción (VPS) las 24 horas del día sin interrupciones, como en un ordenador local de pruebas.

---

## 🛠️ Arquitectura y Tecnologías
* **Motor Backend:** Python 3.14+ con FastAPI (asíncrono).
* **Motor CRAG (Corrective RAG):** Búsqueda híbrida (densa con `BAAI/bge-small-en-v1.5` + esparsa con `SPLADE`) y re-ranking con Cross-Encoder (`BAAI/bge-reranker-base`).
* **Base de Datos Vectorial:** Qdrant (almacén persistente de embeddings para PDFs y fragmentos temporales de vídeo con panel en `http://localhost:6333/dashboard`).
* **Cola de Ingesta Asíncrona:** Celery (con Redis como broker de tareas en segundo plano).
* **Base de Datos Relacional:** PostgreSQL 16 (metadatos de documentos, vídeos, historial y estado de procesamiento).
* **LLM:** Groq LPU (`llama-3.1-8b-instant`), Google Gemini (`gemini-3.6-flash`) o DeepSeek (`deepseek-chat`) para respuestas ultra rápidas con citas inline obligatorias.
* **Frontend:** Next.js 15 + React 19 + TailwindCSS (panel de gestión de documentos, reproductor de citas y chat interactivo).
* **Exposición y Acceso:** Nginx con SSL y dominio propio (para despliegue 24/7 en VPS de producción, sin Ngrok) o Ngrok (únicamente para pruebas temporales desde un PC local con Windows).

---

## 📂 Mapa de Archivos Clave del Código

Para entender cómo funciona internamente la aplicación y qué hace cada parte, esta es la guía de los módulos principales:

### 🧠 1. Motores de IA y RAG

* **`crag_engine.py` (Motor Corrective RAG):**
  Es el cerebro orquestador del sistema. Implementa una máquina de estados para garantizar respuestas fiables:
  * **Búsqueda Dual Paralela:** Limpia muletillas conversacionales (*"háblame de...", "qué dice de..."*) y lanza en paralelo la consulta en lenguaje natural y la búsqueda estricta de entidades.
  * **Deduplicación Inteligente:** Unifica los resultados por ID y elimina fragmentos con contenido textual repetido.
  * **Re-Ranking Semántico:** Aplica el modelo Cross-Encoder sobre los mejores candidatos.
  * **Nodo GRADE & Umbral Dinámico:** Evalúa la puntuación del contexto. Si el score es inferior al umbral y no hay coincidencia exacta de términos, pasa al estado de ambigüedad y reescribe la consulta con el LLM para una segunda pasada de recuperación.
  * **Generación Restrictiva:** Construye el prompt blindado contra inyecciones y fuerza al LLM a responder únicamente con la información validada, obligando a generar citas en formato `[archivo.pdf, pág. X]` o `[Video: Título, min. M:SS]`.

* **`retrieval.py` (Búsqueda Híbrida y Fusión):**
  Ejecuta la búsqueda combinada en Qdrant calculando en tiempo real tanto el vector denso semántico como el vector esparso léxico (SPLADE). Fusiona los rankings en la propia base de datos mediante **Reciprocal Rank Fusion (RRF)** y aplica filtros dinámicos (exclusión automática de documentos inactivos o filtrado por documentos seleccionados).

* **`vector_store.py` (Almacén Vectorial y Embeddings):**
  Gestiona la conexión con Qdrant y la ejecución de los modelos de embeddings locales ONNX (`BAAI/bge-small-en-v1.5` para denso y `prithivida/Splade_PP_en_v1` para esparso) mediante FastEmbed. Permite la inserción por lotes (*batching*) y el borrado atómico de vectores asociados a un documento.

* **`reranker.py` (Reordenador Cross-Encoder):**
  Utiliza el modelo `BAAI/bge-reranker-base` para analizar pares `(consulta, fragmento)` asignando una puntuación precisa de relevancia semántica antes de pasar los textos al LLM.

* **`llm.py` (Capa Unificada de LLMs):**
  Abstrae los distintos proveedores de modelos de lenguaje (Groq, Google Gemini y DeepSeek). Maneja la inyección segura de instrucciones, tokens máximos, temperaturas y fallbacks.

---

### ⚙️ 2. Ingestión y Tareas en Segundo Plano

* **`ingestion.py` (Pipeline Asíncrono de Ingestión):**
  Contiene las tareas de Celery para procesar archivos y vídeos sin bloquear el servidor web:
  * **PDFs:** Extrae texto página a página con `pypdfium2` bajo cerrojo seguro de hilos, activa OCR paralelo (`RapidOCR` ONNX / `EasyOCR`) si la página es escaneada o es una imagen, divide el texto en fragmentos solapados (`RecursiveCharacterTextSplitter`), sanitiza datos sensibles/PII y calcula/guarda los embeddings en lotes de 100 en Qdrant.
  * **YouTube:** Descarga subtítulos con soporte de cookies anti-bloqueo (`youtube_cookies.txt`), fragmenta en ventanas temporales de 90 segundos con timestamps exactos y los indexa en Qdrant.

* **`celery_app.py` (Configuración de Celery):**
  Inicializa y configura la instancia del worker conectada a Redis, definiendo políticas de reintentos automáticos y serialización.

---

### 🌐 3. API REST y Controladores

* **`main.py` (Punto de Entrada FastAPI):**
  Configura el ciclo de vida (*lifespan*) para verificar/crear tablas en PostgreSQL y colecciones en Qdrant, aplica middleware CORS y control de tasa (*Rate Limiting* con SlowAPI).

* **`chat.py` (Controlador de Conversación):**
  Endpoint para consultas interactivas del chat con streaming y métricas de latencia en tiempo real.

* **`documents.py` (Gestor Documental):**
  Endpoints para subida segura de PDFs (validación de cabeceras/magic bytes), importación manual de transcripciones VTT/TXT, activación/desactivación de fuentes, eliminación y sincronización de YouTube.

* **`health.py` (Monitor de Salud):**
  Verificación continua de conectividad con PostgreSQL, Qdrant y Redis con cálculo de latencias.

---

### 🗄️ 4. Persistencia y Seguridad

* **`models.py` (Modelos de Base de Datos):**
  Modelos SQLAlchemy para PostgreSQL (`Document`, `ConversationHistory`, `DocumentStatus`).

* **`postgres.py`, `qdrant.py`, `redis.py` (Conectores de Base de Datos):**
  Fábricas de sesiones asíncronas y clientes de conexión con gestión optimizada de pools.

* **`prompt_guard.py` y `file_validator.py` (Módulos de Seguridad):**
  Barreras de sanitización contra inyección de prompts, validación de PDFs reales y saneamiento estricto de nombres de archivo.

---

## 📥 Ciclo de Ingestión Asíncrona (PDF y YouTube)

El procesamiento de información se realiza en segundo plano mediante trabajadores de **Celery**, garantizando que la aplicación web responda de forma instantánea sin bloqueos de memoria:

```
[ Subida PDF / Sincronización YouTube ]
                  ↓
       [ Validación de Seguridad ] ─────── (Magic bytes %PDF / URL YouTube / Anti-PII)
                  ↓
     [ Estado PENDING en PostgreSQL ]
                  ↓
    [ Worker Asíncrono de Celery ]
         ├── PDF: pypdfium2 (Thread-Safe) + RapidOCR ONNX Paralelo
         └── YouTube: Subtítulos/Cookies o Importación Directa VTT
                  ↓
       [ Fragmentación Inteligente ] ───── (RecursiveCharacterTextSplitter / Ventanas 90s)
                  ↓
    [ FastEmbed ONNX (CPU Local) ] ─────── (Vector Denso BGE + Vector Esparso SPLADE)
                  ↓
     [ Inserción por Lotes en Qdrant ] ─── (Colección aegis_chunks en batches de 100)
                  ↓
    [ Estado COMPLETED en PostgreSQL ]
```

### 1. Ingestión de Manuales PDF:
1. **Subida Segura:** Valida la cabecera real del archivo (*magic bytes* `%PDF`) y sanea el nombre físico en disco.
2. **Registro Inicial:** Crea el registro en PostgreSQL con estado `PENDING` y delega la tarea a Celery.
3. **Extracción Thread-Safe y OCR:** `pypdfium2` extrae el texto digital página a página. Si detecta páginas escaneadas o imágenes, activa automáticamente `RapidOCR` ONNX en paralelo sobre los núcleos de la CPU.
4. **Chunking y Sanitización:** Trocea el contenido con solapamiento (`chunk_overlap`) conservando el número de página original y eliminando cadenas sospechosas de inyección.
5. **Vectorización y Batching:** Genera los embeddings densos y esparsos en lotes de 100 para optimizar el consumo de RAM y los guarda en Qdrant.
6. **Finalización:** Marca el documento como `COMPLETED` y registra el total de chunks generados.

### 2. Ingestión de Videotutoriales de YouTube:
1. **Doble Vía de Entrada:** Puede sincronizar un canal completo vía feed RSS/XML, procesar URLs individuales o recibir archivos de transcripción `.vtt` / `.txt` aportados manualmente.
2. **Extracción Temporal:** Descarga los subtítulos (usando cookies de sesión anti-bloqueo si es necesario) o parsea los bloques WebVTT extrayendo los segundos exactos de inicio.
3. **Ventanas Temporales:** Agrupa las frases en bloques coherentes de 45 a 90 segundos con su marca de tiempo asociada.
4. **Indexación:** Vectoriza y almacena en Qdrant vinculando el `video_id` y el segundo exacto de inicio.

---

## ⚡ Ciclo de Consulta y Respuesta en Tiempo Real (End-to-End)

Cuando un usuario interactúa con el chat, se desencadena el siguiente flujo de alta precisión:

```
[ 1. Usuario envía consulta en Chat ]
                  ↓
[ 2. FastAPI + Rate Limiting ] ────────── (Protección de tráfico y Prompt Guard)
                  ↓
[ 3. Búsqueda Dual Paralela ] ─────────── (Pregunta natural + Palabras clave limpias)
                  ↓
[ 4. Qdrant Híbrido + Fusión RRF ] ────── (Embeddings BGE + SPLADE sobre fuentes activas)
                  ↓
[ 5. Deduplicación por ID y Texto ] ───── (Elimina fragmentos redundantes)
                  ↓
[ 6. Re-Ranking Cross-Encoder ] ───────── (Puntuación semántica profunda con bge-reranker)
                  ↓
[ 7. Nodo Evaluador GRADE (CRAG) ]
     ├── Relevancia Insuficiente ───────→ [ Reescritura de Query con LLM y Reintento ]
     └── Contexto Validado ─────────────→ [ Pasa a Generación ]
                  ↓
[ 8. Generación con LLM (temp=0.0) ] ──── (Gemini / Groq / DeepSeek con citas obligatorias)
                  ↓
[ 9. Renderizado Interactivo ] ────────── (Citas interactivas con salto a PDF / YouTube)
```

### Detalle de cada fase:
1. **Envío y Seguridad:** La consulta viaja al endpoint `/api/v1/chat/query`, donde se valida la tasa de peticiones y se neutralizan posibles comandos maliciosos.
2. **Búsqueda Dual:** Se limpia la consulta de muletillas conversacionales y se lanzan dos búsquedas simultáneas en Qdrant (lenguaje natural y términos clave).
3. **Recuperación Híbrida y Fusión RRF:** FastEmbed genera los vectores denso (semántico) y esparso (léxico SPLADE) en milisegundos. Qdrant recupera los candidatos y los unifica mediante **Reciprocal Rank Fusion**.
4. **Deduplicación:** Se descartan duplicados por identificador de chunk y por similitud de texto normalizado.
5. **Re-Ranking Semántico:** El modelo Cross-Encoder evalúa pares `(pregunta, fragmento)` y selecciona los 12 mejores fragmentos con mayor relevancia.
6. **Máquina de Estados CRAG (Nodo GRADE):**
   * **`CORRECT`:** Si la puntuación supera el umbral, se construye el contexto documental.
   * **`AMBIGUOUS`:** Si la puntuación es baja y no hay coincidencia exacta, el LLM reformula la pregunta incorporando el historial y repite la búsqueda. Si tras el reintento no hay datos, pasa a `NO_DATA_FOUND` y responde educadamente que la información no está en los manuales (evitando alucinaciones).
7. **Generación con Citas:** El LLM redacta la solución con temperatura `0.0` y citas estrictas (`[archivo.pdf, pág. X]` o `[Video: Título, min. M:SS]`).
8. **Interacción en Frontend:** El chat muestra la respuesta y convierte las citas en botones clicables:
   * Al pulsar una cita de PDF, se abre el **Visor Lateral en la página exacta** con el fragmento resaltado.
   * Al pulsar una cita de vídeo, se abre el reproductor en el **segundo exacto** de la explicación.

---

## 🛡️ Arquitectura de Alta Disponibilidad 24/7 (Resiliencia Continua)

El sistema está **diseñado específicamente para funcionar de manera ininterrumpida 24/7** tanto en servidores dedicados/VPS como en local:

* **Políticas de Auto-Reinicio (`restart: always`):** Todos los contenedores en `docker-compose.prod.yml` (`postgres`, `qdrant`, `redis`, `backend`, `celery_worker`, `celery_beat`, `frontend`) se reinician automáticamente si el proceso falla o si el servidor físico se reinicia.

* **Healthchecks Activos:** PostgreSQL y Redis cuentan con comprobaciones continuas de salud (`pg_isready` y `redis-cli ping`). Los servicios dependientes esperan automáticamente a que las bases de datos estén saludables antes de inicializarse.

* **Persistencia Externa:** Los datos de PostgreSQL y Qdrant se almacenan en volúmenes externos independientes (`aegisito_postgres_data` y `aegisito_qdrant_data`), asegurando que ningún dato o embedding se pierda durante reconstrucciones o caídas.

* **Tolerancia a Fallos en Tareas (Celery Auto-Retry):** Las tareas de ingesta cuentan con reintentos automáticos exponenciales (`max_retries=3`, `default_retry_delay=10`) en caso de cortes transitorios. Además, el script `scratch/requeue_processing.py` permite reencolar documentos pendientes tras caídas del sistema.

* **Embeddings Locales sin Dependencia Externa:** La generación de vectores corre localmente vía FastEmbed (ONNX), por lo que nunca se bloquea por límites de cuota de embeddings ni caídas de red de APIs externas.

* **Rotación y Límites de Logs:** Todos los servicios tienen configurada rotación de logs (`max-size: 10m`, `max-file: 3`) para impedir que los discos del servidor se saturen con el paso del tiempo.

---

## 🌐 Modos de Despliegue: VPS (Producción 24/7) vs PC Local (Pruebas)

Es fundamental distinguir los dos entornos posibles de ejecución:

### 1. ☁️ Despliegue en Servidor VPS (Producción 24/7 — SIN Ngrok)
En un servidor VPS en la nube (como Hetzner, OVH o Contabo):
* **No se utiliza Ngrok:** El VPS cuenta con una IP pública fija directa.
* **Acceso con Dominio Propio:** Se conecta un subdominio de la empresa (por ejemplo `asistente.tuempresa.com` o `ia.aegis.es`) apuntando a la IP del servidor.
* **Nginx + SSL Gratuito:** Nginx gestiona el tráfico con certificado HTTPS (Let's Encrypt / Certbot) y redirige las peticiones a los contenedores Docker de forma rápida, segura y sin cortes.
* Para ver la guía completa paso a paso de administración y despliegue en servidor, consulta el documento **`manual_vps.md`**.

### 2. 💻 Despliegue en PC Local (Windows — Entorno de Pruebas con Ngrok)
Si ejecutas el proyecto en un ordenador personal o de oficina con Windows:
* Al no disponer de IP pública fija ni puertos abiertos, se utiliza **Ngrok** como túnel seguro temporal para conectar el backend con la web externa.
* A continuación se detallan los pasos para este modo local:

---

## 🚀 Requisitos para Servidor Local en PC (Windows)
Si quieres copiar este proyecto a otro ordenador (por ejemplo, mediante un pendrive) para que actúe como servidor local conectado a la web, ese ordenador debe tener instalado previamente:

1. **Docker Desktop** (para arrancar PostgreSQL, Qdrant y Redis).
2. **Python 3.14+** (instalado de forma global en Windows, marcando la opción *"Add python.exe to PATH"* en el instalador).
3. **Node.js y npm** (versión 20+ para compilar y ejecutar el frontend).

---

## 📋 Pasos de Configuración en el Nuevo Ordenador

### Paso 1: Copiar la carpeta y el archivo `.env`
Copia la carpeta entera `AEGIS` al disco local del nuevo ordenador (se recomienda el Escritorio para mayor velocidad).
> [!IMPORTANT]  
> Asegúrate de que el archivo `.env` esté dentro de la carpeta `backend/`. Debe contener la configuración de puertos, tokens y claves de API de los proveedores de LLM:
> ```env
> POSTGRES_PORT=5433
> REDIS_PORT=6380
> CORS_ORIGINS=["http://localhost:3000", "http://localhost:8000", "https://aegisformacion.com"]
> NGROK_AUTHTOKEN=tu_token_de_ngrok_aqui
> YOUTUBE_CHANNEL_ID=UCoZWQl3d034u8OIqnEGEnXA
> 
> # Claves de API de los proveedores de LLM (pueden coexistir en el archivo)
> GROQ_API_KEY=gsk_tu_clave_de_groq_aqui
> GEMINI_API_KEY=tu_clave_de_gemini_aqui
> DEEPSEEK_API_KEY=tu_clave_de_deepseek_aqui
> 
> # Configuración del LLM activo
> LLM_PROVIDER=gemini # Opciones: groq, gemini, deepseek
> LLM_MODEL=gemini-3.6-flash # Ejemplos: openai/gpt-oss-120b (Groq), gemini-3.6-flash (Gemini), deepseek-chat (DeepSeek)
> 
> # NOTA DE SEGURIDAD: Google retira modelos antiguos periódicamente. 
> # Antes de configurar LLM_MODEL para Gemini, comprueba la lista oficial de modelos vigentes en:
> # https://ai.google.dev/gemini-api/docs/models?hl=es-419
> ```

### Paso 2: Colocar Ngrok
Descarga Ngrok para Windows y extrae el archivo **`ngrok.exe`** directamente en la raíz de esta carpeta (en el mismo nivel donde está `start_aegis.bat`). 

*(El script `.bat` leerá automáticamente la variable `NGROK_AUTHTOKEN` de tu `.env` local antes de abrir el túnel).*

### Paso 3: Crear el Entorno Virtual e Instalar Librerías (Solo la primera vez)
Abre una consola (CMD) en la raíz del proyecto y ejecuta:

1. **Backend (Python .venv):**
   ```cmd
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Frontend (Node.js):**
   ```cmd
   cd ../frontend
   npm install
   ```

### Paso 4: Arrancar los servicios con la Consola Unificada
1. Abre **Docker Desktop** en tu ordenador.
2. Ejecuta el archivo **`start_aegis.bat`** (o ejecuta `python aegis_console.py`).
3. Todos los servicios (**Docker Compose**, **Backend FastAPI**, **Worker Celery**, **Frontend Next.js** y **Túnel Ngrok**) se iniciarán y supervisarán en una **única consola unificada**, con logs coloreados en tiempo real y panel de tracking.
4. **Comandos interactivos disponibles en la consola:**
   * `t` o `track` / `status`: Muestra el panel completo de tracking en tiempo real (estado de BD, Qdrant, Celery, documentos indexados, total de chunks, URL pública).
   * `d` o `docs`: Muestra la tabla de documentos y videotutoriales con su estado de indexación.
   * `h` o `health`: Ejecuta un chequeo de salud en vivo de todos los subsistemas.
   * `u` o `urls`: Muestra las URLs activas (Frontend, API Docs, Qdrant UI, Ngrok).
   * `r <servicio>`: Reinicia en caliente un servicio individual (`r backend`, `r celery`, `r frontend`, `r ngrok`).
   * `q` o `quit`: Cierre limpio y ordenado de todos los subprocesos.

---

## 💻 Panel de Control y Chat (http://localhost:3000)

Una vez arrancado, entra en [http://localhost:3000](http://localhost:3000) para acceder al panel integral:

### 1. Gestión de Manuales PDF
* **Subida por arrastre (*Drag & Drop*):** Sube manuales PDF para procesamiento asíncrono con extracción de texto y OCR automático.
* **Visor Interactivo Lateral:** Al hacer clic en citas del PDF (`[archivo.pdf, pág. X]`), se abre el visor lateral derecho en la página exacta con resaltado visual del fragmento.

### 2. Sincronización de Videotutoriales de YouTube
* **Ingestión Dinámica de Canales:** Introduce un ID o URL de canal de YouTube (o pulsa *Sincronizar* para usar el configurado en `.env`).
* **Extracción de Transcripciones y Timestamps:** El worker descarga los subtítulos, los fragmenta en bloques temporales de 90 segundos y los indexa en Qdrant.
* **Apertura Directa al Segundo Exacto:** Al pulsar en citas de vídeo (`[Video: Título, seg. X]`) o en el botón superior *Ver tutorial en YouTube*, se abre la plataforma oficial de YouTube en el segundo concreto donde se explica el concepto.

### 3. Selección y Filtros Inteligentes
* **Casillas Maestras de Selección:** Checkboxes en los encabezados para seleccionar o deseleccionar todos los PDFs o todos los videotutoriales con contadores activos.
* **Síntesis Multifuente:** Si marcas tanto manuales PDF como vídeos, Aegisito fusiona ambas fuentes en una sola respuesta detallada y cita cada dato en su contexto.

---

## 🔍 Herramientas de Inspección y Diagnóstico
* **Panel de Qdrant (Base Vectorial):** [http://localhost:6333/dashboard](http://localhost:6333/dashboard) (colección `aegis_chunks`).
* **Documentación Interactiva de la API (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs).
* **Verificación de Salud:** `GET http://localhost:8000/api/v1/health`.

---

## 🛠️ Solución de Problemas en Indexación de Vídeos (YouTube)

YouTube bloquea de forma muy agresiva las solicitudes automatizadas sin cookies de sesión (dando el error `IP blocked / Rate Limit` en los logs del worker de Celery). Para solucionarlo o saltártelo si algún vídeo falla:

### Opción A: Configurar Cookies de Sesión (Recomendado)
1. Instala la extensión **[Cookie-Editor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhgoadkfgghfacnekggghhj)** en Chrome/Edge.
2. Ve a [youtube.com](https://www.youtube.com) (con tu cuenta logueada).
3. Abre la extensión, haz clic en **Export** y selecciona **Netscape** (copiará las cookies al portapapeles).
4. Crea un archivo llamado `youtube_cookies.txt` en la carpeta `backend/` y pega el contenido.
5. El worker de Celery leerá las cookies automáticamente en la siguiente descarga, evitando el baneo de IP.

### Opción B: Indexación Manual por Transcripción
Si prefieres indexar un vídeo pegando su transcripción manualmente usando el formato estándar de YouTube (`0:00 \n Texto`):
1. Copia la transcripción desde YouTube (*Mostrar transcripción*) o extráela de Gemini con `@YouTube`.
2. Guarda el texto de la transcripción en un archivo temporal llamado `temp_trans.txt` en `backend/scratch/`.
3. Ejecuta el indexador manual con el **ID del documento** correspondiente:
   ```cmd
   cd backend
   python -c "import sys; sys.path.append('scratch'); from index_manual_transcript import index_manual_video; text = open('scratch/temp_trans.txt', encoding='utf-8').read(); index_manual_video('ID_DEL_DOCUMENTO', text)"
   ```

### Recargar Documentos Atascados
Si tras un reinicio del backend o una caída del sistema algunos archivos o vídeos se han quedado atascados en estado `PROCESSING` o `PENDING` de forma perpetua:
```cmd
cd backend
python scratch/requeue_processing.py
```
Este script buscará los documentos pendientes o a medias, restablecerá su estado y los volverá a enviar a la cola de Celery automáticamente.

