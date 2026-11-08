"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { apiRequest } from "@/lib/api";

interface Api {
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
}

const ApiContext = createContext<Api | null>(null);

export function ApiProvider({ baseUrl, children }: { baseUrl: string; children: ReactNode }) {
  const api = useMemo<Api>(
    () => ({
      get: (path) => apiRequest(baseUrl, path),
      post: (path, body) => apiRequest(baseUrl, path, { method: "POST", body: body ?? {} }),
    }),
    [baseUrl],
  );
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("ApiProvider eksik");
  return api;
}
