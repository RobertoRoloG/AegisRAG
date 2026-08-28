"use client";

import React, { useState, useRef, useEffect } from "react";
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, Trash2, Search, Video, RotateCw, Play, Eye, EyeOff } from "lucide-react";
import { uploadDocument, getDocumentStatus, listDocuments, deleteDocument, DocumentStatusResponse, syncYoutubeVideos, getYoutubeChannelConfig, toggleDocument } from "../lib/api";

export interface TrackedDocument {
  id: string;
  filename: string;
  file_path?: string;
  status: string;
  document_type?: string;
  totalChunks: number | null;
  errorMessage: string | null;
  is_active: boolean;
}

interface DocumentSidebarProps {
  onOpenDocument: (docId: string, filename: string, type: "pdf" | "youtube", filePath?: string) => void;
}

export default function DocumentSidebar({ onOpenDocument }: DocumentSidebarProps) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<TrackedDocument[]>([]);
  const [pdfSearchTerm, setPdfSearchTerm] = useState("");
  const [ytSearchTerm, setYtSearchTerm] = useState("");
  const [width, setWidth] = useState(400);
  const isResizing = useRef(false);

  useEffect(() => {
    const savedWidth = localStorage.getItem("aegis_sidebar_width");
    if (savedWidth) {
      setWidth(parseInt(savedWidth, 10));
    }
  }, []);

  const handleMouseMove = (mouseMoveEvent: MouseEvent) => {
    if (!isResizing.current) return;
    const newWidth = mouseMoveEvent.clientX;
    if (newWidth >= 280 && newWidth <= 650) {
      setWidth(newWidth);
      localStorage.setItem("aegis_sidebar_width", newWidth.toString());
    }
  };

  const handleMouseUp = () => {
    isResizing.current = false;
    document.removeEventListener("mousemove", handleMouseMove);
    document.removeEventListener("mouseup", handleMouseUp);
  };

  const startResizing = (mouseDownEvent: React.MouseEvent) => {
    mouseDownEvent.preventDefault();
    isResizing.current = true;
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [syncingYt, setSyncingYt] = useState(false);
  const activePollsRef = useRef<{ [key: string]: NodeJS.Timeout }>({});
  
  const [channelUrl, setChannelUrl] = useState("");
  const [toast, setToast] = useState<{message: string, type: "success" | "error"} | null>(null);

  const showToast = (message: string, type: "success" | "error" = "success") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 5000);
  };

  useEffect(() => {
    const savedUrl = localStorage.getItem("aegis_youtube_channel_url");
    if (savedUrl) {
      setChannelUrl(savedUrl);
    } else {
      getYoutubeChannelConfig()
        .then((cfg) => {
          if (cfg && cfg.channel_url) {
            setChannelUrl(cfg.channel_url);
          }
        })
        .catch((err) => {
          console.warn("No se pudo cargar el canal por defecto del backend:", err);
        });
    }
  }, []);

  const handleChannelUrlChange = (val: string) => {
    setChannelUrl(val);
    localStorage.setItem("aegis_youtube_channel_url", val);
  };


  const handleSyncYoutube = async () => {
    setSyncingYt(true);
    setError(null);
    try {
      const result = await syncYoutubeVideos(channelUrl);
      const data = await listDocuments();
      const formatted: TrackedDocument[] = data.map((d) => ({
        id: d.document_id,
        filename: d.filename,
        file_path: d.file_path,
        status: d.status,
        document_type: d.document_type || "pdf",
        totalChunks: d.total_chunks,
        errorMessage: d.error_message,
        is_active: d.is_active,
      }));
      setDocuments(formatted);
      
      formatted.forEach((doc) => {
        if (doc.status === "PENDING" || doc.status === "PROCESSING") {
          startPolling(doc.id, doc.filename);
        }
      });
      if (result.added && result.added > 0) {
        showToast(`Se han encontrado y encolado ${result.added} vídeos nuevos.`, "success");
      } else {
        showToast("Sincronización completada. No hay vídeos nuevos.", "success");
      }
    } catch (err: any) {
      setError(err.message || "Error al sincronizar vídeos de YouTube.");
    } finally {
      setSyncingYt(false);
    }
  };

  useEffect(() => {
    async function loadDocs() {
      try {
        const data = await listDocuments();
        const formatted: TrackedDocument[] = data.map((d) => ({
          id: d.document_id,
          filename: d.filename,
          file_path: d.file_path,
          status: d.status,
          document_type: d.document_type || "pdf",
          totalChunks: d.total_chunks,
          errorMessage: d.error_message,
          is_active: d.is_active,
        }));
        setDocuments(formatted);
        
        formatted.forEach((doc) => {
          if (doc.status === "PENDING" || doc.status === "PROCESSING") {
            startPolling(doc.id, doc.filename);
          }
        });
      } catch (err: any) {
        console.error("Error al inicializar documentos:", err);
        setError("Error al cargar la lista de documentos del servidor.");
      }
    }
    loadDocs();

    return () => {
      Object.values(activePollsRef.current).forEach((interval) => clearInterval(interval));
    };
  }, []);

  const startPolling = (docId: string, filename: string) => {
    if (activePollsRef.current[docId]) {
      clearInterval(activePollsRef.current[docId]);
    }

    const interval = setInterval(async () => {
      try {
        const data = await getDocumentStatus(docId);
        
        setDocuments((prev) =>
          prev.map((doc) =>
            doc.id === docId
              ? {
                  ...doc,
                  status: data.status,
                  totalChunks: data.total_chunks,
                  errorMessage: data.error_message,
                  is_active: data.is_active,
                }
              : doc
          )
        );

        if (data.status === "COMPLETED" || data.status === "FAILED") {
          clearInterval(interval);
          delete activePollsRef.current[docId];
        }
      } catch (err) {
        console.error("Error polling document:", err);
      }
    }, 1500);

    activePollsRef.current[docId] = interval;
  };

  const handleDelete = async (docId: string, e: React.MouseEvent) => {
    e.stopPropagation(); 
    
    if (!confirm("¿Estás seguro de que deseas eliminar este documento y todas sus citas asociadas?")) {
      return;
    }

    try {
      if (activePollsRef.current[docId]) {
        clearInterval(activePollsRef.current[docId]);
        delete activePollsRef.current[docId];
      }

      await deleteDocument(docId);
      
      const nextDocs = documents.filter((doc) => doc.id !== docId);
      setDocuments(nextDocs);
    } catch (err: any) {
      setError(err.message || "Error al eliminar documento.");
    }
  };

  const handleToggleActive = async (docId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await toggleDocument(docId);
      
      const nextDocs = documents.map((doc) =>
        doc.id === docId
          ? {
              ...doc,
              is_active: res.is_active,
            }
          : doc
      );
      setDocuments(nextDocs);

      showToast(
        res.is_active
          ? "Documento activado correctamente."
          : "Documento desactivado. No se usará en futuras búsquedas.",
        "success"
      );
    } catch (err: any) {
      setError(err.message || "Error al cambiar el estado del documento.");
    }
  };

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Solo se aceptan archivos PDF.");
      return;
    }

    setUploading(true);
    setError(null);

    const tempId = "temp-" + Date.now();
    const tempDoc: TrackedDocument = {
      id: tempId,
      filename: file.name,
      status: "UPLOADING",
      document_type: "pdf",
      totalChunks: null,
      errorMessage: null,
      is_active: true,
    };
    setDocuments((prev) => [tempDoc, ...prev]);

    try {
      const res = await uploadDocument(file);
      
      setDocuments((prev) => 
        prev.map(d => d.id === tempId ? {
          ...d,
          id: res.document_id,
          status: "PENDING",
          is_active: true,
        } : d)
      );
      
      startPolling(res.document_id, file.name);
    } catch (err: any) {
      setDocuments((prev) => prev.filter(d => d.id !== tempId));
      setError(err.message || "Error al subir documento.");
    } finally {
      setUploading(false);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUpload(e.dataTransfer.files[0]);
    }
  };

  return (
    <aside 
      style={{ width: `${width}px` }} 
      className="bg-zinc-950 border-r border-zinc-800 flex flex-col h-full relative"
    >
      {toast && (
        <div className={`absolute bottom-4 left-4 right-4 p-3 rounded-xl text-xs font-medium border shadow-xl z-50 transition-all ${
          toast.type === "success" 
            ? "bg-green-950/90 border-green-900/50 text-green-400" 
            : "bg-red-950/90 border-red-900/50 text-red-400"
        }`}>
          {toast.message}
        </div>
      )}

      <div className="p-6 border-b border-zinc-800 flex items-center justify-between">
        <h2 className="text-xl font-bold text-zinc-100 flex items-center gap-2 tracking-tight">
          <span className="w-3 h-3 rounded-full bg-blue-500 animate-pulse"></span>
          AEGIS
        </h2>
        <span className="text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded font-mono">v0.1.0</span>
      </div>

      <div className="p-6 border-b border-zinc-800">
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border border-dashed rounded-xl p-5 text-center cursor-pointer transition-all duration-300 flex flex-col items-center justify-center gap-3 ${
            dragActive
              ? "border-blue-500 bg-blue-950/20"
              : "border-zinc-800 hover:border-zinc-700 bg-zinc-900/30 hover:bg-zinc-900/50"
          }`}
        >
          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept=".pdf"
            onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          />
          {uploading ? (
            <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
          ) : (
            <Upload className="h-8 w-8 text-zinc-500 transition-transform group-hover:-translate-y-1" />
          )}
          <div>
            <p className="text-sm font-semibold text-zinc-300">Sube tu PDF</p>
            <p className="text-xs text-zinc-500 mt-1">Arrastra y suelta aquí</p>
          </div>
        </div>
        {error && (
          <p className="text-xs text-red-500 mt-3 flex items-center gap-1.5 bg-red-950/20 border border-red-900/50 p-2 rounded-lg">
            <AlertCircle className="h-3.5 w-3.5" />
            {error}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-widest">
            Documentos Activos
          </h3>
          <span className="text-[10px] text-zinc-500 font-mono">
            {documents.filter(d => (d.document_type || "pdf") === "pdf" && d.status === "COMPLETED").length} manuales
          </span>
        </div>

        <div className="relative">
          <input
            type="text"
            placeholder="Buscar PDF por nombre..."
            value={pdfSearchTerm}
            onChange={(e) => setPdfSearchTerm(e.target.value)}
            className="w-full bg-zinc-900/50 hover:bg-zinc-900/80 focus:bg-zinc-900/90 border border-zinc-800 text-zinc-200 text-sm rounded-xl pl-10 pr-4 py-3 outline-none focus:border-blue-500/80 transition-all placeholder-zinc-500"
          />
          <Search className="absolute left-3.5 top-3.5 h-4 w-4 text-zinc-500" />
        </div>
        
        {(() => {
          const pdfDocs = documents.filter(d => (d.document_type || "pdf") === "pdf");
          const filteredDocs = pdfDocs.filter((doc) =>
            doc.filename.toLowerCase().includes(pdfSearchTerm.toLowerCase())
          );

          return (
            <div className="space-y-2">
              {filteredDocs.length === 0 ? (
                <p className="text-center text-xs text-zinc-600 py-6">
                  No hay manuales PDF indexados.
                </p>
              ) : (
                filteredDocs.map((doc) => {
                  return (
                    <div
                      key={doc.id}
                      onClick={() => doc.status === "COMPLETED" && doc.is_active && onOpenDocument(doc.id, doc.filename, "pdf")}
                      className={`p-4 rounded-xl border transition-all duration-300 relative group ${
                        doc.status === "COMPLETED" && doc.is_active 
                          ? "cursor-pointer border-zinc-900 hover:border-blue-500/50 hover:bg-blue-950/10 hover:shadow-lg hover:shadow-blue-950/10" 
                          : doc.status === "COMPLETED" 
                            ? "cursor-pointer opacity-70 border-zinc-900 hover:border-zinc-800 bg-zinc-900/20" 
                            : "opacity-60 cursor-not-allowed border-zinc-900 bg-zinc-900/10"
                      }`}
                    >
                      {doc.status === "COMPLETED" && (
                        <button
                          onClick={(e) => handleToggleActive(doc.id, e)}
                          className={`absolute top-4 right-10 text-zinc-500 hover:text-blue-400 transition-all duration-200 z-10 cursor-pointer ${
                            !doc.is_active ? "opacity-100 text-amber-500" : "opacity-0 group-hover:opacity-100"
                          }`}
                          title={doc.is_active ? "Desactivar documento (no se usará en chat)" : "Activar documento (se usará en chat)"}
                        >
                          {doc.is_active ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                        </button>
                      )}

                      <button
                        onClick={(e) => handleDelete(doc.id, e)}
                        className="absolute top-4 right-4 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-10 cursor-pointer"
                        title="Eliminar documento"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>

                      <div className="flex items-start gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <FileText className="h-4 w-4 shrink-0 text-zinc-500" />
                            <p className={`text-sm font-medium truncate pr-16 ${
                              !doc.is_active ? "text-zinc-500 line-through italic" : "text-zinc-200"
                            }`}>{doc.filename}</p>
                          </div>
                          
                          <div className="flex items-center gap-1.5 mt-1.5 pl-5.5">
                            {doc.status === "COMPLETED" && (
                              <>
                                <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                                <span className="text-xs text-zinc-500">{doc.totalChunks} chunks {!doc.is_active && "(Inactivo)"}</span>
                              </>
                            )}
                            {doc.status === "FAILED" && (
                              <div className="mt-1">
                                <div className="flex items-center gap-1.5">
                                  <AlertCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                                  <span className="text-xs font-bold text-red-500">Error</span>
                                </div>
                              </div>
                            )}
                            {(doc.status === "PENDING" || doc.status === "PROCESSING" || doc.status === "UPLOADING") && (
                              <div className="flex items-center gap-1.5">
                                <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />
                                <span className="text-xs text-blue-400">Procesando...</span>
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          );
        })()}

        <div className="pt-4 border-t border-zinc-900 space-y-4">
          <div className="flex flex-col gap-3">
            {(() => {
              const completedVideos = documents.filter(d => d.document_type === "youtube" && d.status === "COMPLETED");

              return (
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-zinc-400 uppercase tracking-widest flex items-center gap-1.5">
                    <Video className="h-4 w-4 text-red-500 shrink-0" />
                    Videotutoriales
                  </h3>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-zinc-500 font-mono">
                      {completedVideos.length} vídeos
                    </span>
                    <button
                      onClick={handleSyncYoutube}
                      disabled={syncingYt}
                      className="p-1.5 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 hover:text-zinc-200 text-zinc-400 cursor-pointer disabled:opacity-40 transition-all flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider"
                      title="Sincronizar videotutoriales de YouTube"
                    >
                      {syncingYt ? (
                        <Loader2 className="h-3.5 w-3.5 text-red-500 animate-spin" />
                      ) : (
                        <RotateCw className="h-3.5 w-3.5 text-zinc-400" />
                      )}
                      <span>Sincronizar</span>
                    </button>
                  </div>
                </div>
              );
            })()}
            
            <input
              type="text"
              value={channelUrl}
              onChange={(e) => handleChannelUrlChange(e.target.value)}
              placeholder="Enlace o ID del canal de YouTube..."
              className="w-full bg-zinc-900/50 hover:bg-zinc-900/80 focus:bg-zinc-900/90 border border-zinc-800 text-zinc-200 text-sm rounded-xl px-4 py-3 outline-none focus:border-red-500/80 transition-all placeholder-zinc-600"
            />
          </div>

          <div className="relative">
            <input
              type="text"
              placeholder="Buscar vídeo por nombre..."
              value={ytSearchTerm}
              onChange={(e) => setYtSearchTerm(e.target.value)}
              className="w-full bg-zinc-900/50 hover:bg-zinc-900/80 focus:bg-zinc-900/90 border border-zinc-800 text-zinc-200 text-sm rounded-xl pl-10 pr-4 py-3 outline-none focus:border-red-500/80 transition-all placeholder-zinc-500"
            />
            <Search className="absolute left-3.5 top-3.5 h-4 w-4 text-zinc-500" />
          </div>

          {(() => {
            const ytDocs = documents.filter(d => d.document_type === "youtube");
            const filteredYt = ytDocs.filter(d => d.filename.toLowerCase().includes(ytSearchTerm.toLowerCase()));

            return (
              <div className="space-y-2">
                {filteredYt.length === 0 ? (
                  <div className="text-center py-6 border border-zinc-900 rounded-xl bg-zinc-950/10">
                    <p className="text-xs text-zinc-600">No hay vídeos indexados. Haz clic en "Sincronizar" para buscarlos.</p>
                  </div>
                ) : (
                  filteredYt.map((doc) => {
                    return (
                      <div
                        key={doc.id}
                        onClick={() => doc.status === "COMPLETED" && doc.is_active && onOpenDocument(doc.id, doc.filename, "youtube", doc.file_path)}
                        className={`p-4 rounded-xl border transition-all duration-300 relative group ${
                          doc.status === "COMPLETED" && doc.is_active 
                            ? "cursor-pointer border-zinc-900 hover:border-red-500/50 hover:bg-red-950/10 hover:shadow-lg hover:shadow-red-950/10" 
                            : doc.status === "COMPLETED" 
                              ? "cursor-pointer opacity-70 border-zinc-900 hover:border-zinc-800 bg-zinc-900/20" 
                              : "opacity-60 cursor-not-allowed border-zinc-900 bg-zinc-900/10"
                        }`}
                      >
                        {doc.status === "COMPLETED" && (
                          <button
                            onClick={(e) => handleToggleActive(doc.id, e)}
                            className={`absolute top-4 right-10 text-zinc-500 hover:text-red-400 transition-all duration-200 z-10 cursor-pointer ${
                              !doc.is_active ? "opacity-100 text-amber-500" : "opacity-0 group-hover:opacity-100"
                            }`}
                            title={doc.is_active ? "Desactivar videotutorial (no se usará en chat)" : "Activar videotutorial (se usará en chat)"}
                          >
                            {doc.is_active ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                          </button>
                        )}

                        <button
                          onClick={(e) => handleDelete(doc.id, e)}
                          className="absolute top-4 right-4 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-10 cursor-pointer"
                          title="Eliminar videotutorial"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>

                        <div className="flex items-start gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5">
                              <Play className="h-4 w-4 shrink-0 text-zinc-500" />
                              <p className={`text-sm font-semibold truncate pr-16 ${
                                !doc.is_active ? "text-zinc-500 line-through italic" : "text-zinc-200"
                              }`}>{doc.filename}</p>
                            </div>
                            
                            <div className="flex items-center gap-1.5 mt-1.5 pl-5.5">
                              {doc.status === "COMPLETED" && (
                                <>
                                  <CheckCircle2 className="h-3.5 w-3.5 text-green-500 animate-pulse" />
                                  <span className="text-xs text-zinc-500 font-medium">{doc.totalChunks} chunks {!doc.is_active && "(Inactivo)"}</span>
                                </>
                              )}
                              {doc.status === "FAILED" && (
                                <span className="text-[10px] text-red-500 font-bold">Error en procesado</span>
                              )}
                              {(doc.status === "PENDING" || doc.status === "PROCESSING" || doc.status === "UPLOADING") && (
                                <div className="flex items-center gap-1.5">
                                  <Loader2 className="h-3 w-3 text-red-400 animate-spin" />
                                  <span className="text-[10px] text-red-400">Indexando...</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            );
          })()}
        </div>

      </div>

      {/* Barra de arrastre para redimensionar (resizer handle) */}
      <div
        onMouseDown={startResizing}
        className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-zinc-700/80 active:bg-blue-500 transition-colors z-30"
      />
    </aside>
  );
}
