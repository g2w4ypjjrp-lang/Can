import { LogIn } from "lucide-react";

import { LinkButton } from "@/components/ui";

export function LoginPrompt({ next, action }: { next: string; action: string }) {
  return (
    <div className="rounded-3xl border border-border bg-surface p-6 text-center shadow-sm" data-testid="forum-login">
      <LogIn aria-hidden="true" className="mx-auto h-8 w-8 text-accent-text" />
      <p className="mt-3 font-semibold text-fg">{action} için giriş yapın</p>
      <p className="mt-1 text-sm text-muted">Hesabınız yoksa birkaç saniyede oluşturabilirsiniz; e-posta doğrulaması gerekir.</p>
      <div className="mt-5 flex flex-wrap justify-center gap-3">
        <LinkButton href={`/giris?sonra=${encodeURIComponent(next)}`}>Giriş yap</LinkButton>
        <LinkButton href="/kayit" variant="secondary">
          Hesap oluştur
        </LinkButton>
      </div>
    </div>
  );
}
