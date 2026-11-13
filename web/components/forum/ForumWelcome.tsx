"use client";

// Klasik forum "hoş geldiniz" çubuğu: girişliyse forum adı ve bağlantılar, değilse giriş / kayıt.

import Link from "next/link";
import { useEffect, useState } from "react";

import { useApi } from "@/components/ApiContext";
import { RankPill } from "@/components/forum/Ranks";

interface WhoAmI {
  logged_in: boolean;
  profile: { nickname: string; posts: number } | null;
}

export function ForumWelcome() {
  const api = useApi();
  // Ziyaretçiye de 200 döner (tarayıcı konsolunda 401 hatası oluşmaz).
  const [who, setWho] = useState<WhoAmI | null>(null);
  useEffect(() => {
    api
      .get<WhoAmI>("/v1/forum/whoami")
      .then(setWho)
      .catch(() => setWho({ logged_in: false, profile: null }));
  }, [api]);
  const profile = who?.profile ?? null;
  const link = "font-semibold text-accent-text underline-offset-4 hover:underline";
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-border bg-surface-2 px-3.5 py-2 text-[13px] text-muted" data-testid="forum-welcome">
      {who === null ? (
        <span>Hoş geldiniz…</span>
      ) : who.logged_in ? (
        profile ? (
          <>
            <span>
              Hoş geldiniz, <b className="text-fg">{profile.nickname}</b>
            </span>
            <RankPill posts={profile.posts} team={false} />
            <span aria-hidden="true">·</span>
            <Link href={`/forum/uye/${encodeURIComponent(profile.nickname)}`} className={link}>
              Profilim
            </Link>
            <span aria-hidden="true">·</span>
            <Link href="/forum/yeni#gonderilerim" className={link}>
              Gönderilerim
            </Link>
          </>
        ) : (
          <span>
            Hoş geldiniz! İlk gönderinizde seçtiğiniz ad kalıcı forum adınız olur.{" "}
            <Link href="/forum/yeni" className={link}>
              Konu açın
            </Link>
          </span>
        )
      ) : (
        <span>
          Hoş geldiniz, <b className="text-fg">Ziyaretçi</b>. Konu açmak ve yanıt yazmak için{" "}
          <Link href="/giris?sonra=/forum" className={link}>
            giriş yapın
          </Link>{" "}
          ya da{" "}
          <Link href="/kayit" className={link}>
            hesap oluşturun
          </Link>
          .
        </span>
      )}
    </p>
  );
}
