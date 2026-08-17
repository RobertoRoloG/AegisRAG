"""
AegisRAG — Servicio LLM centralizado.

Soporta:
1. OpenAI (Cloud comercial)
2. Groq (Cloud ultrarrápido y gratuito)
3. Ollama (Inferencia local)
4. Mock (Desarrollo local sin dependencias)
"""

import logging
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """Servicio para interactuar con LLMs locales (Ollama), cloud (OpenAI/Groq) o simulados (Mock)."""

    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower()
        self.model = settings.llm_model
        self.base_url = settings.ollama_base_url
        self.openai_key = settings.openai_api_key
        self.groq_key = settings.groq_api_key

        # Validar conectividad con Ollama, OpenAI o Groq, si no hay, caemos en Mock automáticamente
        self._detect_best_provider()

    def _detect_best_provider(self) -> None:
        """Verifica la conectividad y ajusta el proveedor si es necesario."""
        if self.provider == "openai" and not self.openai_key:
            logger.warning("OPENAI_API_KEY no configurada. Activando proveedor 'mock' para desarrollo local.")
            self.provider = "mock"

        elif self.provider == "groq" and not self.groq_key:
            logger.warning("GROQ_API_KEY no configurada. Activando proveedor 'mock' para desarrollo local.")
            self.provider = "mock"
        
        elif self.provider == "ollama":
            # Test rápido de conexión síncrona
            try:
                with httpx.Client(timeout=1.0) as client:
                    r = client.get(self.base_url)
                    if r.status_code != 200:
                        raise httpx.ConnectError("Ollama no devolvió 200 OK")
            except Exception:
                logger.warning(
                    "No se detectó Ollama corriendo en %s. "
                    "Activando proveedor 'mock' temporalmente para verificar el pipeline.",
                    self.base_url
                )
                self.provider = "mock"

        logger.info(
            "Servicio LLM inicializado. Proveedor final: %s, Modelo: %s",
            self.provider,
            self.model,
        )

    async def generate_response(self, prompt: str, system_prompt: str = "") -> str:
        """Genera una respuesta de texto basada en un prompt y un system prompt opcional."""
        if self.provider == "openai":
            return await self._call_openai(prompt, system_prompt)
        elif self.provider == "groq":
            return await self._call_groq(prompt, system_prompt)
        elif self.provider == "ollama":
            return await self._call_ollama(prompt, system_prompt)
        elif self.provider == "mock":
            return await self._call_mock(prompt)
        else:
            raise ValueError(f"Proveedor de LLM no soportado: '{self.provider}'")

    async def rewrite_query(self, query: str) -> str:
        """Reescribe una consulta de usuario para optimizar la recuperación semántica."""
        if self.provider == "mock":
            # Mock de reescritura simple agregando sinónimos de RAG
            logger.info("Mocking query rewrite...")
            return f"{query} Hybrid Search Retrieval Corrective RAG"

        system_prompt = (
            "Eres un asistente de recuperación de información de nivel experto. "
            "Tu tarea es analizar la consulta del usuario y reescribirla de forma clara, "
            "eliminando ambigüedades y añadiendo términos clave relacionados para mejorar "
            "la búsqueda semántica y de palabras clave. "
            "Devuelve ÚNICAMENTE la consulta reescrita, sin introducciones ni comentarios."
        )
        prompt = f"Consulta original: {query}"
        
        try:
            rewritten = await self.generate_response(prompt, system_prompt)
            rewritten_clean = rewritten.strip().replace('"', '').replace("'", "")
            logger.info("Consulta reescrita de '%s' a '%s'", query, rewritten_clean)
            return rewritten_clean
        except Exception as exc:
            logger.warning("Fallo al reescribir la consulta: %s. Usando original.", exc)
            return query

    async def _call_ollama(self, prompt: str, system_prompt: str) -> str:
        """Realiza una llamada asíncrona a la API local de Ollama."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"temperature": 0.0}
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["response"]).strip()
            except Exception as exc:
                logger.error("Error conectando con Ollama: %s", exc)
                raise

    async def _call_openai(self, prompt: str, system_prompt: str) -> str:
        """Realiza una llamada asíncrona a la API oficial de OpenAI."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["choices"][0]["message"]["content"]).strip()
            except Exception as exc:
                logger.error("Error conectando con OpenAI: %s", exc)
                raise

    async def _call_groq(self, prompt: str, system_prompt: str) -> str:
        """Realiza una llamada asíncrona a la API oficial de Groq (OpenAI-compatible)."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }
        
        # Mapear modelos estándar a modelos activos de Groq
        # Groq no soporta modelos genéricos como 'llama3', requiere nombres específicos
        groq_model = self.model
        if groq_model in ["llama3", "llama3.2", "llama", "llama-3.1-8b-instant"]:
            groq_model = "openai/gpt-oss-20b"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": groq_model,
            "messages": messages,
            "temperature": 0.0,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["choices"][0]["message"]["content"]).strip()
            except Exception as exc:
                logger.error("Error conectando con Groq: %s", exc)
                raise

    async def _call_mock(self, prompt: str) -> str:
        """Genera una respuesta simulada inteligente basada en los fragmentos del prompt."""
        # Extraer fragmentos del prompt para construir una respuesta simulada con citas correctas
        lines = prompt.split("\n")
        files_found = []
        snippets = []

        current_file = ""
        current_page = ""
        
        for line in lines:
            if line.startswith("Archivo:"):
                current_file = line.split(":", 1)[1].strip()
            elif line.startswith("Página:"):
                current_page = line.split(":", 1)[1].strip()
            elif line.startswith("Contenido:"):
                content = line.split(":", 1)[1].strip()
                if current_file and current_page:
                    files_found.append((current_file, current_page))
                    snippets.append(content)
                    current_file = ""
                    current_page = ""

        if not snippets:
            return "Lo siento, no he encontrado información en los fragmentos provistos para responder."

        # Simular una respuesta estructurada
        answer_parts = []
        if "implement" in prompt.lower() or "what" in prompt.lower():
            answer_parts.append(
                f"De acuerdo a la documentación, AegisRAG implementa Búsqueda Híbrida y Re-Ranking "
                f"junto con un sistema de Ingestión Asíncrona [{files_found[0][0]}, pág. {files_found[0][1]}]."
            )
            if len(files_found) > 1:
                answer_parts.append(
                    f"Adicionalmente, se menciona que el pipeline de ingestión divide el texto en chunks y "
                    f"genera los embeddings de forma local con FastEmbed ejecutándose en CPU [{files_found[1][0]}, pág. {files_found[1][1]}]."
                )
        else:
            answer_parts.append(
                f"Información recuperada del documento: {snippets[0][:150]}... "
                f"[{files_found[0][0]}, pág. {files_found[0][1]}]."
            )

        return " ".join(answer_parts)


# Instancia singleton para uso en toda la aplicación
llm_service = LLMService()


def get_llm_service() -> LLMService:
    """Retorna la instancia singleton del servicio LLM."""
    return llm_service
