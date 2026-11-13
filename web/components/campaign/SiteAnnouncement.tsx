// Duyuru şeridinin sunucu tarafı: yönetimden girilen duyuru, yoksa yürürlükteki kampanya.

import { AnnouncementBar } from "@/components/campaign/AnnouncementBar";
import { fetchAnnouncement } from "@/lib/announcement";

function hash(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) h = (Math.imul(31, h) + text.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

export async function SiteAnnouncement() {
  const { announcement, campaign } = await fetchAnnouncement();
  if (announcement) {
    return (
      <AnnouncementBar
        id={hash(`a|${announcement.text}|${announcement.link}|${announcement.ends_at ?? ""}`)}
        text={announcement.text}
        link={announcement.link}
        linkLabel="Ayrıntılar"
        tone={announcement.tone}
        endsAt={announcement.ends_at}
      />
    );
  }
  if (campaign) {
    const ends = campaign.ends_at && new Date(campaign.ends_at).getTime() > Date.now() ? campaign.ends_at : null;
    return (
      <AnnouncementBar
        id={hash(`c|${campaign.percent}|${campaign.label ?? ""}|${campaign.ends_at ?? ""}`)}
        text={`${campaign.label ?? "Kampanya"}: bütün paketlerde %${campaign.percent} indirim!`}
        link="/paketler"
        linkLabel="Fırsatı gör"
        tone="campaign"
        endsAt={ends}
      />
    );
  }
  return null;
}
