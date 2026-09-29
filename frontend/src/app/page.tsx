"use client";

import React, { useState } from "react";
import dynamic from "next/dynamic";
import DocumentSidebar from "../components/DocumentSidebar";
import ChatInterface from "../components/ChatInterface";
import YoutubeViewer from "../components/YoutubeViewer";

const PdfViewer = dynamic(() => import("../components/PdfViewer"), {
  ssr: false,
});

export interface ViewerMediaState {
  type: "pdf" | "youtube";
  docId: string;
  filename: string;
  pageNumber: number;
  snippet?: string;
  videoId?: string;
}

export default function Home() {
  const [viewerMedia, setViewerMedia] = useState<ViewerMediaState | null>(null);
  const [highlightEnabled, setHighlightEnabled] = useState(true);

  const handleOpenMedia = (
    docId: string,
    filename: string,
    pageNumber: number,
    snippet?: string,
    type: "pdf" | "youtube" = "pdf",
    videoId?: string
  ) => {
    let extractedVideoId = videoId || "";
    if (type === "youtube" || videoId) {
      if (videoId && videoId.includes("watch?v=")) {
        extractedVideoId = videoId.split("v=")[1]?.split("&")[0] || videoId;
      } else if (videoId && videoId.includes("youtu.be/")) {
        extractedVideoId = videoId.split("youtu.be/")[1]?.split("?")[0] || videoId;
      } else if (!extractedVideoId) {
        extractedVideoId = docId;
      }
      setViewerMedia({
        type: "youtube",
        docId,
        filename,
        pageNumber,
        snippet,
        videoId: extractedVideoId,
      });
      return;
    }

    setViewerMedia({
      type: "pdf",
      docId,
      filename,
      pageNumber,
      snippet,
    });
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
          onOpenDocument={(docId, filename, type, filePath) =>
            handleOpenMedia(docId, filename, 1, undefined, type, filePath)
          }
        />

        {/* Ventana de Chat Conversacional RAG */}
        <ChatInterface
          onOpenPdf={handleOpenMedia}
          viewerPdf={
            viewerMedia && viewerMedia.type === "pdf"
              ? {
                  docId: viewerMedia.docId,
                  filename: viewerMedia.filename,
                  pageNumber: viewerMedia.pageNumber,
                  snippet: viewerMedia.snippet,
                }
              : null
          }
          highlightEnabled={highlightEnabled}
          onToggleHighlight={handleToggleHighlight}
        />

        {/* Panel Visor Lateral Derecho: PDF con resaltado semántico */}
        {viewerMedia && viewerMedia.type === "pdf" && (
          <PdfViewer
            docId={viewerMedia.docId}
            filename={viewerMedia.filename}
            pageNumber={viewerMedia.pageNumber}
            snippet={viewerMedia.snippet}
            highlightEnabled={highlightEnabled}
            onToggleHighlight={handleToggleHighlight}
            onClose={() => setViewerMedia(null)}
          />
        )}

        {/* Panel Visor Lateral Derecho: YouTube Embebido con Timestamp exacto */}
        {viewerMedia && viewerMedia.type === "youtube" && (
          <YoutubeViewer
            videoId={viewerMedia.videoId || viewerMedia.docId}
            seconds={viewerMedia.pageNumber}
            title={viewerMedia.filename}
            onClose={() => setViewerMedia(null)}
          />
        )}
      </div>
    </div>
  );
}
