"use client";

import { X, BookOpen } from "lucide-react";
import type { Citation } from "@/lib/api";

interface CitationPanelProps {
  citation: Citation;
  index: number;
  onClose: () => void;
}

/** Source panel for one citation: document name, page, section,
 * chunk id, score, and snippet. Rendered as a dialog so keyboard
 * and screen-reader users get a labelled, dismissible surface
 * (Escape closes via the onClose button; see ChatPanel). */
export default function CitationPanel({ citation, index, onClose }: CitationPanelProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Source ${index + 1}: ${citation.document_name}`}
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="card w-full max-w-lg p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2 min-w-0">
            <BookOpen className="w-5 h-5 text-brand-400 flex-shrink-0" />
            <h2 className="font-semibold text-slate-100 truncate">
              Source {index + 1}: {citation.document_name}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close source panel"
            className="btn-ghost !p-2 flex-shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="text-slate-500 w-20 flex-shrink-0">Chunk</dt>
            <dd className="text-slate-200">
              {citation.chunk_index}
              {citation.chunk_id ? <span className="text-slate-500 font-mono text-xs"> · {citation.chunk_id}</span> : null}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-slate-500 w-20 flex-shrink-0">Page</dt>
            <dd className="text-slate-200">{citation.page != null ? `Page ${citation.page}` : "Not recorded"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-slate-500 w-20 flex-shrink-0">Section</dt>
            <dd className="text-slate-200">{citation.section || "Not recorded"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-slate-500 w-20 flex-shrink-0">Score</dt>
            <dd className="text-slate-200">{(citation.score * 100).toFixed(0)}% match</dd>
          </div>
        </dl>
        <p className="mt-4 text-sm text-slate-300 leading-relaxed border-t border-surface-border pt-4">
          {citation.snippet}
        </p>
      </div>
    </div>
  );
}
