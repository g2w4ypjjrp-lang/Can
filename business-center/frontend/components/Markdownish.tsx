/** Model çıktısını güvenle gösterir: HTML yorumlanmaz, yalnızca başlık/madde/kalın biçimlenir. */
export function Markdownish({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {lines.map((line, i) => {
        const h = /^(#{1,4})\s+(.*)$/.exec(line);
        if (h) return <p key={i} className="pt-2 font-semibold">{bold(h[2])}</p>;
        const li = /^\s*([-*]|\d+\.)\s+(.*)$/.exec(line);
        if (li) return <p key={i} className="pl-4 -indent-3">• {bold(li[2])}</p>;
        if (!line.trim()) return <div key={i} className="h-2" />;
        return <p key={i}>{bold(line)}</p>;
      })}
    </div>
  );
}

function bold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part);
}
