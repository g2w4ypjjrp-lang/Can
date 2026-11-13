"use client";

import { useCallback, useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { ApiError } from "@/lib/api";

export interface ForumProfile {
  nickname: string;
  posts: number;
  topics: number;
  replies: number;
  likes: number;
  created_at: string;
}

export interface MyPosts {
  profile?: ForumProfile | null;
  topics: {
    number: number;
    title: string;
    category: string;
    status: "pending" | "approved" | "rejected" | "hidden";
    moderation_note: string | null;
    created_at: string;
  }[];
  replies: {
    number: number;
    title: string;
    body: string;
    status: "pending" | "approved" | "rejected" | "hidden";
    moderation_note: string | null;
    created_at: string;
  }[];
}

/** Forumda yazmak için oturum gerekir: kendi gönderileri okunarak oturum durumu anlaşılır. */
export function useForumAccount() {
  const api = useApi();
  const [state, setState] = useState<"loading" | "anon" | "ok" | "error">("loading");
  const [mine, setMine] = useState<MyPosts | null>(null);
  const load = useCallback(() => {
    // Önce oturum sorulur (ziyaretçiye de 200): girişsiz ziyaretçide konsolda 401 hatası oluşmaz.
    api
      .get<{ logged_in: boolean }>("/v1/forum/whoami")
      .then(async (who) => {
        if (!who.logged_in) {
          setState("anon");
          return;
        }
        setMine(await api.get<MyPosts>("/v1/forum/me"));
        setState("ok");
      })
      .catch((err: unknown) => setState(err instanceof ApiError && err.status === 401 ? "anon" : "error"));
  }, [api]);
  useEffect(load, [load]);
  return { state, mine, reload: load };
}

export const NAME_KEY = "ati-forum-name";

export function rememberedName(): string {
  try {
    return window.localStorage.getItem(NAME_KEY) ?? "";
  } catch {
    return "";
  }
}

export function rememberName(name: string) {
  try {
    window.localStorage.setItem(NAME_KEY, name);
  } catch {
    // Depolama kapalı: ad her seferinde yazılır.
  }
}
