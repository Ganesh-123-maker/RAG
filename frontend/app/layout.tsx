import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Toaster } from "react-hot-toast";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

// force-dynamic is required by the nonce CSP (see middleware.ts):
// statically prerendered pages are baked at build time, before any
// request nonce exists, so their inline RSC scripts would ship
// without a nonce and the browser would block them. This app is an
// authenticated client-side app, so giving up static prerendering
// costs nothing measurable.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "RAG Knowledge Assistant — Ask Your Documents",
  description:
    "Upload PDFs, DOCX, and text files. Ask questions and get precise, cited answers grounded in your documents.",
  keywords: ["RAG", "AI", "document search", "knowledge assistant"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} font-sans`}>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: "#16162a",
              color: "#f1f5f9",
              border: "1px solid #2d2d4e",
              borderRadius: "12px",
              fontSize: "14px",
            },
            success: {
              iconTheme: { primary: "#6366f1", secondary: "#f1f5f9" },
            },
            error: {
              iconTheme: { primary: "#f87171", secondary: "#f1f5f9" },
            },
          }}
        />
      </body>
    </html>
  );
}
