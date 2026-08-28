"use client";

import React, { useState } from "react";
import dynamic from "next/dynamic";
import DocumentSidebar, { TrackedDocument } from "../components/DocumentSidebar";
import ChatInterface from "../components/ChatInterface";

const PdfViewer = dynamic(() => import("../components/PdfViewer"), {
  ssr: false,
});

export default function Home() {
  const [viewerPdf, setViewerPdf] = useState<{
    docId: string;
    filename: string;
    pageNumber: number;
    snippet?: string;
  } | null>(null);
  const [highlightEnabled, setHighlightEnabled] = useState(true);

  const handleOpenPdf = (docId: string, filename: string, pageNumber: number, snippet?: string, type: "pdf" | "youtube" = "pdf", videoId?: string) => {
    if (type === "youtube" || videoId) {
      let ytUrl = "";
      if (videoId && videoId.includes("youtube.com")) {
        ytUrl = videoId;
      } else {
        const vId = videoId || docId;
        ytUrl = `https://www.youtube.com/watch?v=${vId}&t=${pageNumber}s`;
      }
      window.open(ytUrl, "_blank");
      return;
    }

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
          onOpenDocument={(docId, filename, type, filePath) => handleOpenPdf(docId, filename, 1, undefined, type, filePath)}
        />

        {/* Ventana de Chat Conversacional RAG */}
        <ChatInterface
          onOpenPdf={handleOpenPdf}
          viewerPdf={viewerPdf}
          highlightEnabled={highlightEnabled}
          onToggleHighlight={handleToggleHighlight}
        />

        {/* Panel Visor Interactivo Lateral Derecho (PDF) */}
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

