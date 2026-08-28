# AEGIS - Asistente RAG Multifuente con Personalidad de Aegisito (Pack Portable)

Este es el backend y el panel de control local del asistente inteligente RAG (*Retrieval-Augmented Generation*) para **AEGIS** (Programas de facturación y gestión contable).

El sistema es completamente **portable** y dinámico. Al utilizar rutas relativas y variables cargadas de forma local, puedes mover esta carpeta completa a cualquier ordenador y funcionará sin tener que alterar las configuraciones internas de Windows.

---

## 🛠️ Arquitectura y Tecnologías
* **Motor Backend:** Python 3.14+ con FastAPI (asíncrono).
* **Motor CRAG (Corrective RAG):** Búsqueda híbrida (densa con `BAAI/bge-small-en-v1.5` + esparsa con `SPLADE`) y re-ranking con Cross-Encoder (`BAAI/bge-reranker-base`).
* **Base de Datos Vectorial:** Qdrant (almacén persistente de embeddings para PDFs y fragmentos temporales de vídeo con panel en `http://localhost:6333/dashboard`).
* **Cola de Ingesta Asíncrona:** Celery (con Redis como broker de tareas en segundo plano).
* **Base de Datos Relacional:** PostgreSQL 16 (metadatos de documentos, vídeos, historial y estado de procesamiento).
* **LLM:** Groq LPU (`llama-3.1-8b-instant`) para respuestas ultra rápidas con citas inline obligatorias.
* **Frontend:** Next.js 15 + React 19 + TailwindCSS (panel de gestión de documentos, reproductor de citas y chat interactivo).
* **Controlador de Túnel:** Ngrok (para exponer el servidor local a internet y conectar la web externa).

---

## 🚀 Requisitos para Servidor Local (Otro Ordenador)
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

### Paso 4: Arrancar los servicios
1. Abre **Docker Desktop** en el nuevo ordenador.
2. Ejecuta el archivo **`start_aegis.bat`** haciendo doble clic.
3. Se abrirán las terminales independientes levantando las bases de datos en Docker, el worker de Celery, el Backend de FastAPI, el Frontend en Next.js y el túnel seguro de Ngrok.

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

