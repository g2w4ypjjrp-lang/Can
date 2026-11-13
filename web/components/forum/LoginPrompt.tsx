import { LogIn } from "lucide-react";

import { LinkButton } from "@/components/ui";

export function LoginPrompt({ next, action }: { next: string; action: string }) {
  return (
    <div className="fb-box p-5 text-center" data-testid="forum-login">
      <LogIn aria-hidden="true" className="mx-auto h-6 w-6 text-accent-text" />
      <p className="mt-2 text-[14px] font-semibold text-fg">{action} için giriş yapın</p>
      <p className="mt-1 text-[13px] text-muted">Hesabınız yoksa birkaç saniyede oluşturabilirsiniz; e-posta doğrulaması gerekir.</p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        <LinkButton href={`/giris?sonra=${encodeURIComponent(next)}`} size="sm">
          Giriş yap
        </LinkButton>
        <LinkButton href="/kayit" variant="secondary" size="sm">
          Hesap oluştur
        </LinkButton>
      </div>
    </div>
  );
}
