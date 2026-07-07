/**
 * Job Tracker — applications pipeline plus AI assistance.
 *
 * Each job card: status dropdown, match score badge (from AI analysis),
 * expandable detail with the analysis, cover letter drafting, and interview
 * prep. ARIA never applies for you — everything here is draft and tracking.
 * Analysis quality depends on your Memory: add your CV/skills there first.
 */
"use client";

import { useEffect, useState } from "react";
import { api, type Job, type Recruiter } from "@/lib/api";

const STATUSES = ["saved", "applied", "interview", "offer", "rejected"] as const;

function scoreColor(score: number): string {
  if (score >= 70) return "bg-emerald-600";
  if (score >= 40) return "bg-amber-600";
  return "bg-red-700";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [recruiters, setRecruiters] = useState<Recruiter[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [prep, setPrep] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Add-job form
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  // Add-recruiter form
  const [recName, setRecName] = useState("");
  const [recCompany, setRecCompany] = useState("");
  const [recEmail, setRecEmail] = useState("");

  const refresh = () =>
    Promise.all([api.listJobs().then(setJobs), api.listRecruiters().then(setRecruiters)])
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function addJob(e: React.FormEvent) {
    e.preventDefault();
    await api.addJob({ company, role, url, description });
    setCompany(""); setRole(""); setUrl(""); setDescription("");
    await refresh();
  }

  /** Run one AI action on a job with busy/error handling. */
  async function ai(id: string, action: "analyze" | "cover" | "prep") {
    setBusyId(id);
    setError(null);
    try {
      if (action === "analyze") await api.analyzeJob(id);
      if (action === "cover") await api.draftCoverLetter(id);
      if (action === "prep") {
        const { text } = await api.interviewPrep(id);
        setPrep((p) => ({ ...p, [id]: text }));
      }
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function addRecruiter(e: React.FormEvent) {
    e.preventDefault();
    await api.addRecruiter({
      name: recName,
      company: recCompany,
      email: recEmail || null,
      notes: "",
    });
    setRecName(""); setRecCompany(""); setRecEmail("");
    await refresh();
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h2 className="mb-1 text-2xl font-semibold">Job Tracker</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Track applications, score your fit, draft cover letters and interview
        prep. ARIA never submits anything — applying stays in your hands.
      </p>

      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>
      )}

      {/* Add a job */}
      <form onSubmit={addJob} className="mb-8 space-y-2 rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <div className="flex gap-2">
          <input value={company} onChange={(e) => setCompany(e.target.value)} required
            placeholder="Company" aria-label="Company"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
          <input value={role} onChange={(e) => setRole(e.target.value)} required
            placeholder="Role" aria-label="Role"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
          <input value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="Posting URL (optional)" aria-label="URL"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
        </div>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="Paste the full job description here (needed for AI analysis)…"
          aria-label="Job description" rows={4}
          className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
        <button className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
          Track this job
        </button>
      </form>

      {/* Pipeline */}
      <ul className="mb-10 space-y-3">
        {jobs.map((job) => (
          <li key={job.id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <p className="text-sm font-medium">
                  {job.role} <span className="text-zinc-500">@ {job.company}</span>
                </p>
                {job.url && (
                  <a href={job.url} target="_blank" rel="noreferrer"
                    className="text-xs text-indigo-400 hover:underline">
                    posting ↗
                  </a>
                )}
              </div>
              {job.match_score !== null && (
                <span className={`rounded-full px-2.5 py-1 text-xs font-bold text-white ${scoreColor(job.match_score)}`}
                  title="AI match score">
                  {job.match_score}
                </span>
              )}
              <select value={job.status} aria-label="Status"
                onChange={(e) => api.updateJob(job.id, { status: e.target.value as Job["status"] }).then(refresh)}
                className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs capitalize">
                {STATUSES.map((s) => <option key={s}>{s}</option>)}
              </select>
              <button onClick={() => setOpenId(openId === job.id ? null : job.id)}
                className="text-xs text-zinc-400 hover:text-white">
                {openId === job.id ? "Close" : "Details"}
              </button>
            </div>

            {openId === job.id && (
              <div className="mt-4 space-y-4 border-t border-zinc-800 pt-4">
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => ai(job.id, "analyze")} disabled={busyId === job.id}
                    className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-40">
                    {busyId === job.id ? "Working…" : "Analyze fit"}
                  </button>
                  <button onClick={() => ai(job.id, "cover")} disabled={busyId === job.id}
                    className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:text-white disabled:opacity-40">
                    Draft cover letter
                  </button>
                  <button onClick={() => ai(job.id, "prep")} disabled={busyId === job.id}
                    className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:text-white disabled:opacity-40">
                    Interview prep
                  </button>
                  <button onClick={() => api.deleteJob(job.id).then(() => { setOpenId(null); refresh(); })}
                    className="ml-auto rounded-md px-3 py-1.5 text-xs text-zinc-500 hover:text-red-400">
                    Delete
                  </button>
                </div>

                {job.match_notes && (
                  <section>
                    <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">Fit analysis</h4>
                    <p className="whitespace-pre-wrap text-sm text-zinc-300">{job.match_notes}</p>
                  </section>
                )}
                {job.cover_letter && (
                  <section>
                    <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">Cover letter draft</h4>
                    <p className="whitespace-pre-wrap rounded bg-zinc-950 p-3 text-sm text-zinc-300">{job.cover_letter}</p>
                  </section>
                )}
                {prep[job.id] && (
                  <section>
                    <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">Interview prep</h4>
                    <p className="whitespace-pre-wrap text-sm text-zinc-300">{prep[job.id]}</p>
                  </section>
                )}
              </div>
            )}
          </li>
        ))}
        {jobs.length === 0 && (
          <p className="text-sm text-zinc-500">No jobs tracked yet — add the first one above.</p>
        )}
      </ul>

      {/* Recruiters */}
      <h3 className="mb-2 text-lg font-semibold">Recruiter contacts</h3>
      <form onSubmit={addRecruiter} className="mb-4 flex gap-2">
        <input value={recName} onChange={(e) => setRecName(e.target.value)} required
          placeholder="Name" aria-label="Recruiter name"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
        <input value={recCompany} onChange={(e) => setRecCompany(e.target.value)}
          placeholder="Company" aria-label="Recruiter company"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
        <input value={recEmail} onChange={(e) => setRecEmail(e.target.value)} type="email"
          placeholder="Email (optional)" aria-label="Recruiter email"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500" />
        <button className="rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
          Add
        </button>
      </form>
      <ul className="space-y-2">
        {recruiters.map((r) => (
          <li key={r.id} className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2">
            <span className="text-sm">
              {r.name}
              {r.company && <span className="text-zinc-500"> · {r.company}</span>}
              {r.email && <span className="ml-2 text-xs text-zinc-500">{r.email}</span>}
            </span>
            <button onClick={() => api.deleteRecruiter(r.id).then(refresh)}
              className="text-xs text-zinc-500 hover:text-red-400">
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
