"use client";

import React, { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import {
  ChevronLeft,
  ChevronRight,
  Sparkles,
  X,
  Maximize2,
  ZoomIn,
  ZoomOut,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { getDocumentFileUrl } from "../lib/api";

// Configurar el worker de PDF.js solo en entorno cliente
if (typeof window !== "undefined") {
  pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
}

interface PdfViewerProps {
  docId: string;
  filename: string;
  pageNumber: number;
  snippet?: string;
  highlightEnabled: boolean;
  onToggleHighlight: () => void;
  onClose: () => void;
}

export default function PdfViewer({
  docId,
  filename,
  pageNumber: initialPageNumber,
  snippet,
  highlightEnabled,
  onToggleHighlight,
  onClose,
}: PdfViewerProps) {
  const [pdfDoc, setPdfDoc] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [currentPage, setCurrentPage] = useState(initialPageNumber);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1.2);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const pdfUrl = getDocumentFileUrl(docId);

  // Actualizar página si cambian las props iniciales
  useEffect(() => {
    setCurrentPage(initialPageNumber);
  }, [initialPageNumber, docId]);

  // Cargar documento PDF
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    const loadingTask = pdfjs.getDocument({ url: pdfUrl });
    loadingTask.promise
      .then((pdf) => {
        if (!active) return;
        setPdfDoc(pdf);
        setNumPages(pdf.numPages);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        console.error("Error al cargar PDF con PDF.js:", err);
        setError("No se pudo cargar el archivo PDF.");
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [pdfUrl]);

  // Renderizar la página actual y la capa de texto
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    let renderTask: pdfjs.RenderTask | null = null;
    let active = true;

    pdfDoc
      .getPage(currentPage)
      .then((page) => {
        if (!active || !canvasRef.current) return;

        const viewport = page.getViewport({ scale });
        const canvas = canvasRef.current;
        const context = canvas.getContext("2d");

        if (!context) return;

        canvas.height = viewport.height;
        canvas.width = viewport.width;

        // Limpiar capa de texto anterior
        if (textLayerRef.current) {
          textLayerRef.current.innerHTML = "";
          textLayerRef.current.style.width = `${viewport.width}px`;
          textLayerRef.current.style.height = `${viewport.height}px`;
        }

        // Renderizar Canvas de la página
        renderTask = page.render({
          canvasContext: context,
          viewport,
          canvas,
        });

        return renderTask.promise.then(() =>
          page.getTextContent().then((textContent) => ({ page, viewport, textContent, context }))
        );
      })
      .then((data) => {
        if (!active || !data) return;

        const { viewport, textContent, context } = data;
        const searchTerms =
          highlightEnabled && snippet
            ? snippet
                .replace(/[^\w\s\u00C0-\u00FF]/gi, " ")
                .toLowerCase()
                .split(/\s+/)
                .filter((w) => w.length > 2)
                .slice(0, 5) // Ancla de inicio: tomar solo las primeras 4-5 palabras del inicio de la cita
            : [];

        // Dibujar resaltado fluido solo al inicio de la cita como ancla visual
        if (searchTerms.length > 0 && context) {
          interface HighlightRect {
            x: number;
            y: number;
            w: number;
            h: number;
          }

          const rawRects: HighlightRect[] = [];

          textContent.items.forEach((item: any) => {
            if (!("str" in item) || !item.str.trim() || !item.transform) return;

            const itemText = item.str.toLowerCase();
            const isMatch = searchTerms.some((term) => itemText.includes(term));

            if (isMatch) {
              const tx = item.transform[4];
              const ty = item.transform[5];
              const fontHeight =
                Math.sqrt(item.transform[2] * item.transform[2] + item.transform[3] * item.transform[3]) || 12;
              const fontWidth = item.width || item.str.length * fontHeight * 0.5;

              // Convertir coordenadas PDF a píxeles de Canvas
              const [p1x, p1y] = viewport.convertToViewportPoint(tx, ty);
              const [p2x, p2y] = viewport.convertToViewportPoint(tx + fontWidth, ty + fontHeight);

              const minX = Math.min(p1x, p2x);
              const minY = Math.min(p1y, p2y);
              const width = Math.max(Math.abs(p2x - p1x), 10);
              const height = Math.max(Math.abs(p2y - p1y), fontHeight * scale);

              rawRects.push({ x: minX, y: minY, w: width, h: height });
            }
          });

          // Agrupar y fusionar rectángulos de la misma línea (tolerancia vertical de 6px)
          const mergedLines: HighlightRect[] = [];
          rawRects.sort((a, b) => a.y - b.y || a.x - b.x);

          rawRects.forEach((rect) => {
            const existingLine = mergedLines.find((line) => Math.abs(line.y - rect.y) < 6);

            if (existingLine) {
              const newX = Math.min(existingLine.x, rect.x);
              const newMaxX = Math.max(existingLine.x + existingLine.w, rect.x + rect.w);
              existingLine.x = newX;
              existingLine.w = newMaxX - newX;
              existingLine.h = Math.max(existingLine.h, rect.h);
            } else {
              mergedLines.push({ ...rect });
            }
          });

          // Tomar únicamente la primera línea inicial (ancla de la cita)
          const anchorLines = mergedLines.slice(0, 1);

          // Dibujar franja continua del inicio de la cita
          context.save();
          context.fillStyle = "rgba(253, 224, 71, 0.5)"; // Amarillo marcador fluorescente

          anchorLines.forEach((line) => {
            const paddingX = 4;
            const paddingY = 2;
            const rx = line.x - paddingX;
            const ry = line.y - paddingY;
            const rw = line.w + paddingX * 2;
            const rh = line.h + paddingY * 2;
            const radius = Math.min(4, rh / 2);

            context.beginPath();
            if (typeof (context as any).roundRect === "function") {
              (context as any).roundRect(rx, ry, rw, rh, radius);
            } else {
              context.rect(rx, ry, rw, rh);
            }
            context.fill();
          });

          context.restore();
        }
      })
      .catch((err) => {
        if (err?.name !== "RenderingCancelledException") {
          console.error("Error al renderizar página PDF:", err);
        }
      });

    return () => {
      active = false;
      if (renderTask) {
        renderTask.cancel();
      }
    };
  }, [pdfDoc, currentPage, scale, highlightEnabled, snippet]);

  return (
    <div className="w-[680px] border-l border-zinc-800 bg-zinc-950 flex flex-col h-full animate-in slide-in-from-right duration-300 shrink-0">
      {/* Header del Visor */}
      <div className="h-16 border-b border-zinc-800/80 px-6 flex items-center justify-between bg-zinc-950/40 shrink-0">
        <div className="min-w-0 pr-4">
          <h3 className="text-sm font-semibold text-zinc-200 truncate">{filename}</h3>
          <p className="text-[10px] text-zinc-500 font-mono mt-0.5">
            Página {currentPage} de {numPages || "..."}
          </p>
        </div>

        {/* Acciones y Controles de Encabezado */}
        <div className="flex items-center gap-2">
          {/* Botón Switch para Activar / Desactivar Resaltado */}
          <button
            onClick={onToggleHighlight}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-all duration-150 flex items-center gap-1.5 font-semibold cursor-pointer ${
              highlightEnabled
                ? "bg-amber-500/20 border-amber-500/50 text-amber-300 hover:bg-amber-500/30 shadow-sm shadow-amber-500/10"
                : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            }`}
            title={highlightEnabled ? "Desactivar resaltado automático de la cita" : "Activar resaltado de la cita"}
          >
            <Sparkles className={`h-3.5 w-3.5 ${highlightEnabled ? "text-amber-400 animate-pulse" : "text-zinc-500"}`} />
            <span>Resaltar: {highlightEnabled ? "ON" : "OFF"}</span>
          </button>

          <a
            href={`${pdfUrl}#page=${currentPage}`}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
            title="Abrir PDF en pestaña completa"
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

      {/* Barra de Herramientas de Navegación y Zoom */}
      <div className="h-10 border-b border-zinc-800/50 px-6 flex items-center justify-between bg-zinc-900/30 shrink-0 text-xs text-zinc-400">
        <div className="flex items-center gap-2">
          <button
            disabled={currentPage <= 1}
            onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
            className="p-1 rounded hover:bg-zinc-800 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer"
            title="Página anterior"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="font-mono text-zinc-300">
            {currentPage} / {numPages || 1}
          </span>
          <button
            disabled={currentPage >= numPages}
            onClick={() => setCurrentPage((prev) => Math.min(numPages, prev + 1))}
            className="p-1 rounded hover:bg-zinc-800 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer"
            title="Página siguiente"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setScale((s) => Math.max(0.8, s - 0.2))}
            className="p-1 rounded hover:bg-zinc-800 cursor-pointer"
            title="Alejar"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <span className="font-mono text-zinc-300">{Math.round(scale * 100)}%</span>
          <button
            onClick={() => setScale((s) => Math.min(2.0, s + 0.2))}
            className="p-1 rounded hover:bg-zinc-800 cursor-pointer"
            title="Acercar"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Lienzo Renderizador del PDF */}
      <div className="flex-1 bg-zinc-950 overflow-auto p-4 flex justify-center relative">
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/80 z-20 gap-2">
            <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
            <p className="text-xs text-zinc-400">Cargando documento PDF...</p>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-zinc-950 z-20 gap-2 p-6 text-center">
            <AlertCircle className="h-8 w-8 text-red-500" />
            <p className="text-sm font-semibold text-zinc-200">{error}</p>
          </div>
        )}

        <div className="relative shadow-2xl rounded-lg overflow-hidden border border-zinc-800 h-fit">
          <canvas ref={canvasRef} className="block" />
          <div ref={textLayerRef} className="absolute top-0 left-0 pointer-events-none" />
        </div>
      </div>
    </div>
  );
}
