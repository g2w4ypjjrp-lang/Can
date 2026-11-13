// Gönderi metni: paragraflar ve alıntılar ("> " satırları). Düz metindir; HTML yorumlanmaz.

import { bodyBlocks } from "@/lib/forum";

export function ForumBody({ body, testId }: { body: string; testId?: string }) {
  return (
    <div className="space-y-2.5 text-[14px] leading-[1.65] text-fg" data-testid={testId}>
      {bodyBlocks(body).map((block, i) =>
        block.kind === "quote" ? (
          <blockquote key={i} className="whitespace-pre-line break-words rounded-r-lg border-l-4 border-accent-text/60 bg-surface-2 px-3.5 py-2 text-[13px] text-muted">
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
