"use client";

import React from "react";
import { X, Maximize2, Video } from "lucide-react";

interface YoutubeViewerProps {
  videoId: string;
  seconds: number;
  title: string;
  onClose: () => void;
}

export default function YoutubeViewer({ videoId, seconds, title, onClose }: YoutubeViewerProps) {
  const embedUrl = `https://www.youtube.com/embed/${videoId}?start=${seconds}&autoplay=1`;
  const watchUrl = `https://www.youtube.com/watch?v=${videoId}&t=${seconds}s`;

  return (
    <div className="w-[680px] border-l border-zinc-800 bg-zinc-950 flex flex-col h-full animate-in slide-in-from-right duration-300 shrink-0">
      {/* Header del Visor */}
      <div className="h-16 border-b border-zinc-800/80 px-6 flex items-center justify-between bg-zinc-950/40 shrink-0">
        <div className="min-w-0 pr-4">
          <h3 className="text-sm font-semibold text-zinc-200 truncate flex items-center gap-2">
            <Video className="h-4 w-4 text-red-500 shrink-0" />
            {title}
          </h3>
          <p className="text-[10px] text-zinc-500 font-mono mt-0.5">
            Videotutorial · Reproduciendo en segundo {seconds}
          </p>
        </div>

        {/* Acciones de Encabezado */}
        <div className="flex items-center gap-2">
          <a
            href={watchUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
            title="Abrir en YouTube en pestaña completa"
          >
            <Maximize2 className="h-4 w-4" />
          </a>

          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-zinc-900 border border-zinc-850 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
            title="Cerrar visor"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Reproductor de YouTube */}
      <div className="flex-1 bg-zinc-950 p-4 flex items-center justify-center">
        <div className="w-full h-full rounded-xl overflow-hidden border border-zinc-800 shadow-2xl bg-black">
          <iframe
            src={embedUrl}
            className="w-full h-full"
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          ></iframe>
        </div>
      </div>
    </div>
  );
}
