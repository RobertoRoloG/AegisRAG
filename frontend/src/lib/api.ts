// ============================================================
// AegisRAG — Cliente API Frontend
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
  total_chunks: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceDocument {
  doc_id: string;
  filename: string;
  page_number: number;
  score: number;
  snippet: string;
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
  const response = await fetch(`${BACKEND_BASE_URL}/documents/${documentId}/status`);
  
  if (!response.ok) {
    throw new Error("No se pudo obtener el estado del documento");
  }

  return response.json();
}

/**
 * Envía una consulta de RAG al motor de chat.
 */
export async function queryChat(query: string, documentIds: string[]): Promise<ChatQueryResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/chat/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      document_ids: documentIds,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || "Error al procesar la consulta en el motor CRAG");
  }

  return response.json();
}

/**
 * Verifica la salud general de los servicios del backend.
 */
export async function checkBackendHealth(): Promise<HealthResponse> {
  const response = await fetch(`${BACKEND_BASE_URL}/health`);
  
  if (!response.ok && response.status !== 503) {
    throw new Error("Backend inalcanzable");
  }

  return response.json();
}

export interface DocumentItem {
  document_id: string;
  filename: string;
  status: string;
  total_chunks: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Obtiene el listado de todos los documentos y su estado.
 */
export async function listDocuments(): Promise<DocumentItem[]> {
  const response = await fetch(`${BACKEND_BASE_URL}/documents/`);
  
  if (!response.ok) {
    throw new Error("No se pudo obtener el listado de documentos");
  }

  return response.json();
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

