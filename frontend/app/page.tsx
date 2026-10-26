"use client";

import Link from "next/link";
import { Brain, FileText, MessageSquare, Zap, Shield, ChevronRight } from "lucide-react";

const features = [
  {
    icon: FileText,
    title: "Multi-format ingestion",
    description: "Upload PDF, DOCX, TXT, and Markdown files. Token-aware chunking preserves context across boundaries.",
  },
  {
    icon: Zap,
    title: "Agentic RAG pipeline",
    description: "LangGraph-powered flow: Planner rewrites queries, Retriever finds relevant chunks, Reasoning synthesises answers.",
  },
  {
    icon: MessageSquare,
    title: "Cited answers",
    description: "Every answer links back to the exact document chunk it came from — no hallucinations go untraced.",
  },
  {
    icon: Shield,
    title: "Secure by design",
    description: "JWT auth, ownership-scoped retrieval, and bcrypt passwords. Your documents are only visible to you.",
  },
];

export default function LandingPage() {
  // Phase E: httpOnly cookies are invisible to JS, so the landing
  // page no longer presence-checks a token. It links to the
  // dashboard, which proves auth via GET /me and redirects to
  // /login on failure.

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="sticky top-0 z-50 border-b border-surface-border bg-surface/80 backdrop-blur-xl">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-slate-100">RAG Assistant</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/login" className="btn-ghost text-sm">
              Sign in
            </Link>
            <Link href="/register" className="btn-primary text-sm">
              Get started <ChevronRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </nav>

      <main className="flex-1">
        <section className="relative pt-28 pb-24 px-6 text-center overflow-hidden">
          <div className="absolute inset-0 bg-hero-glow pointer-events-none" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-brand-600/5 rounded-full blur-3xl pointer-events-none" />

          <div className="relative max-w-4xl mx-auto animate-fade-in">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-brand-600/10 border border-brand-500/20 text-brand-300 text-sm font-medium mb-8">
              <span className="w-2 h-2 rounded-full bg-brand-400 animate-pulse-slow" />
              Powered by your documents + Qdrant vector search
            </div>

            <h1 className="text-5xl md:text-7xl font-bold text-slate-100 mb-6 leading-tight">
              Ask anything about{" "}
              <span className="gradient-text">your documents</span>
            </h1>

            <p className="text-xl text-slate-400 mb-10 max-w-2xl mx-auto leading-relaxed">
              Upload PDFs, Word files, and notes. Get precise answers with citations
              from an agentic RAG system that actually knows what it&apos;s talking about.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link href="/register" className="btn-primary text-base px-8 py-3.5">
                Start for free <ChevronRight className="w-5 h-5" />
              </Link>
              <Link href="/login" className="btn-ghost text-base px-8 py-3.5">
                Sign in to your account
              </Link>
            </div>
          </div>
        </section>

        <section className="py-20 px-6">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-3xl font-bold text-slate-100 mb-4">
                Built for engineers who care about{" "}
                <span className="gradient-text">how it works</span>
              </h2>
              <p className="text-slate-400 text-lg max-w-xl mx-auto">
                Every design decision is explainable. No black boxes.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {features.map((feature) => (
                <div
                  key={feature.title}
                  className="card-hover p-8 group animate-slide-up"
                >
                  <div className="w-12 h-12 rounded-xl bg-brand-600/10 border border-brand-500/20 flex items-center justify-center mb-5 group-hover:bg-brand-600/20 transition-colors">
                    <feature.icon className="w-6 h-6 text-brand-400" />
                  </div>
                  <h3 className="font-semibold text-slate-100 text-lg mb-2">
                    {feature.title}
                  </h3>
                  <p className="text-slate-400 leading-relaxed">
                    {feature.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="py-20 px-6">
          <div className="max-w-3xl mx-auto text-center card p-16 relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-brand-600/5 via-transparent to-violet-600/5 pointer-events-none" />
            <h2 className="text-4xl font-bold text-slate-100 mb-4 relative">
              Ready to interrogate your documents?
            </h2>
            <p className="text-slate-400 mb-8 text-lg relative">
              No credit card required. Upload your first document in seconds.
            </p>
            <Link href="/register" className="btn-primary text-base px-10 py-4 relative">
              Create free account <ChevronRight className="w-5 h-5" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-surface-border py-8 text-center text-slate-500 text-sm">
        RAG Knowledge Assistant · Built with Next.js, FastAPI and Qdrant
      </footer>
    </div>
  );
}
