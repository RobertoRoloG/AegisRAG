// ============================================================
// AEGIS — Cliente API Frontend
// Interacciones HTTP asíncronas con el backend en puerto 8000
// ============================================================

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";

export interface DocumentUploadResponse {
  document_id: string;
  filename: string;
  status: string;
}

export interface DocumentStatusResponse {
  document_id: string;
  filename: string;
  status: string;
  document_type?: string;
  total_chunks: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  is_active?: boolean;
}

export interface SourceDocument {
  doc_id: string;
  filename: string;
  page_number: number;
  score: number;
  snippet: string;
  type?: "pdf" | "youtube";
  video_id?: string;
}

export interface LatencyBreakdown {
  retrieval: number;
  rewrite: number;
  generation: number;
  total: number;
}

export interface ChatQueryResponse {
  answer: string;
  sources: SourceDocument[];
  crag_status: "CORRECT" | "AMBIGUOUS" | "NO_DATA_FOUND";
  latency_ms: LatencyBreakdown;
  session_id: string;
}

export interface ChatHistoryMessage {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceDocument[];
  latency_ms?: LatencyBreakdown;
  crag_status?: "CORRECT" | "AMBIGUOUS" | "NO_DATA_FOUND";
  created_at: string;
}

export interface HealthResponse {
  status: "healthy" | "degraded";
  postgres: "up" | "down";
  qdrant: "up" | "down";
  redis: "up" | "down";
}

/**
 * Sube un archivo PDF al backend para procesamiento asíncrono.
 */
export async function uploadDocument(file: File): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${BACKEND_BASE_URL}/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al subir el archivo PDF");
  }

  return response.json();
}

/**
 * Consulta el estado actual de procesamiento de un documento.
 */
export async function getDocumentStatus(documentId: string): Promise<DocumentStatusResponse> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/documents/${documentId}/status`);
    if (response.ok) {
      return await response.json();
    }
  } catch (err) {
    console.warn(`[Aegis API] Error de conexión al consultar estado de doc ${documentId}:`, err);
  }
  
  return {
    document_id: documentId,
    filename: "",
    status: "PROCESSING",
    total_chunks: null,
    error_message: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_active: true,
  };
}

/**
 * Envía una consulta de RAG al motor de chat con memoria conversacional.
 */
export async function queryChat(
  query: string, 
  documentIds: string[], 
  sessionId?: string,
  signal?: AbortSignal
): Promise<ChatQueryResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/chat/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      document_ids: documentIds,
      session_id: sessionId || undefined,
    }),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al procesar la consulta en el chat");
  }

  return response.json();
}

/**
 * Recupera el historial completo de mensajes para una sesión de forma segura.
 */
export async function getChatHistory(sessionId: string): Promise<ChatHistoryMessage[]> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/chat/history/${sessionId}`);
    if (!response.ok) return [];
    return await response.json();
  } catch (err) {
    console.warn("[Aegis API] No se pudo recuperar historial de chat:", err);
    return [];
  }
}

/**
 * Limpia el historial de una sesión.
 */
export async function clearChatHistory(sessionId: string): Promise<void> {
  try {
    await fetch(`${BACKEND_BASE_URL}/chat/history/${sessionId}`, {
      method: "DELETE",
    });
  } catch (err) {
    console.warn("[Aegis API] Error al limpiar historial:", err);
  }
}

export interface FAQItem {
  text: string;
  desc: string;
}

/**
 * Obtiene las preguntas frecuentes del sistema de forma dinámica y estructurada.
 */
export async function getPopularQuestions(): Promise<FAQItem[]> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/chat/popular-questions`);
    if (!response.ok) return [];
    return await response.json();
  } catch (err) {
    console.warn("[Aegis API] Error al cargar preguntas frecuentes:", err);
    return [];
  }
}

/**
 * Verifica la salud general de los servicios del backend de forma segura.
 */
export async function checkBackendHealth(): Promise<HealthResponse> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/health`);
    if (!response.ok && response.status !== 503) {
      return { status: "degraded", postgres: "down", qdrant: "down", redis: "down" };
    }
    return await response.json();
  } catch (err) {
    return { status: "degraded", postgres: "down", qdrant: "down", redis: "down" };
  }
}

export interface DocumentItem {
  document_id: string;
  filename: string;
  file_path?: string;
  status: string;
  document_type?: string;
  total_chunks: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  is_active?: boolean;
}

/**
 * Obtiene el listado de todos los documentos y su estado con reintentos automáticos.
 */
export async function listDocuments(retries: number = 3): Promise<DocumentItem[]> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const response = await fetch(`${BACKEND_BASE_URL}/documents/`, {
        cache: "no-store",
      });
      
      if (response.ok) {
        return await response.json();
      }
      
      if (attempt < retries) {
        await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
      }
    } catch (err) {
      if (attempt < retries) {
        await new Promise((resolve) => setTimeout(resolve, 800 * attempt));
      } else {
        console.warn("[Aegis API] Backend no disponible temporalmente para /documents/:", err);
      }
    }
  }

  return [];
}

/**
 * Elimina un documento, su archivo físico y sus vectores.
 */
export async function deleteDocument(documentId: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${BACKEND_BASE_URL}/documents/${documentId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al eliminar el documento");
  }

  return response.json();
}

/**
 * Retorna la URL para acceder al archivo PDF original.
 */
export function getDocumentFileUrl(documentId: string): string {
  return `${BACKEND_BASE_URL}/documents/${documentId}/file`;
}

/**
 * Importa una transcripción manual (.vtt o .txt) de un vídeo de YouTube.
 */
export async function uploadYoutubeTranscript(
  videoUrl: string,
  title: string,
  transcriptFile: File
): Promise<{ document_id: string; filename: string; status: string }> {
  const formData = new FormData();
  formData.append("video_url", videoUrl);
  formData.append("title", title);
  formData.append("transcript_file", transcriptFile);

  const response = await fetch(`${BACKEND_BASE_URL}/documents/youtube-transcript`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al importar la transcripción del vídeo");
  }

  return response.json();
}

/**
 * Lanza la sincronización manual de vídeos de YouTube.
 */
export async function syncYoutubeVideos(
  channelUrl?: string,
  fullScan: boolean = false
): Promise<{ status: string; message: string; added?: number }> {
  const body = JSON.stringify({
    channel_url: channelUrl || undefined,
    full_scan: fullScan,
  });

  const response = await fetch(`${BACKEND_BASE_URL}/documents/sync-youtube`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al sincronizar los vídeos de YouTube");
  }

  return response.json();
}

/**
 * Obtiene la configuración por defecto del canal de YouTube desde el backend.
 */
export async function getYoutubeChannelConfig(): Promise<{ channel_id: string; channel_url: string }> {
  try {
    const response = await fetch(`${BACKEND_BASE_URL}/documents/youtube-channel`);
    if (response.ok) {
      return await response.json();
    }
  } catch (err) {
    console.warn("[Aegis API] Canal de YouTube fallback:", err);
  }

  return { channel_id: "default", channel_url: "https://www.youtube.com/@MAIS_IA" };
}

export interface ToggleDocumentResponse {
  document_id: string;
  is_active: boolean;
}

/**
 * Activa o desactiva un documento en el sistema para las búsquedas de RAG.
 */
export async function toggleDocument(documentId: string): Promise<ToggleDocumentResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/documents/${documentId}/toggle`, {
    method: "PATCH",
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al cambiar el estado del documento");
  }

  return response.json();
}



