// Gönderi metni: paragraflar ve alıntılar ("> " satırları). Düz metindir; HTML yorumlanmaz.

import { bodyBlocks } from "@/lib/forum";

export function ForumBody({ body, testId }: { body: string; testId?: string }) {
  return (
    <div className="space-y-3 text-[15.5px] leading-relaxed text-fg" data-testid={testId}>
      {bodyBlocks(body).map((block, i) =>
        block.kind === "quote" ? (
          <blockquote key={i} className="whitespace-pre-line break-words rounded-r-xl border-l-4 border-accent-text/60 bg-surface-2 px-4 py-2.5 text-sm text-muted">
            {block.text}
          </blockquote>
        ) : (
          <p key={i} className="whitespace-pre-line break-words">
            {block.text}
          </p>
        ),
      )}
    </div>
  );
}
