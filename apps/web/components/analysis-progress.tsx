"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { AnalysisRun } from "@sentinel/shared-schemas";

import { getAnalysisRun } from "@/lib/api-client";

const POLL_INTERVAL_MS = 3000;

/**
 * Live progress for a run still `pending` or `running`.
 *
 * Polls the API directly for a smooth progress bar, and asks the server
 * component tree to re-fetch (`router.refresh()`) once the run leaves those
 * states, so the rest of the page — the results table, the next step's form
 * — picks up the finished run without the user reloading anything.
 *
 * Pass `key={run.id}` from the parent: this component tracks one run's
 * progress internally, so a different run must remount it rather than have
 * its state synced from a changed prop.
 */
export function AnalysisProgress({ run }: { run: AnalysisRun }): React.ReactElement | null {
  const router = useRouter();
  const [current, setCurrent] = useState(run);
  const settled = useRef(false);

  useEffect(() => {
    if (current.status !== "pending" && current.status !== "running") {
      return;
    }
    const interval = setInterval(() => {
      getAnalysisRun(current.id)
        .then((updated) => {
          setCurrent(updated);
          if (updated.status !== "pending" && updated.status !== "running" && !settled.current) {
            settled.current = true;
            router.refresh();
          }
        })
        .catch(() => {
          // Transient network errors during polling are not worth surfacing;
          // the next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [current, router]);

  if (current.status !== "pending" && current.status !== "running") {
    return null;
  }

  const total = Number(current.metrics["total"] ?? 0);
  const completed = Number(current.metrics["completed"] ?? 0);
  const failed = Number(current.metrics["failed"] ?? 0);
  const ratio = total > 0 ? (completed + failed) / total : 0;

  return (
    <div className="progress">
      <div className="coverage-cell">
        <div className="coverage-bar" style={{ width: `${Math.min(100, ratio * 100)}%` }} />
        <span>
          {completed + failed} / {total}
        </span>
      </div>
      <p className="subtitle">Processing… this page updates automatically.</p>
    </div>
  );
}
