"use client";

import React, { useState, useRef, useEffect } from "react";
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, Trash2, Search } from "lucide-react";
import { uploadDocument, getDocumentStatus, listDocuments, deleteDocument, DocumentStatusResponse } from "../lib/api";

interface DocumentSidebarProps {
  onSelectionChange: (docIds: string[], filenames: string[]) => void;
  selectedDocIds: string[];
}

interface TrackedDocument {
  id: string;
  filename: string;
  status: string;
  totalChunks: number | null;
  errorMessage: string | null;
}

export default function DocumentSidebar({ onSelectionChange, selectedDocIds }: DocumentSidebarProps) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [documents, setDocuments] = useState<TrackedDocument[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activePollsRef = useRef<{ [key: string]: NodeJS.Timeout }>({});

  useEffect(() => {
    async function loadDocs() {
      try {
        const data = await listDocuments();
        const formatted = data.map((d) => ({
          id: d.document_id,
          filename: d.filename,
          status: d.status,
          totalChunks: d.total_chunks,
          errorMessage: d.error_message,
        }));
        setDocuments(formatted);

        // Auto-seleccionar todos los documentos listos si no había una selección previa activa
        if (selectedDocIds.length === 0) {
          const completedDocs = formatted.filter((d) => d.status === "COMPLETED");
          if (completedDocs.length > 0) {
            onSelectionChange(
              completedDocs.map((d) => d.id),
              completedDocs.map((d) => d.filename)
            );
          }
        }
        
        // Iniciar polling para documentos pendientes o procesándose
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

    // Limpiar todos los intervalos de polling al desmontar el componente
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
      
      // Actualizar listado local
      const nextDocs = documents.filter((doc) => doc.id !== docId);
      setDocuments(nextDocs);
      
      // Si el documento eliminado estaba seleccionado, quitarlo de la selección
      if (selectedDocIds.includes(docId)) {
        const nextDocIds = selectedDocIds.filter((id) => id !== docId);
        const nextFilenames = nextDocs
          .filter((d) => nextDocIds.includes(d.id))
          .map((d) => d.filename);
        onSelectionChange(nextDocIds, nextFilenames);
      }
    } catch (err: any) {
      setError(err.message || "Error al eliminar documento.");
    }
  };

  const handleToggleDocument = (docId: string, filename: string) => {
    let nextDocIds: string[];
    let nextFilenames: string[];

    if (selectedDocIds.includes(docId)) {
      nextDocIds = selectedDocIds.filter((id) => id !== docId);
    } else {
      nextDocIds = [...selectedDocIds, docId];
    }

    nextFilenames = documents
      .filter((d) => nextDocIds.includes(d.id))
      .map((d) => d.filename);

    onSelectionChange(nextDocIds, nextFilenames);
  };


  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Solo se aceptan archivos PDF.");
      return;
    }

    setUploading(true);
    setError(null);

    // Añadir documento temporal a la lista para feedback visual instantáneo
    const tempId = "temp-" + Date.now();
    const tempDoc: TrackedDocument = {
      id: tempId,
      filename: file.name,
      status: "UPLOADING",
      totalChunks: null,
      errorMessage: null,
    };
    setDocuments((prev) => [tempDoc, ...prev]);

    try {
      const res = await uploadDocument(file);
      
      // Actualizar el documento temporal con el ID real
      setDocuments((prev) => 
        prev.map(d => d.id === tempId ? {
          ...d,
          id: res.document_id,
          status: "PENDING",
        } : d)
      );
      
      // Auto-seleccionar agregando el nuevo documento
      const nextDocIds = [...selectedDocIds, res.document_id];
      const nextFilenames = [
        ...documents.filter((d) => selectedDocIds.includes(d.id)).map((d) => d.filename),
        file.name
      ];
      onSelectionChange(nextDocIds, nextFilenames);
      
      startPolling(res.document_id, file.name);
    } catch (err: any) {
      // Eliminar el documento temporal si falla la subida
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
    <aside className="w-80 bg-zinc-950 border-r border-zinc-800 flex flex-col h-full">
      {/* Header */}
      <div className="p-6 border-b border-zinc-800 flex items-center justify-between">
        <h2 className="text-xl font-bold text-zinc-100 flex items-center gap-2 tracking-tight">
          <span className="w-3 h-3 rounded-full bg-indigo-500 animate-pulse"></span>
          AegisRAG
        </h2>
        <span className="text-xs bg-zinc-800 text-zinc-400 px-2 py-0.5 rounded font-mono">v0.1.0</span>
      </div>

      {/* Zona de Subida */}
      <div className="p-6 border-b border-zinc-800">
        <div
          onDragEnter={handleDrag}
          onDragOver={handleDrag}
          onDragLeave={handleDrag}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border border-dashed rounded-xl p-5 text-center cursor-pointer transition-all duration-300 flex flex-col items-center justify-center gap-3 ${
            dragActive
              ? "border-indigo-500 bg-indigo-950/20"
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
            <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
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

      {/* Listado de Documentos */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-xs font-bold text-zinc-500 uppercase tracking-widest">Documentos Activos</h3>
        </div>

        {/* Input buscador interactivo */}
        <div className="relative">
          <input
            type="text"
            placeholder="Buscar PDF por nombre..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-zinc-900/50 hover:bg-zinc-900/80 focus:bg-zinc-900/90 border border-zinc-800 text-zinc-200 text-xs rounded-xl pl-9 pr-4 py-2.5 outline-none focus:border-indigo-500/80 transition-all placeholder-zinc-500"
          />
          <Search className="absolute left-3 top-3 h-3.5 w-3.5 text-zinc-500" />
        </div>

        {/* Botón dinámico para limpiar la selección */}
        {selectedDocIds.length > 0 && (
          <button
            onClick={() => onSelectionChange([], [])}
            className="w-full text-center p-2 rounded-xl text-[10px] text-indigo-400 hover:text-indigo-300 hover:bg-indigo-950/20 border border-indigo-900/30 transition-all font-semibold uppercase tracking-wider cursor-pointer"
          >
            Limpiar selección ({selectedDocIds.length} seleccionados)
          </button>
        )}
        
        {documents.length === 0 ? (
          <div className="text-center py-10">
            <p className="text-sm text-zinc-600">No hay archivos cargados aún.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {(() => {
              const filteredDocs = documents.filter((doc) =>
                doc.filename.toLowerCase().includes(searchTerm.toLowerCase())
              );

              if (filteredDocs.length === 0) {
                return (
                  <p className="text-center text-xs text-zinc-600 py-6">
                    No se encontraron documentos que coincidan con la búsqueda.
                  </p>
                );
              }

              return filteredDocs.map((doc) => {
                const isSelected = selectedDocIds.includes(doc.id);
                return (
                  <div
                    key={doc.id}
                    onClick={() => doc.status === "COMPLETED" && handleToggleDocument(doc.id, doc.filename)}
                    className={`p-3 rounded-xl border transition-all duration-300 relative group ${
                      doc.status === "COMPLETED" ? "cursor-pointer" : "opacity-60 cursor-not-allowed"
                    } ${
                      isSelected
                        ? "border-indigo-500/50 bg-indigo-950/10 shadow-lg shadow-indigo-950/10"
                        : "border-zinc-900 hover:border-zinc-800 bg-zinc-900/20 hover:bg-zinc-900/40"
                    }`}
                  >
                    {/* Botón de eliminar con papelera (visible en hover) */}
                    <button
                      onClick={(e) => handleDelete(doc.id, e)}
                      className="absolute top-3 right-3 text-zinc-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-10 cursor-pointer"
                      title="Eliminar documento"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>

                    <div className="flex items-start gap-3">
                      {/* Checkbox para indicar selección múltiple */}
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={doc.status !== "COMPLETED"}
                        onChange={(e) => {
                          e.stopPropagation();
                          if (doc.status === "COMPLETED") {
                            handleToggleDocument(doc.id, doc.filename);
                          }
                        }}
                        className="mt-1 h-3.5 w-3.5 rounded border-zinc-700 text-indigo-600 focus:ring-indigo-500 bg-zinc-900 shrink-0 cursor-pointer disabled:opacity-40"
                      />
                      
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <FileText className={`h-4 w-4 shrink-0 ${isSelected ? "text-indigo-400" : "text-zinc-500"}`} />
                          <p className="text-sm font-medium text-zinc-200 truncate pr-6">{doc.filename}</p>
                        </div>
                        
                        <div className="flex items-center gap-1.5 mt-1.5 pl-5">
                          {doc.status === "COMPLETED" && (
                            <>
                              <CheckCircle2 className="h-3 w-3 text-green-500" />
                              <span className="text-xs text-zinc-500">{doc.totalChunks} chunks</span>
                            </>
                          )}
                          {doc.status === "FAILED" && (
                            <div className="mt-1">
                              <div className="flex items-center gap-1.5">
                                <AlertCircle className="h-3 w-3 text-red-500 shrink-0" />
                                <span className="text-xs font-bold text-red-500">Error en procesamiento</span>
                              </div>
                              {doc.errorMessage && (
                                <p className="text-[10px] text-red-400/90 mt-1 leading-relaxed bg-red-950/10 border border-red-900/30 p-1.5 rounded-lg break-words whitespace-pre-wrap">
                                  {doc.errorMessage}
                                </p>
                              )}
                            </div>
                          )}
                          {(doc.status === "PENDING" || doc.status === "PROCESSING" || doc.status === "UPLOADING") && (
                            <div className="flex items-center gap-1.5">
                              <Loader2 className="h-3 w-3 text-indigo-400 animate-spin" />
                              <span className="text-xs text-indigo-400">
                                {doc.status === "UPLOADING" ? "Subiendo..." : "Procesando..."}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              });
            })()}
          </div>
        )}
      </div>
    </aside>
  );
}
