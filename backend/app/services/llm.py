"""
AEGIS — Servicio LLM modular y desacoplado mediante Patrón Strategy y Herencia.

Arquitectura:
- BaseLLMProvider (Clase base abstracta)
  ├── OpenAICompatibleProvider (Base para APIs con esquema OpenAI)
  │    ├── OpenAIProvider
  │    ├── GroqProvider
  │    └── DeepSeekProvider
  ├── GeminiProvider (Google AI Studio API)
  ├── OllamaProvider (Inferencia local)
  └── MockProvider (Simulación offline para testing y desarrollo)
- LLMProviderFactory: Factoría para instanciar el proveedor óptimo.
- LLMService: Facade de alto nivel con soporte de reescritura conversacional.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Optional
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# =============================================================================
# CLASE BASE ABSTRACTA
# =============================================================================
class BaseLLMProvider(ABC):
    """Interfaz base abstracta para todos los proveedores de modelos de lenguaje."""

    def __init__(self, model: str) -> None:
        self.model = model

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Genera una respuesta textual a partir de un prompt y system prompt."""
        pass


# =============================================================================
# PROVEEDOR BASE COMPATIBLE CON OPENAI
# =============================================================================
class OpenAICompatibleProvider(BaseLLMProvider):
    """
    Proveedor reutilizable para cualquier API compatible con la especificación
    OpenAI Chat Completions (OpenAI, Groq, DeepSeek, Together, etc.).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        max_tokens: int = 2048,
        provider_name: str = "OpenAI-Compatible",
    ) -> None:
        super().__init__(model)
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.provider_name = provider_name

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": self.max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                choice_msg = data["choices"][0]["message"]
                # Soporta respuestas con contenido estándar o reasoning de modelos R1
                content = choice_msg.get("content") or choice_msg.get("reasoning") or ""
                return str(content).strip()
            except Exception as exc:
                logger.error("Error conectando con %s: %s", self.provider_name, exc)
                raise


# =============================================================================
# IMPLEMENTACIONES DERIVADAS DE OPENAI COMPATIBLE
# =============================================================================
class OpenAIProvider(OpenAICompatibleProvider):
    """Proveedor oficial para la API de OpenAI."""

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(
            api_key=api_key,
            base_url="https://api.openai.com/v1/chat/completions",
            model=model,
            provider_name="OpenAI",
        )


class GroqProvider(OpenAICompatibleProvider):
    """Proveedor de inferencia ultrarrápida Groq."""

    def __init__(self, api_key: str, model: str) -> None:
        # Mapeo a modelos estándar soportados en Groq
        active_model = model
        if active_model in ["llama3", "llama", "llama-3", "mock", "llama-3.1-8b-instant"]:
            active_model = "openai/gpt-oss-120b"

        super().__init__(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1/chat/completions",
            model=active_model,
            provider_name="Groq",
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    """Proveedor oficial para la API de DeepSeek."""

    def __init__(self, api_key: str, model: str) -> None:
        active_model = model
        if active_model in ["deepseek", "mock", "openai/gpt-oss-120b", "llama3", "llama-3.1-8b-instant", "gemini-1.5-flash"]:
            active_model = "deepseek-chat"

        super().__init__(
            api_key=api_key,
            base_url="https://api.deepseek.com/chat/completions",
            model=active_model,
            provider_name="DeepSeek",
        )


# =============================================================================
# PROVEEDOR GOOGLE GEMINI
# =============================================================================
class GeminiProvider(BaseLLMProvider):
    """Proveedor para Google AI Studio (Gemini)."""

    def __init__(self, api_key: str, model: str) -> None:
        active_model = model
        if active_model in ["gemini", "mock", "openai/gpt-oss-120b", "llama3", "llama-3.1-8b-instant", "deepseek-chat"]:
            active_model = "gemini-3.6-flash"
        super().__init__(active_model)
        self.api_key = api_key

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0},
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["candidates"][0]["content"]["parts"][0]["text"]).strip()
            except Exception as exc:
                logger.error("Error conectando con Gemini: %s", exc)
                raise


# =============================================================================
# PROVEEDOR OLLAMA LOCAL
# =============================================================================
class OllamaProvider(BaseLLMProvider):
    """Proveedor para servidores locales de Ollama."""

    def __init__(self, base_url: str, model: str) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"temperature": 0.0},
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return str(data["response"]).strip()
            except Exception as exc:
                logger.error("Error conectando con Ollama en %s: %s", self.base_url, exc)
                raise


# =============================================================================
# PROVEEDOR MOCK OFFLINE
# =============================================================================
class MockProvider(BaseLLMProvider):
    """Simulación inteligente offline para desarrollo y testing sin consumo de APIs."""

    def __init__(self, model: str = "mock") -> None:
        super().__init__(model)

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
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

        answer_parts = []
        if "implement" in prompt.lower() or "what" in prompt.lower() or "resumen" in prompt.lower():
            answer_parts.append(
                f"De acuerdo a la documentación indexada, AEGIS implementa búsqueda híbrida y re-ranking "
                f"[{files_found[0][0]}, pág. {files_found[0][1]}]."
            )
            if len(files_found) > 1:
                answer_parts.append(
                    f"Adicionalmente, se detalla la extracción y estructuración semántica de datos "
                    f"[{files_found[1][0]}, pág. {files_found[1][1]}]."
                )
        else:
            answer_parts.append(
                f"Información recuperada del documento: {snippets[0][:150]}... "
                f"[{files_found[0][0]}, pág. {files_found[0][1]}]."
            )

        return " ".join(answer_parts)


# =============================================================================
# REGISTRO Y FACTORY DECLARATIVO (REGISTRY PATTERN)
# =============================================================================
def _check_ollama() -> bool:
    try:
        with httpx.Client(timeout=1.0) as client:
            return client.get(settings.ollama_base_url).status_code == 200
    except Exception:
        return False


_PROVIDER_REGISTRY: dict[str, Any] = {
    "openai": lambda m: OpenAIProvider(settings.openai_api_key, m) if settings.openai_api_key else None,
    "groq": lambda m: GroqProvider(settings.groq_api_key, m) if settings.groq_api_key else None,
    "gemini": lambda m: GeminiProvider(settings.gemini_api_key, m) if settings.gemini_api_key else None,
    "deepseek": lambda m: DeepSeekProvider(settings.deepseek_api_key, m) if settings.deepseek_api_key else None,
    "ollama": lambda m: OllamaProvider(settings.ollama_base_url, m) if _check_ollama() else None,
    "custom": lambda m: (
        OpenAICompatibleProvider(
            api_key=settings.llm_api_key or "",
            base_url=settings.llm_base_url or "",
            model=m,
            provider_name="Custom",
        )
        if settings.llm_base_url and settings.llm_api_key
        else None
    ),
    "mock": lambda m: MockProvider(m),
}


class LLMProviderFactory:
    """Factoría declarativa basada en registro dinámico (cero condicionales encadenados)."""

    @staticmethod
    def create_provider() -> tuple[BaseLLMProvider, str]:
        provider_name = settings.llm_provider.lower()
        builder = _PROVIDER_REGISTRY.get(provider_name)
        
        provider = builder(settings.llm_model) if builder else None
        if provider:
            return provider, provider_name

        logger.warning("Proveedor '%s' no disponible o sin credenciales. Activando MockProvider.", provider_name)
        return MockProvider(settings.llm_model), "mock"


# =============================================================================
# SERVICIO LLM PRINCIPAL (FACADE)
# =============================================================================
class LLMService:
    """
    Fachada de alto nivel para interactuar con el proveedor LLM activo.
    Ofrece generación directa y reescritura de consultas contextuales.
    """

    def __init__(self) -> None:
        self.provider, self.provider_name = LLMProviderFactory.create_provider()
        self.model = self.provider.model
        logger.info(
            "Servicio LLM inicializado. Proveedor final: %s, Modelo: %s",
            self.provider_name,
            self.model,
        )

    async def generate_response(self, prompt: str, system_prompt: str = "") -> str:
        """Genera una respuesta delegando en el proveedor polimórfico activo."""
        return await self.provider.generate(prompt, system_prompt)

    async def rewrite_query(self, query: str, history: Optional[list[dict[str, str]]] = None) -> str:
        """Reescribe una consulta para optimizar la búsqueda semántica con contexto previo."""
        if self.provider_name == "mock":
            logger.info("Mocking query rewrite...")
            return f"{query} Hybrid Search Retrieval Corrective RAG"

        history_str = ""
        if history:
            history_lines = []
            for t in history[-4:]:
                role_label = "Usuario" if t.get("role") == "user" else "AEGIS"
                content = t.get("content", "")
                if len(content) > 400:
                    content = content[:400] + "..."
                history_lines.append(f"{role_label}: {content}")
            history_str = "Historial de conversación previo:\n" + "\n".join(history_lines) + "\n\n"

        system_prompt = (
            "Eres un asistente de recuperación de información de nivel experto. "
            "Tu tarea es analizar la consulta del usuario (y el historial si lo hay) y reescribirla de forma clara, "
            "eliminando ambigüedades, reemplazando pronombres ('eso', 'el anterior', 'lo') por los conceptos reales "
            "y deduciendo términos clave contextuales para mejorar la búsqueda semántica. "
            "Devuelve ÚNICAMENTE la consulta reescrita, sin introducciones, sin explicaciones y sin comillas."
        )
        prompt = f"{history_str}Consulta del usuario a reformular: {query}"

        try:
            rewritten = await self.generate_response(prompt, system_prompt)
            rewritten_clean = rewritten.strip().replace('"', "").replace("'", "")
            logger.info("Consulta reescrita de '%s' a '%s'", query, rewritten_clean)
            return rewritten_clean
        except Exception as exc:
            logger.warning("Fallo al reescribir la consulta: %s. Usando original.", exc)
            return query


# Instancia singleton para uso en toda la aplicación
llm_service = LLMService()


def get_llm_service() -> LLMService:
    """Retorna la instancia singleton del servicio LLM."""
    return llm_service
