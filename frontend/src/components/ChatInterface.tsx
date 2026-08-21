"use client";

import React, { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Sparkles, AlertCircle, FileText, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { queryChat, ChatQueryResponse, SourceDocument } from "../lib/api";
import LatencyDisplay from "./LatencyDisplay";

interface ChatInterfaceProps {
  selectedDocIds: string[];
  selectedFilenames: string[];
  onOpenPdf: (docId: string, filename: string, pageNumber: number, snippet?: string) => void;
  viewerPdf: { docId: string; filename: string; pageNumber: number; snippet?: string } | null;
  highlightEnabled: boolean;
  onToggleHighlight: () => void;
}

interface Message {
  id: string;
  sender: "user" | "bot";
  text: string;
  sources?: SourceDocument[];
  cragStatus?: string;
  latencyMs?: any;
}

export default function ChatInterface({
  selectedDocIds,
  selectedFilenames,
  onOpenPdf,
  viewerPdf,
  highlightEnabled,
  onToggleHighlight,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      sender: "bot",
      text: "¡Hola! Soy AegisRAG, tu asistente inteligente. Sube un documento PDF y hazme cualquier consulta para empezar.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSourcesIdx, setOpenSourcesIdx] = useState<number | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userQuery = input.trim();
    setInput("");
    setError(null);

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      sender: "user",
      text: userQuery,
    };
    setMessages((prev) => [...prev, userMsg]);

    if (selectedDocIds.length === 0) {
      const warnMsg: Message = {
        id: `bot-warn-${Date.now()}`,
        sender: "bot",
        text: "⚠️ No hay ningún documento PDF seleccionado. Por favor, marca al menos una casilla en el panel izquierdo de 'Documentos Activos' para consultar.",
      };
      setMessages((prev) => [...prev, warnMsg]);
      return;
    }

    setLoading(true);

    try {
      const res = await queryChat(userQuery, selectedDocIds);
      
      const botMsg: Message = {
        id: `bot-${Date.now()}`,
        sender: "bot",
        text: res.answer,
        sources: res.sources,
        cragStatus: res.crag_status,
        latencyMs: res.latency_ms,
      };

      setMessages((prev) => [...prev, botMsg]);
    } catch (err: any) {
      setError(err.message || "Fallo al procesar la respuesta.");
    } finally {
      setLoading(false);
    }
  };

  const parseCitations = (text: string, sources: SourceDocument[] | undefined) => {
    if (!text) return text;
    
    const citationRegex = /\[([^\]]+?\.pdf)(?:[,\s]*(?:pág|pag|página|pagina|p)\.?\s*(\d+))?\]/gi;
    const parts = [];
    let lastIndex = 0;
    let match;

    const normalizeName = (n: string) => n.toLowerCase().replace(/[\+_\s]/g, "");

    while ((match = citationRegex.exec(text)) !== null) {
      const matchIndex = match.index;
      
      if (matchIndex > lastIndex) {
        parts.push(text.substring(lastIndex, matchIndex));
      }

      const filename = match[1];
      const pageNumber = match[2] ? parseInt(match[2], 10) : 1;
      const fullCitationText = match[0];

      let matchingSource = sources?.find(
        (src) => src.filename.toLowerCase() === filename.toLowerCase()
      );

      if (!matchingSource) {
        const normCitation = normalizeName(filename);
        matchingSource = sources?.find((src) => {
          const normSrc = normalizeName(src.filename);
          return normSrc === normCitation || normSrc.includes(normCitation) || normCitation.includes(normSrc);
        });
      }

      if (!matchingSource && sources && sources.length > 0) {
        matchingSource = sources[0];
      }

      if (matchingSource) {
        const docId = matchingSource.doc_id;
        const targetFilename = matchingSource.filename;
        const snippetText = matchingSource.snippet ? matchingSource.snippet.slice(0, 50) : undefined;

        parts.push(
          <button
            key={`cite-${matchIndex}`}
            onClick={() => onOpenPdf(docId, targetFilename, pageNumber, snippetText)}
            className="px-2 py-0.5 mx-1 rounded-md bg-indigo-600/90 hover:bg-indigo-500 active:bg-indigo-700 text-white font-semibold text-xs transition-all duration-150 cursor-pointer inline-flex items-center gap-1.5 focus:outline-none shadow-sm hover:shadow-indigo-500/20 border border-indigo-400/30"
            title={`Abrir página ${pageNumber} en el visor de ${targetFilename}`}
          >
            <FileText className="h-3.5 w-3.5 shrink-0 text-indigo-200" />
            <span>{fullCitationText}</span>
          </button>
        );
      } else {
        parts.push(fullCitationText);
      }

      lastIndex = citationRegex.lastIndex;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  const parseBoldText = (text: string, sources?: SourceDocument[]) => {
    const parts = text.split(/(\*\*.*?\*\*)/g);

    return parts.flatMap((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        const boldInner = part.slice(2, -2);
        const parsedInner = parseCitations(boldInner, sources);

        return [
          <strong key={index} className="font-extrabold text-zinc-50">
            {Array.isArray(parsedInner) ? parsedInner : [parsedInner]}
          </strong>,
        ];
      }

      const parsed = parseCitations(part, sources);
      return Array.isArray(parsed) ? parsed : [parsed];
    });
  };

  const renderFormattedText = (text: string, sources?: SourceDocument[]) => {
    if (!text) return null;
    
    const lines = text.split("\n");
    const formattedElements: React.ReactNode[] = [];
    
    let keyCounter = 0;
    let listItems: React.ReactNode[] = [];

    const flushList = () => {
      if (listItems.length > 0) {
        formattedElements.push(
          <ul
            key={`list-${keyCounter++}`}
            className="list-disc pl-5 my-2 space-y-1.5 text-zinc-300"
          >
            {listItems}
          </ul>
        );
        listItems = [];
      }
    };

    lines.forEach((line) => {
      const trimmedLine = line.trim();
      
      const isNumbered = /^\d+\.\s(.*)/.exec(trimmedLine);
      const isBullet = /^[-*]\s(.*)/.exec(trimmedLine);

      if (isNumbered) {
        flushList();
        const content = isNumbered[1];

        formattedElements.push(
          <div
            key={`num-${keyCounter++}`}
            className="flex gap-2 pl-2 my-2 leading-relaxed text-zinc-300"
          >
            <span className="font-bold text-indigo-400 shrink-0">
              {trimmedLine.split(".")[0]}.
            </span>
            <span className="flex-1">
              {parseBoldText(content, sources)}
            </span>
          </div>
        );
      } else if (isBullet) {
        const content = isBullet[1];

        listItems.push(
          <li key={`bullet-item-${keyCounter++}`} className="leading-relaxed">
            {parseBoldText(content, sources)}
          </li>
        );
      } else {
        flushList();

        if (trimmedLine) {
          formattedElements.push(
            <p
              key={`p-${keyCounter++}`}
              className="my-2 leading-relaxed text-zinc-300"
            >
              {parseBoldText(trimmedLine, sources)}
            </p>
          );
        } else {
          formattedElements.push(
            <div key={`spacer-${keyCounter++}`} className="h-2" />
          );
        }
      }
    });

    flushList();

    return <div className="space-y-1">{formattedElements}</div>;
  };

  return (
    <section className="flex-1 flex flex-col h-full bg-zinc-900/10">

      {/* Header del Chat */}
      <div className="h-16 border-b border-zinc-800/80 px-8 flex items-center justify-between bg-zinc-950/20">
        <div>
          <h1 className="text-sm font-semibold text-zinc-100 flex items-center gap-1.5">
            <Sparkles className="h-4 w-4 text-indigo-400" />
            Asistente AegisRAG
          </h1>

          <p className="text-xs text-zinc-500 mt-0.5">
            {selectedFilenames.length === 0
              ? "⚠️ Ningún documento seleccionado"
              : selectedFilenames.length === 1
              ? `Buscando en: ${selectedFilenames[0]}`
              : `Buscando en: ${selectedFilenames.length} documentos seleccionados`}
          </p>
        </div>

        <div className="flex items-center gap-3">

          {/* Botón Global para Activar / Desactivar Resaltado de Citas */}
          <button
            onClick={onToggleHighlight}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-all duration-150 flex items-center gap-1.5 font-semibold cursor-pointer ${
              highlightEnabled
                ? "bg-amber-500/20 border-amber-500/50 text-amber-300 hover:bg-amber-500/30 shadow-sm shadow-amber-500/10"
                : "bg-zinc-900 border-zinc-800 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            }`}
            title={
              highlightEnabled
                ? "Desactivar resaltado automático de citas en el PDF"
                : "Activar resaltado automático de citas en el PDF"
            }
          >
            <Sparkles
              className={`h-3.5 w-3.5 ${
                highlightEnabled
                  ? "text-amber-400 animate-pulse"
                  : "text-zinc-500"
              }`}
            />
            <span>
              Resaltar Citas: {highlightEnabled ? "ON" : "OFF"}
            </span>
          </button>

          {selectedDocIds.length > 0 && (
            <button
              onClick={() =>
                onOpenPdf(selectedDocIds[0], selectedFilenames[0], 1)
              }
              className="flex items-center gap-1.5 text-xs bg-zinc-900 border border-zinc-800/80 hover:bg-zinc-800 text-zinc-300 hover:text-zinc-100 px-3 py-1.5 rounded-lg transition-colors font-medium shadow-sm cursor-pointer"
              title="Visualizar el documento seleccionado"
            >
              <FileText className="h-3.5 w-3.5 text-indigo-400" />
              {selectedDocIds.length === 1
                ? "Ver documento"
                : "Ver primer documento"}
            </button>
          )}
        </div>
      </div>

      {/* Historial de Mensajes */}
      <div className="flex-1 overflow-y-auto p-8 space-y-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {messages.map((msg, index) => {
            const isBot = msg.sender === "bot";

            return (
              <div
                key={msg.id}
                className={`flex gap-4 ${
                  isBot ? "justify-start" : "justify-end"
                }`}
              >

                {/* Avatar */}
                {isBot && (
                  <div className="h-8 w-8 rounded-lg bg-indigo-950/50 border border-indigo-500/20 flex items-center justify-center shrink-0">
                    <Bot className="h-4 w-4 text-indigo-400" />
                  </div>
                )}

                <div className="max-w-xl space-y-3 min-w-0">

                  {/* Burbuja de Texto */}
                  <div
                    className={`rounded-2xl px-5 py-4 text-sm leading-relaxed border ${
                      isBot
                        ? "bg-zinc-900/40 border-zinc-800/80 text-zinc-200 shadow-md shadow-zinc-950/25"
                        : "bg-indigo-600 border-indigo-500 text-white font-medium shadow-md shadow-indigo-950/25"
                    }`}
                  >
                    {isBot
                      ? renderFormattedText(msg.text, msg.sources)
                      : msg.text}
                  </div>

                  {/* Latencias */}
                  {isBot && msg.latencyMs && (
                    <LatencyDisplay
                      latencies={msg.latencyMs}
                      cragStatus={msg.cragStatus || ""}
                    />
                  )}

                  {/* Fuentes y Citas */}
                  {isBot && msg.sources && msg.sources.length > 0 && (
                    <div className="border border-zinc-800/60 rounded-xl bg-zinc-950/20 overflow-hidden text-xs">

                      <button
                        onClick={() =>
                          setOpenSourcesIdx(
                            openSourcesIdx === index ? null : index
                          )
                        }
                        className="w-full flex items-center justify-between p-3 text-zinc-400 hover:text-zinc-200 transition-colors"
                      >
                        <span className="flex items-center gap-1.5 font-medium">
                          <FileText className="h-3.5 w-3.5 text-indigo-400" />
                          Fuentes utilizadas ({msg.sources.length})
                        </span>

                        {openSourcesIdx === index ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </button>

                      {openSourcesIdx === index && (
                        <div className="border-t border-zinc-850 p-4 space-y-3 bg-zinc-950/40">

                          {msg.sources.map((src, sIdx) => (
                            <div
                              key={sIdx}
                              className="bg-zinc-900/30 border border-zinc-800/40 rounded-xl p-3"
                            >
                              <div className="flex items-center justify-between text-zinc-400 font-semibold text-[10px] mb-2">

                                <button
                                  onClick={() =>
                                    onOpenPdf(
                                      src.doc_id,
                                      src.filename,
                                      src.page_number
                                    )
                                  }
                                  className="truncate max-w-[70%] hover:text-indigo-400 hover:underline text-left cursor-pointer transition-colors"
                                  title="Ver esta página en el visor"
                                >
                                  {src.filename} (pág. {src.page_number})
                                </button>

                                <span className="text-indigo-400 font-mono">
                                  Rerank: {src.score}
                                </span>
                              </div>

                              <p className="text-[11px] text-zinc-500 leading-relaxed italic bg-zinc-950/10 p-2 rounded-lg border border-zinc-900/40">
                                "{src.snippet}"
                              </p>
                            </div>
                          ))}

                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Avatar del Usuario */}
                {!isBot && (
                  <div className="h-8 w-8 rounded-lg bg-zinc-850 border border-zinc-700 flex items-center justify-center shrink-0">
                    <User className="h-4 w-4 text-zinc-300" />
                  </div>
                )}
              </div>
            );
          })}

          {/* Loader del Bot */}
          {loading && (
            <div className="flex gap-4 justify-start">

              <div className="h-8 w-8 rounded-lg bg-indigo-950/50 border border-indigo-500/20 flex items-center justify-center shrink-0">
                <Bot className="h-4 w-4 text-indigo-400" />
              </div>

              <div className="max-w-xl space-y-3">

                <div className="rounded-2xl px-5 py-4 border bg-zinc-900/40 border-zinc-800/80 text-zinc-400 text-sm">

                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 text-indigo-400 animate-spin" />
                    <span>
                      Consultando motor CRAG y generando respuesta...
                    </span>
                  </div>

                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="max-w-xl mx-auto my-4 bg-red-950/20 border border-red-900/50 p-4 rounded-xl flex items-center gap-3 text-red-400 text-sm">
              <AlertCircle className="h-5 w-5 shrink-0" />

              <div>
                <p className="font-semibold">
                  Error al obtener respuesta
                </p>

                <p className="text-xs text-red-500/90 mt-0.5">
                  {error}
                </p>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>
      </div>

      {/* Input de Chat */}
      <div className="p-8 border-t border-zinc-800/80 bg-zinc-950/10">

        <form
          onSubmit={handleSend}
          className="max-w-3xl mx-auto relative"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading}
            placeholder={
              selectedFilenames.length === 0
                ? "Pregunta sobre la documentación indexada..."
                : selectedFilenames.length === 1
                ? `Pregunta sobre ${selectedFilenames[0]}...`
                : `Pregunta sobre los ${selectedFilenames.length} PDFs seleccionados...`
            }
            className="w-full bg-zinc-900/50 hover:bg-zinc-900/70 focus:bg-zinc-900/80 text-zinc-100 placeholder-zinc-500 text-sm rounded-2xl pl-5 pr-14 py-4 border border-zinc-800 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none transition-all duration-300 shadow-inner"
          />
          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="absolute right-3.5 top-3.5 p-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-850 disabled:text-zinc-600 text-white transition-all duration-300 shadow-md shadow-indigo-950/30"
          >
            <Send className="h-4 w-4 text-white" />
          </button>
        </form>

        <p className="text-[10px] text-zinc-600 text-center mt-3">
          Respuestas formuladas usando Corrective RAG (CRAG) con búsqueda híbrida y re-ranking local.
        </p>

      </div>
    </section>
  );
}
