# 🚀 Manual de Despliegue y Administración en VPS — AEGIS

Este documento sirve como manual oficial de referencia para administrar el servidor de producción (VPS) del proyecto **AEGIS** (asistente inteligente "Aegisito"). Contiene las instrucciones técnicas avanzadas para el administrador de sistemas y una guía simplificada dirigida a personal sin conocimientos de programación.

---

# 🛠️ PARTE 1: Guía Técnica Avanzada (SysAdmin)

## 1. Topología y Arquitectura Docker
La infraestructura en producción se orquesta mediante un fichero `docker-compose.prod.yml` que corre en la dirección IP **`57.131.148.194`** bajo una red interna de tipo bridge llamada `aegis-prod-network`.

Orquesta **7 contenedores Docker**:

| Servicio | Imagen / Origen | Puerto Host | Puerto Interno | Volumen Persistente | Propósito |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `postgres` | `postgres:16-alpine` | `5433` | `5432` | `aegisito_postgres_data` | Almacenamiento SQL relacional |
| `qdrant` | `qdrant/qdrant:v1.18.2` | `6333`, `6334` | `6333`, `6334` | `aegisito_qdrant_data` | Base de datos vectorial (RAG) |
| `redis` | `redis:7-alpine` | Ninguno | `6379` | Memoria temporal | Broker de mensajería para Celery |
| `backend` | `./backend/Dockerfile` | `8000` | `8000` | `./backend/uploads` | API FastAPI principal |
| `celery_worker`| `./backend/Dockerfile.worker` | Ninguno | Ninguno | `./backend/uploads` | Ejecución de tareas asíncronas |
| `celery_beat` | `./backend/Dockerfile.worker` | Ninguno | Ninguno | Ninguno | Planificador de tareas recurrentes |
| `frontend` | `./frontend/Dockerfile` | `3000` | `3000` | Ninguno | Aplicación Next.js Standalone |

---

## 2. Configuración del Entorno (`.env`)
El archivo de entorno está localizado en el VPS en `/home/ubuntu/opt/aegisito/backend/.env`.

### Variables Críticas de Producción:
* **`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`**: Credenciales de la base de datos PostgreSQL (`AEGIS` / `AEGIS_secret`).
* **`QDRANT_COLLECTION`**: Colección vectorial por defecto en producción (`Aegisito_chunks`).
* **`CORS_ORIGINS`**: Lista en formato JSON de orígenes permitidos:
  `["http://localhost:3000", "http://localhost:8000", "https://aegisformacion.com", "https://www.aegisformacion.com", "https://formacion.aegis.es"]`
* **`AEGIS_SECURITY_TOKEN`**: Clave de comunicación interna segura entre servicios.
* **`LLM_PROVIDER` / `LLM_MODEL`**: Proveedor del modelo (`groq`, `gemini`, o `deepseek`) y modelo exacto a ejecutar (ej. `openai/gpt-oss-120b`, `gemini-3.6-flash`, o `deepseek-chat`).
  > [!IMPORTANT]
  > Google retira modelos obsoletos con frecuencia. Antes de configurar `LLM_MODEL` para Gemini, consulta la [lista oficial de modelos vigentes en Google AI Studio](https://ai.google.dev/gemini-api/docs/models?hl=es-419) para asegurarte de que el modelo seleccionado sigue activo y no devuelve un error 404.
* **Claves de API (`GROQ_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`)**: Claves de API para los respectivos proveedores. Es completamente compatible y seguro definir múltiples API keys en el archivo al mismo tiempo; el sistema utilizará única y exclusivamente la clave que corresponda al proveedor indicado en `LLM_PROVIDER`, ignorando las demás.

---

## 3. Guía de Operaciones en Producción (Línea de Comandos)

### Requisito Inicial: Volúmenes Persistentes
Antes del primer arranque en una máquina limpia, se deben crear manualmente los volúmenes externos definidos en Docker Compose para evitar fallos de inicialización:
```bash
sudo docker volume create aegisito_postgres_data
sudo docker volume create aegisito_qdrant_data
```

### Inicialización Completa:
Para compilar y levantar toda la pila en segundo plano:
```bash
sudo docker compose -f docker-compose.prod.yml up -d --build
```

### Reconstrucción de un Servicio Específico (Ej: Backend):
Si solo se actualiza el código del backend, se puede compilar e iniciar de forma aislada para minimizar el tiempo de inactividad:
```bash
sudo docker compose -f docker-compose.prod.yml up -d --build backend celery_worker celery_beat
```

### Parada del Entorno:
```bash
sudo docker compose -f docker-compose.prod.yml down
```

### Monitoreo de Logs:
* **Ver logs generales en tiempo real:**
  ```bash
  sudo docker compose -f docker-compose.prod.yml logs -f --tail 100
  ```
* **Ver logs de un contenedor específico (Ej: backend):**
  ```bash
  sudo docker compose -f docker-compose.prod.yml logs -f backend
  ```

---

## 4. Matriz de Troubleshooting (Resolución de Conflictos)

### Error A: `volume "aegisito_postgres_data" is declared as external, but could not be found`
* **Causa:** El volumen relacional no fue inicializado en el host de producción.
* **Solución:** Ejecutar `sudo docker volume create aegisito_postgres_data` antes de arrancar los contenedores.

### Error B: `bind: address already in use` en puerto `5433` o `6380`
* **Causa:** Hay otra instancia de PostgreSQL o Redis instalada directamente sobre la máquina VPS (bare metal) bloqueando el puerto.
* **Solución:** Detener los servicios locales:
  ```bash
  sudo systemctl stop postgresql
  sudo systemctl disable postgresql
  ```

### Error C: La IA no responde o da mensaje de "Error al conectar con el servidor"
* **Causa:** El túnel base, el backend o Celery están caídos.
* **Solución:**
  1. Verificar el estado de los contenedores: `sudo docker ps`.
  2. Si el contenedor del backend está abajo, revisar los logs: `sudo docker compose -f docker-compose.prod.yml logs backend`.
  3. Si es un fallo de conexión a Redis, reiniciar la base de mensajes: `sudo docker compose -f docker-compose.prod.yml restart redis`.

### Error D: Límite de cuota excedido o error de API en el LLM
* **Causa:** El token del proveedor de la IA (`Groq`, `Gemini`, `DeepSeek`) superó su límite de llamadas gratuitas o la API Key ha expirado.
* **Solución:** Abrir el archivo `/home/ubuntu/opt/aegisito/backend/.env`, introducir una API Key válida y reiniciar el backend:
  ```bash
  sudo docker compose -f docker-compose.prod.yml restart backend celery_worker
  ```

---
---

# 🧸 PARTE 2: Guía Sencilla (Casi para bobos)

Para entender cómo funciona el servidor sin ser informático, imagínate esto: la **VPS** es como un ordenador que tenemos alquilado en internet y que nunca se apaga (está encendido las 24 horas del día, los 365 días del año). 

En lugar de instalar los programas directamente como harías en tu ordenador de casa, usamos **Docker**. Imagina que Docker es un puerto de barcos donde cada programa (`Base de datos`, `FastAPI Backend`, `Aegisito Chat`) está metido dentro de su propio **contenedor de mercancías metálico cerrado**. Ninguno molesta al otro y todos trabajan en equipo a través de cables invisibles.

---

## 1. El archivo de secretos y configuración (`.env`)
En la carpeta `/home/ubuntu/opt/aegisito/backend/` hay un archivo de texto llamado `.env`. Este archivo es como la libreta de contraseñas de Aegisito. Si alguna vez tienes que cambiar la clave de la IA o los dominios web autorizados, debes modificar este archivo.

* **GEMINI_API_KEY / GROQ_API_KEY / DEEPSEEK_API_KEY**: Las contraseñas o claves del proveedor que le da el cerebro a Aegisito. Puedes tener puestas varias claves al mismo tiempo sin problema; el servidor no se confundirá.
* **LLM_PROVIDER**: Aquí escribes qué IA está activa en ese momento. Pon `groq`, `gemini` o `deepseek`. El servidor solo mirará la clave de la IA que esté escrita aquí y guardará o ignorará las demás de forma segura.
* **LLM_MODEL**: El modelo exacto a usar. Ejemplos recomendados: `gemini-3.6-flash` para Gemini (o el último Flash estable disponible), `openai/gpt-oss-120b` para Groq, y `deepseek-chat` para DeepSeek.
  > [!IMPORTANT]
  > Google AI Studio depreca y apaga sus modelos antiguos muy rápido. Revisa siempre la [documentación de modelos de Google](https://ai.google.dev/gemini-api/docs/models?hl=es-419) antes de configurar este campo.

---

## 2. Cómo subir una actualización al servidor (Paso a Paso)

Si hemos hecho cambios en la oficina y queremos subirlos a la web de producción para que los clientes vean las mejoras:

1. **Empaquetar el código**: Genera el archivo comprimido `aegisito.zip` (que tiene las carpetas `backend`, `frontend`, etc.).
2. **Subir el archivo**: Abre un programa de transferencia como **FileZilla**, conéctate al servidor con la IP `57.131.148.194` usando tus credenciales de acceso, y arrastra el archivo `aegisito.zip` a la carpeta `/home/ubuntu/opt/aegisito/`.
3. **Abrir la consola del servidor**: Conéctate al servidor mediante la consola negra (terminal) ejecutando en tu ordenador:
   ```bash
   ssh ubuntu@57.131.148.194
   ```
4. **Limpiar el código viejo**: Entra a la carpeta y borra los archivos viejos copiando y pegando este comando (y luego pulsa Enter):
   ```bash
   cd /home/ubuntu/opt/aegisito && sudo rm -rf backend frontend docker docker-compose* README.md
   ```
5. **Descomprimir la actualización**: Extrae el contenido del zip copiando y pegando este comando:
   ```bash
   unzip aegisito.zip && rm aegisito.zip
   ```
6. **Aplicar los cambios**: Para que el ordenador de internet empiece a usar el nuevo código, ejecuta este comando:
   ```bash
   sudo docker compose -f docker-compose.prod.yml up -d --build backend celery_worker celery_beat
   ```
   *Esto apagará momentáneamente la versión anterior, leerá el nuevo código y encenderá la nueva versión en menos de un minuto.*

---

## 3. Recetario de Emergencia (¿Qué hago si algo falla?)

### Pregunta: "Aegisito no responde a las preguntas en la web, se queda cargando"
* **Solución rápida:** Conéctate a la consola negra (paso 3 anterior) y escribe el siguiente comando para reiniciar la máquina del chat:
  ```bash
  cd /home/ubuntu/opt/aegisito && sudo docker compose -f docker-compose.prod.yml restart backend celery_worker
  ```

### Pregunta: "Quiero ver qué está haciendo Aegisito por dentro ahora mismo"
* **Solución rápida:** Escribe esto en la consola negra para ver pasar en directo lo que piensa el backend:
  ```bash
  cd /home/ubuntu/opt/aegisito && sudo docker compose -f docker-compose.prod.yml logs -f backend
  ```
  *(Para salir de esa pantalla de texto y volver a escribir comandos normales, pulsa en tu teclado las teclas `Ctrl` + `C` a la vez).*

---
---

# 🔐 Acceso Protegido al Panel de Administración (`formacion.aegis.es`)

El panel de configuración y administración de vídeos de la IA está protegido mediante **Nginx HTTP Basic Auth**, una capa de seguridad perimetral que actúa *antes* de que la petición llegue a los contenedores Docker.

---

## 🛠️ PARTE TÉCNICA — Cómo funciona la autenticación Nginx

### Flujo de Autenticación
```
Navegador → HTTPS (puerto 443) → Nginx
                                    ↓
                         ¿Tiene credenciales válidas?
                            ├── NO → Responde 401 y muestra cuadro de login
                            └── SÍ → Verifica hash en /etc/nginx/.htpasswd
                                        └── Reenvía petición → Docker:3000 (frontend)
```

### Configuración del bloque Nginx
El fichero de configuración habitual está en `/etc/nginx/sites-available/aegisito` (o `default`):

```nginx
server {
    listen 443 ssl;
    server_name formacion.aegis.es;

    # Certificados SSL (Let's Encrypt / Certbot)
    ssl_certificate     /etc/letsencrypt/live/formacion.aegis.es/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/formacion.aegis.es/privkey.pem;

    # ── Protección con contraseña ──────────────────────────
    auth_basic           "Panel de Administración AEGIS";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Fichero `.htpasswd` — Algoritmo de Cifrado
Las contraseñas se almacenan en `/etc/nginx/.htpasswd` en el siguiente formato:
```
usuario:$apr1$randomsalt$hashcifrado
```

El prefijo `$apr1$` indica el algoritmo **APR1-MD5** (variante de MD5 usada por Apache/Nginx con 1000 iteraciones de sal). Nginx también acepta el prefijo `$2y$` para **bcrypt**, que es más robusto:

| Prefijo | Algoritmo | Seguridad |
|:---|:---|:---|
| `$apr1$` | APR1-MD5 | Media (legacy) |
| `{SHA}` | SHA-1 | Baja (no recomendado) |
| `$2y$` | bcrypt | Alta ✅ (recomendado) |

### Operaciones Administrativas con `.htpasswd`

#### Crear un usuario nuevo (bcrypt, recomendado):
```bash
sudo htpasswd -B /etc/nginx/.htpasswd nuevo_usuario
```

#### Cambiar la contraseña de un usuario existente:
```bash
sudo htpasswd -B /etc/nginx/.htpasswd nombre_usuario
```

#### Eliminar un usuario:
```bash
sudo htpasswd -D /etc/nginx/.htpasswd nombre_usuario
```

#### Ver los usuarios actuales (sin contraseñas, solo nombres):
```bash
sudo cut -d: -f1 /etc/nginx/.htpasswd
```

### Aplicar cambios tras modificar el fichero:
```bash
# Verificar que la configuración de Nginx no tiene errores de sintaxis
sudo nginx -t

# Recargar Nginx sin cortar las conexiones activas
sudo systemctl reload nginx
```

### Error E: "401 Authorization Required" al acceder a `formacion.aegis.es`
* **Causa:** Las credenciales son incorrectas o el fichero `.htpasswd` no existe/tiene mal la ruta.
* **Diagnóstico:**
  ```bash
  sudo cat /etc/nginx/.htpasswd   # ¿Existe el fichero?
  sudo nginx -t                   # ¿Tiene errores la config de Nginx?
  ```
* **Solución:** Recrear el fichero si no existe:
  ```bash
  sudo htpasswd -cB /etc/nginx/.htpasswd nombre_usuario
  sudo systemctl reload nginx
  ```

---

## 🧸 PARTE SENCILLA — La contraseña del panel de vídeos

Cuando alguien abre `formacion.aegis.es` en el navegador, le aparece un **cuadro de diálogo con usuario y contraseña**. Eso no lo gestiona Aegisito ni el código del chat, sino el servidor web llamado **Nginx**, que actúa como portero.

La contraseña **nunca se guarda en texto claro**. Se guarda revuelta (cifrada) en un fichero especial en el servidor llamado `.htpasswd`. Cuando el usuario escribe su contraseña, Nginx la revuelve de la misma manera y compara los resultados. Si coinciden, deja pasar.

### ¿Cómo cambio la contraseña?

1. Conéctate al servidor (consola negra):
   ```bash
   ssh ubuntu@57.131.148.194
   ```
2. Copia y pega este comando cambiando `nombre_usuario` por el usuario cuya contraseña quieres cambiar:
   ```bash
   sudo htpasswd -B /etc/nginx/.htpasswd nombre_usuario
   ```
3. Te pedirá la nueva contraseña dos veces. Cuando termines, no hace falta reiniciar nada.

### ¿Cómo añado un usuario nuevo?
El mismo comando sirve para crear usuarios nuevos si el usuario que escribes no existe todavía:
```bash
sudo htpasswd -B /etc/nginx/.htpasswd usuario_nuevo
```

### ¿Qué pasa si el panel no deja entrar a nadie?
Si nadie puede entrar al panel aunque la contraseña sea la correcta, prueba este comando para recargar el portero:
```bash
sudo systemctl reload nginx
```

