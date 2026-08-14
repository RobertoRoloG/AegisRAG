"use client";

import React, { useState } from "react";
import dynamic from "next/dynamic";
import DocumentSidebar from "../components/DocumentSidebar";
import ChatInterface from "../components/ChatInterface";

const PdfViewer = dynamic(() => import("../components/PdfViewer"), {
  ssr: false,
});

export default function Home() {
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [selectedFilenames, setSelectedFilenames] = useState<string[]>([]);
  const [viewerPdf, setViewerPdf] = useState<{
    docId: string;
    filename: string;
    pageNumber: number;
    snippet?: string;
  } | null>(null);
  const [highlightEnabled, setHighlightEnabled] = useState(true);

  const handleSelectionChange = (docIds: string[], filenames: string[]) => {
    setSelectedDocIds(docIds);
    setSelectedFilenames(filenames);
    
    // Si ya no quedan documentos seleccionados en la lista, cerramos el visor
    if (docIds.length === 0) {
      setViewerPdf(null);
    } else if (viewerPdf && !docIds.includes(viewerPdf.docId)) {
      // Si el documento que estábamos visualizando se deseleccionó, abrimos la página 1 del primer seleccionado
      setViewerPdf({ docId: docIds[0], filename: filenames[0], pageNumber: 1 });
    }
  };

  const handleOpenPdf = (docId: string, filename: string, pageNumber: number, snippet?: string) => {
    setViewerPdf({ docId, filename, pageNumber, snippet });
  };

  const handleToggleHighlight = () => {
    setHighlightEnabled((prev) => !prev);
  };

  return (
    <div className="flex h-screen w-screen bg-zinc-950 text-zinc-100 overflow-hidden font-sans antialiased">
      {/* Fondo decorativo con gradiente suave */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-950/10 via-zinc-950 to-zinc-950 pointer-events-none z-0"></div>

      <div className="flex h-full w-full relative z-10">
        {/* Barra Lateral Izquierda (Documentos y Carga) */}
        <DocumentSidebar
          onSelectionChange={handleSelectionChange}
          selectedDocIds={selectedDocIds}
        />

        {/* Ventana de Chat Conversacional RAG */}
        <ChatInterface
          selectedDocIds={selectedDocIds}
          selectedFilenames={selectedFilenames}
          onOpenPdf={handleOpenPdf}
          viewerPdf={viewerPdf}
          highlightEnabled={highlightEnabled}
          onToggleHighlight={handleToggleHighlight}
        />

        {/* Panel Visor de PDF Interactivo Lateral Derecho */}
        {viewerPdf && (
          <PdfViewer
            docId={viewerPdf.docId}
            filename={viewerPdf.filename}
            pageNumber={viewerPdf.pageNumber}
            snippet={viewerPdf.snippet}
            highlightEnabled={highlightEnabled}
            onToggleHighlight={handleToggleHighlight}
            onClose={() => setViewerPdf(null)}
          />
        )}
      </div>
    </div>
  );
}
