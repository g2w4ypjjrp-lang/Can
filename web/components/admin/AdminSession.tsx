"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { useApi } from "@/components/ApiContext";
import { ApiError } from "@/lib/api";
import type { AdminMe } from "@/lib/admin";

interface SessionState {
  me: AdminMe | null;
  loading: boolean;
  reload: () => void;
}

const AdminSessionContext = createContext<SessionState>({ me: null, loading: true, reload: () => {} });

/** Yönetici oturumu: /admin/v1/auth/me. Oturum yoksa giriş sayfasına yönlendirir. */
export function AdminSessionProvider({ children }: { children: ReactNode }) {
  const api = useApi();
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<AdminMe | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    setLoading(true);
    api
      .get<AdminMe>("/admin/v1/auth/me")
      .then((value) => setMe(value))
      .catch((err: unknown) => {
        setMe(null);
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/yonetim/giris?sonra=${encodeURIComponent(pathname)}`);
        }
      })
      .finally(() => setLoading(false));
  }, [api, router, pathname]);

  useEffect(() => {
    reload();
  }, [reload]);

  return <AdminSessionContext.Provider value={{ me, loading, reload }}>{children}</AdminSessionContext.Provider>;
}

export function useAdmin(): SessionState {
  return useContext(AdminSessionContext);
}
