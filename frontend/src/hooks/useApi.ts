import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../services/api";
import type { AnalysisRun } from "../types";
import { errorMessage } from "../utils/format";

export interface Loaded<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: (value: T | null) => void;
}

/** Load `path` whenever it changes. Pass null to skip the request. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (path === null) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<T>(path)
      .then((value) => {
        if (!cancelled) setData(value);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, loading, error, reload, setData };
}

/** Run an action with busy/error state, e.g. a form submit. */
export function useAction(): {
  busy: boolean;
  error: string | null;
  setError: (message: string | null) => void;
  run: <T>(action: () => Promise<T>) => Promise<T | undefined>;
} {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (err) {
      if (mounted.current) setError(errorMessage(err));
      return undefined;
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

/** Poll an analysis job until it is COMPLETED or FAILED. */
export async function waitForRun(run: AnalysisRun, onUpdate?: (run: AnalysisRun) => void, timeoutMs = 10 * 60 * 1000): Promise<AnalysisRun> {
  let current = run;
  const started = Date.now();
  while (current.status === "PENDING" || current.status === "PROCESSING") {
    if (Date.now() - started > timeoutMs) throw new Error("The analysis is taking longer than expected. Check Project History later.");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    current = await api.get<AnalysisRun>(`/analysis/${run.id}`);
    if (onUpdate) onUpdate(current);
  }
  return current;
}
