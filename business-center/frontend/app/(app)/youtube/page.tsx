import { NotConnected, PageHeader, Stat, n } from "@/components/Page";
import { ProposeEdit } from "@/components/ProposeEdit";
import { QuickTask } from "@/components/QuickTask";
import { api } from "@/lib/api";
import { appContext } from "@/lib/context";

type Y = { channel: { title: string; youtube_channel_id: string; subscriber_count: number | null; view_count: number; video_count: number;
  stats_fetched_at: string } | null; videos: { youtube_video_id: string; title: string; privacy_status: string | null; published_at: string | null; tags: string[] | null }[];
  last30: { views: number | null; minutes: string | null; net_subs: number | null } };

export default async function YouTube() {
  const { token, org } = await appContext();
  const d = await api<Y>(`/api/organizations/${org.id}/youtube`, token);
  const admin = org.role !== "viewer";
  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader title="YouTube Management" desc={d.channel ? `${d.channel.title} · son güncelleme ${new Date(d.channel.stats_fetched_at).toLocaleString("tr-TR")}` : undefined}>
        {admin && <>
          <QuickTask orgId={org.id} agent="yt_trend_research" label="Video fikri bul" command="Bu hafta kanalım için 5 video fikri bul ve fırsat puanıyla sırala." />
          <QuickTask orgId={org.id} agent="yt_analytics" label="Performansı analiz et" command="Kanalımın son 30 günlük performansını analiz et ve 3 aksiyon öner." />
        </>}
      </PageHeader>
      {!d.channel ? <NotConnected what="YouTube kanalı" /> : <>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Abone" value={d.channel.subscriber_count === null ? "Gizli" : n(d.channel.subscriber_count)} />
          <Stat label="Toplam izlenme" value={n(d.channel.view_count)} />
          <Stat label="Son 30 gün izlenme" value={n(d.last30.views)} />
          <Stat label="Son 30 gün net abone" value={d.last30.net_subs === null ? "—" : `${d.last30.net_subs > 0 ? "+" : ""}${n(d.last30.net_subs)}`} />
        </div>
        <section className="overflow-hidden rounded-2xl border border-line bg-panel">
          <h2 className="border-b border-line p-4 font-semibold">Son videolar</h2>
          <ul className="divide-y divide-line">
            {d.videos.map((v) => (
              <li key={v.youtube_video_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-4 text-sm">
                <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(v.youtube_video_id)}`} target="_blank" rel="noopener noreferrer"
                  className="min-w-0 flex-1 truncate font-medium hover:underline">{v.title}</a>
                <span className="rounded-full bg-canvas px-2 py-0.5 text-xs">{v.privacy_status ?? "—"}</span>
                <span className="text-xs text-muted">{v.published_at ? new Date(v.published_at).toLocaleDateString("tr-TR") : ""}</span>
                {admin && <div className="w-full"><ProposeEdit orgId={org.id} action="youtube.video.update_metadata" targetId={v.youtube_video_id}
                  title={v.title} tags={v.tags ?? []} maxTitle={100} /></div>}
              </li>
            ))}
            {!d.videos.length && <li className="p-4 text-sm text-muted">Video yok. API Integrations'tan senkronlayın.</li>}
          </ul>
        </section>
      </>}
    </div>
  );
}
