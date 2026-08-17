/**
 * Documents — read a file, ask it questions, decide what ARIA may believe.
 *
 * The backend has done this since the document-intelligence work; there was no
 * way to reach it from either the PC or the phone, which made it a capability
 * on paper only.
 *
 * The one rule this page exists to make visible: ARIA does not adopt beliefs
 * about MORICE's life because a model read them in a PDF. Every proposed fact
 * shows the quote it came from, and nothing enters memory until he accepts it.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Trash2, Upload } from "lucide-react";
import {
  api,
  type DocumentAnswer,
  type DocumentFact,
  type DocumentSummary,
} from "@/lib/api";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [selected, setSelected] = useState<DocumentSummary | null>(null);
  const [facts, setFacts] = useState<DocumentFact[]>([]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<DocumentAnswer | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(
    () =>
      api
        .listDocuments()
        .then(setDocuments)
        .catch((e: Error) => setError(e.message)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const openDocument = useCallback(async (document: DocumentSummary) => {
    setSelected(document);
    setAnswer(null);
    setQuestion("");
    setFacts(await api.listFacts(document.id).catch(() => []));
  }, []);

  async function upload(file: File) {
    setBusy("Reading the document…");
    setError(null);
    try {
      const created = await api.uploadDocument(file);
      await load();
      await openDocument(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function propose() {
    if (!selected) return;
    setBusy("Reading it for facts — this one uses the cloud model…");
    setError(null);
    try {
      setFacts(await api.extractFacts(selected.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function decide(fact: DocumentFact, accept: boolean) {
    const updated = await api.decideFact(fact.id, accept);
    setFacts((current) =>
      current.map((f) => (f.id === updated.id ? updated : f)),
    );
  }

  async function ask() {
    if (!selected || !question.trim()) return;
    setBusy("Looking it up in this document…");
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await api.askDocument(selected.id, question.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function remove(document: DocumentSummary) {
    await api.deleteDocument(document.id);
    if (selected?.id === document.id) setSelected(null);
    await load();
  }

  const proposed = facts.filter((f) => f.status === "proposed");
  const decided = facts.filter((f) => f.status !== "proposed");

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Documents</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Upload a PDF, Word file, or text file. ARIA reads it, makes it
        searchable, and can answer questions from that document alone — and she
        will say when it does not contain the answer rather than guess.
      </p>

      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {error}
        </p>
      )}
      {busy && <p className="mb-4 text-sm text-cyan-300">{busy}</p>}

      <section className="glass mb-6 rounded-xl p-5">
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.txt,.md,.csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
            e.target.value = "";
          }}
        />
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy !== ""}
          className="flex items-center gap-2 rounded-lg bg-cyan-500/20 px-4 py-2 text-sm text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40"
        >
          <Upload size={14} aria-hidden />
          Add a document
        </button>
        <p className="mt-2 text-[11px] text-zinc-500">
          Scanned PDFs with no text layer are refused with that reason — ARIA
          has no OCR, and pretending otherwise would produce an empty document
          that looks fine.
        </p>
      </section>

      {documents && documents.length === 0 && (
        <p className="text-sm text-zinc-500">
          No documents yet. A CV is a good first one: it feeds job analysis too.
        </p>
      )}

      <ul className="mb-6 space-y-2">
        {documents?.map((document) => (
          <li key={document.id} className="glass rounded-xl p-3">
            <div className="flex items-start justify-between gap-3">
              <button
                onClick={() => openDocument(document)}
                className="flex min-w-0 items-start gap-2 text-left"
              >
                <FileText
                  size={15}
                  aria-hidden
                  className="mt-0.5 shrink-0 text-zinc-500"
                />
                <span className="min-w-0">
                  <span
                    className={`block truncate text-sm ${
                      selected?.id === document.id
                        ? "text-cyan-300"
                        : "text-zinc-200"
                    }`}
                  >
                    {document.filename}
                  </span>
                  <span className="mt-0.5 block text-xs text-zinc-500">
                    {document.format} · {document.pages} page
                    {document.pages === 1 ? "" : "s"} ·{" "}
                    {document.characters.toLocaleString()} characters
                    {document.facts_extracted ? " · facts proposed" : ""}
                  </span>
                </span>
              </button>
              <button
                onClick={() => remove(document)}
                aria-label={`Delete ${document.filename}`}
                className="shrink-0 text-zinc-600 hover:text-red-400"
              >
                <Trash2 size={14} aria-hidden />
              </button>
            </div>
          </li>
        ))}
      </ul>

      {selected && (
        <>
          <section className="glass mb-6 rounded-xl p-5">
            <h3 className="mb-1 text-sm font-medium">
              Ask about {selected.filename}
            </h3>
            <p className="mb-3 text-xs text-zinc-500">
              Answered from this document only — not from your other documents,
              and not from what the model happens to know.
            </p>
            <div className="flex gap-2">
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask()}
                placeholder="e.g. what is the notice period?"
                aria-label="Question about this document"
                className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
              />
              <button
                onClick={ask}
                disabled={busy !== "" || !question.trim()}
                className="rounded-md bg-cyan-600 px-3 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
              >
                Ask
              </button>
            </div>
            {answer && (
              <div className="mt-3 border-t border-white/10 pt-3">
                <p className="whitespace-pre-wrap text-sm text-zinc-200">
                  {answer.answer}
                </p>
                <p className="mt-2 text-[11px] text-zinc-500">
                  {answer.scope} · answered by {answer.ran_on}
                </p>
              </div>
            )}
          </section>

          <section className="glass mb-6 rounded-xl p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium">What ARIA may remember</h3>
              <button
                onClick={propose}
                disabled={busy !== ""}
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:text-white disabled:opacity-40"
              >
                {facts.length ? "Read it again" : "Read it for facts"}
              </button>
            </div>
            <p className="mb-3 mt-1 text-xs text-zinc-500">
              Each fact shows the sentence it came from. Nothing enters memory
              until you accept it — ARIA does not believe things about your life
              because a model read them in a file.
            </p>

            {proposed.length === 0 && decided.length === 0 && (
              <p className="text-xs text-zinc-500">
                Nothing proposed yet.
              </p>
            )}

            <ul className="space-y-2">
              {proposed.map((fact) => (
                <li key={fact.id} className="rounded-lg bg-black/20 p-3">
                  <p className="text-sm text-zinc-200">{fact.fact}</p>
                  {fact.quote && (
                    <p className="mt-1 border-l-2 border-white/10 pl-2 text-xs italic text-zinc-500">
                      “{fact.quote}”
                    </p>
                  )}
                  <div className="mt-2 flex items-center gap-2">
                    <span className="mr-auto text-[11px] uppercase tracking-wide text-zinc-600">
                      {fact.category}
                    </span>
                    <button
                      onClick={() => decide(fact, true)}
                      className="rounded-md bg-emerald-500/20 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-500/30"
                    >
                      Remember this
                    </button>
                    <button
                      onClick={() => decide(fact, false)}
                      className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-400 hover:text-white"
                    >
                      No
                    </button>
                  </div>
                </li>
              ))}
              {decided.map((fact) => (
                <li key={fact.id} className="px-1 text-xs text-zinc-500">
                  <span
                    className={
                      fact.status === "accepted"
                        ? "text-emerald-400/80"
                        : "text-zinc-600"
                    }
                  >
                    {fact.status}
                  </span>{" "}
                  — {fact.fact}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
