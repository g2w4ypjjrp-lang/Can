// Forum uçtan uca: müşteri konu açar (onaya düşer, onaysız görünmez), yönetici onaylar ya da
// nedenle reddeder, yanıt onayla görünür; coin haberi panelden "Paylaş" ile ekip konusu olur.
// Haberler veritabanına doğrudan eklenir (testler dış kaynaklara bağlanmaz). Erişilebilirlik.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { randomBytes } from "node:crypto";

import { inviteAdmin, sql } from "./db";
import { TotpDevice } from "./totp";

const PASSWORD = "Yonetici-Parolasi-2026!";
const EMAIL = "forumcu@example.com";

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function noAxeViolations(target: Page) {
  const result = await new AxeBuilder({ page: target }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

let customerContext: BrowserContext;
let adminContext: BrowserContext;
let page: Page;
let admin: Page;

test.beforeAll(async ({ browser }) => {
  const options = { locale: "tr-TR", timezoneId: "Europe/Istanbul", baseURL: "http://127.0.0.1:3100" };
  customerContext = await browser.newContext(options);
  adminContext = await browser.newContext(options);
  page = await customerContext.newPage();
  admin = await adminContext.newPage();
});

test.afterAll(async () => {
  await customerContext.close();
  await adminContext.close();
});

test("müşteri konu açar; onaydan önce forumda görünmez", async () => {
  await page.goto("/forum/yeni");
  await expect(page.getByTestId("forum-login")).toContainText("Konu açmak için giriş yapın");
  await noAxeViolations(page);

  // Kayıt akışı account.spec'te sınanır; burada IP başına kayıt sınırına takılmamak için müşteri ve
  // oturumu doğrudan oluşturulur (çerez API'nin koyduğu oturum çereziyle aynıdır).
  const token = randomBytes(32).toString("base64url");
  await sql(
    "WITH c AS (INSERT INTO customers (email, password_hash, email_verified_at) VALUES ($1, '$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA', now()) RETURNING id) " +
      "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, expires_at) " +
      "SELECT id, sha256(convert_to($2, 'UTF8')), 'web', now() + interval '1 day' FROM c",
    [EMAIL, token],
  );
  await customerContext.addCookies([{ name: "ati_session", value: token, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Strict" }]);

  await page.goto("/forum/yeni");
  const form = page.getByTestId("topic-form");
  await form.getByText("Strateji ve analiz").click();
  await form.getByLabel("Forumda görünecek adınız").fill("Deneme Yatırımcı");
  await form.getByLabel("İlgili coin").fill("solusdt");
  await form.getByLabel("Başlık").fill("SOL için destek seviyeleri");
  await form.getByLabel("Metin").fill("Merhaba,\n\n4 saatlik grafikte 170 seviyesi destek gibi duruyor.\nSizce?");
  await noAxeViolations(page);
  await form.getByRole("button", { name: "Onaya gönder" }).click();
  await expect(form.getByRole("status")).toContainText("Yönetici onayından sonra");
  await expect(page.getByTestId(/^my-topic-/)).toContainText("Onay bekliyor");

  // Kazanç vaadi içeren ikinci konu (yönetici reddedecek).
  await form.getByLabel("Başlık").fill("Herkes katılsın");
  await form.getByLabel("Metin").fill("Bu grupta garanti kâr var, t.me/sahte adresine yazın.");
  await form.getByRole("button", { name: "Onaya gönder" }).click();
  await expect(page.getByTestId(/^my-topic-/)).toHaveCount(2);

  await page.goto("/forum");
  await expect(page.getByTestId("forum-empty")).toBeVisible();
});

test("yönetici onaylar ve reddeder; yanıt onaydan sonra görünür", async () => {
  const path = inviteAdmin("forum-yonetici@example.com", "Forum Yöneticisi");
  await admin.goto(path);
  const secret = (await admin.getByTestId("totp-secret").textContent())!.trim();
  const device = new TotpDevice(secret);
  await admin.getByLabel("Parola", { exact: true }).fill(PASSWORD);
  await admin.getByLabel("Parola (tekrar)").fill(PASSWORD);
  await admin.getByLabel("Doğrulama kodu").fill(await device.next());
  await admin.getByRole("button", { name: "Hesabı etkinleştir" }).click();
  await admin.getByLabel("Kodları güvenli bir yere kaydettim").check();
  await admin.getByRole("button", { name: "Panele geç" }).click();

  await admin.getByRole("link", { name: "Forum onayları" }).click();
  await expect(admin.getByRole("heading", { level: 1, name: "Forum onayları" })).toBeVisible();
  const good = admin.getByTestId(/^queue-topic-/).filter({ hasText: "SOL için destek seviyeleri" });
  const spam = admin.getByTestId(/^queue-topic-/).filter({ hasText: "Herkes katılsın" });
  await expect(good).toContainText("İlk konusu");
  await expect(good).toContainText(EMAIL);
  await expect(spam).toContainText("kazanç vaadi");
  await expect(spam).toContainText("iletişim / reklam");
  await noAxeViolations(admin);

  await spam.getByRole("button", { name: "Reddet…" }).click();
  await spam.getByLabel("Reddetme nedeni (müşteri görür)").fill("Kazanç vaadi ve reklam içeriyor");
  await spam.getByRole("button", { name: "Reddet", exact: true }).click();
  await expect(admin.getByRole("status").filter({ hasText: "Reddedildi" })).toBeVisible();
  await good.getByRole("button", { name: /onayla$/ }).click();
  await expect(admin.getByRole("status").filter({ hasText: "Onaylandı ve yayımlandı" })).toBeVisible();
  await expect(admin.getByTestId(/^queue-topic-/)).toHaveCount(0);

  // Müşteri: konu yayında, coin jetonu ve içerik görünür; reddedilen konunun nedeni görünür.
  await page.goto("/forum");
  const card = page.getByTestId(/^topic-\d+$/).filter({ hasText: "SOL için destek seviyeleri" });
  await expect(card).toContainText("Strateji ve analiz");
  await expect(card).toContainText("Deneme Yatırımcı");
  await noAxeViolations(page);
  await card.getByRole("link", { name: "SOL için destek seviyeleri" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("SOL için destek seviyeleri");
  await expect(page).toHaveTitle(/SOL için destek seviyeleri/); // başlık akışla gelir; denetimden önce beklenir
  await expect(page.getByText("1 görüntüleme")).toBeVisible(); // bir ziyaret bir görüntüleme
  await expect(page.getByTestId("topic-body")).toContainText("170 seviyesi destek");
  // Rütbe: ilk mesajla Seviye 10 (Sui); bir üst rütbeye kalan mesaj yazar.
  await expect(page.getByTestId("author-rank").first()).toContainText("Seviye 10 · Sui");
  await expect(page.getByTestId("author-rank").first()).toContainText("Avalanche için 2 mesaj");
  await noAxeViolations(page);

  const reply = page.getByTestId("reply-form");
  await expect(reply.getByLabel("Forumda görünecek adınız")).toHaveValue("Deneme Yatırımcı"); // hatırlanır
  await reply.getByLabel("Yanıtınız").fill("Güncelleme: 165 altına stop koydum.");
  await reply.getByRole("button", { name: "Onaya gönder" }).click();
  await expect(reply.getByRole("status")).toContainText("onayından sonra");
  await expect(page.getByTestId("replies")).toHaveCount(0);

  await admin.reload();
  const pending = admin.getByTestId("queue-reply").filter({ hasText: "165 altına stop" });
  await expect(pending).toContainText("SOL için destek seviyeleri");
  await pending.getByRole("button", { name: /onayla$/ }).click();
  await expect(admin.getByTestId("queue-reply")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("replies")).toContainText("165 altına stop koydum.");

  await page.goto("/forum/yeni");
  const mine = page.getByTestId(/^my-topic-/).filter({ hasText: "Herkes katılsın" });
  await expect(mine).toContainText("Reddedildi");
  await expect(mine).toContainText("Yönetici notu: Kazanç vaadi ve reklam içeriyor");
});

test("coin haberi panelden paylaşılır, forumda sabit ekip konusu olur", async () => {
  await sql(
    "INSERT INTO coin_news (source, external_id, kind, title, summary, url, symbols, published_at) VALUES " +
      "('binance', 'e2e-1', 'listing', 'Binance Will List Testcoin (TST) with Seed Tag Applied', " +
      "'Binance resmî duyurusu (yeni listeleme kategorisi).', 'https://www.binance.com/en/support/announcement/detail/abc', " +
      "'{TST}', now() - interval '5 minutes'), " +
      "('btchaber', 'e2e-2', 'news', 'Bitcoin haftaya yatay başladı', 'Piyasa sakin seyrediyor.', " +
      "'https://www.btchaber.com/bitcoin-yatay/', '{}', now() - interval '1 hour')",
  );
  // İngilizce kaynak: Türkçe çevirisiyle (çeviri bulut testlerinde sınanır).
  await sql(
    "INSERT INTO coin_news (source, external_id, kind, title, url, published_at, lang, title_tr) VALUES " +
      "('cointelegraph', 'e2e-3', 'news', 'Bitcoin rallies past 70k', 'https://cointelegraph.com/news/x', " +
      "now() - interval '2 hours', 'en', 'Bitcoin 70 bini aştı')",
  );
  await admin.getByRole("link", { name: "Coin haberleri" }).click();
  await expect(admin.getByRole("heading", { level: 1, name: "Coin haberleri" })).toBeVisible();
  const card = admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Testcoin" });
  await expect(card).toContainText("Yeni coin");
  await expect(card).toContainText("Binance duyuruları");
  await expect(admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Bitcoin haftaya" })).toHaveCount(0); // yeni coin sekmesi
  await expect(admin.getByTestId("news-sources")).toContainText("Binance yeni işlem çiftleri");
  await noAxeViolations(admin);

  await card.getByRole("button", { name: /paylaş$/ }).click();
  const form = card.getByTestId("share-form");
  await expect(form.getByLabel("Coin", { exact: true })).toHaveValue("TST");
  await expect(form.getByRole("combobox")).toHaveValue("yeni-coin");
  await form.getByLabel("Başlık").fill("Binance Testcoin (TST) listeliyor");
  await form.getByLabel("Üstte sabitle").check();
  await noAxeViolations(admin);
  await form.getByRole("button", { name: "Forumda paylaş" }).click();
  await expect(admin.getByRole("status").filter({ hasText: /Paylaşıldı: forum konusu #\d+/ })).toBeVisible();
  await expect(admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Testcoin" })).toHaveCount(0);

  await admin.getByRole("tab", { name: /Tüm yeni haberler/ }).click();
  const english = admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Bitcoin 70 bini aştı" });
  await expect(english.getByTestId("news-title")).toHaveText("Bitcoin 70 bini aştı");
  await expect(english).toContainText("Orijinal: Bitcoin rallies past 70k");
  await expect(admin.getByTestId("news-translation")).toContainText("MyMemory");
  const other = admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Bitcoin haftaya" });
  await other.getByRole("button", { name: "Gizle" }).click();
  await expect(other).toHaveCount(0);
  await admin.getByRole("tab", { name: "Gizlenenler" }).click();
  await expect(admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Bitcoin haftaya" })).toBeVisible();
  await admin.getByRole("tab", { name: "Paylaşılanlar" }).click();
  await expect(admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Testcoin" })).toContainText(/Forumda: konu #\d+/);

  // Forumda: sabit, resmî, kaynak bağlantılı.
  await page.goto("/forum");
  const first = page.getByTestId(/^topic-\d+$/).first();
  await expect(first).toContainText("Binance Testcoin (TST) listeliyor");
  await expect(first).toContainText("Resmî");
  await expect(first).toContainText("Sabit");
  await first.getByRole("link", { name: "Binance Testcoin (TST) listeliyor" }).click();
  await expect(page).toHaveTitle(/Binance Testcoin \(TST\) listeliyor/);
  await expect(page.getByTestId("topic-source")).toHaveAttribute("href", "https://www.binance.com/en/support/announcement/detail/abc");
  await expect(page.getByTestId("topic-source")).toContainText("Binance duyuruları");
  await noAxeViolations(page);
  await page.goto("/forum?kategori=yeni-coin");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Yeni coinler");
  await expect(page.getByTestId("forum-total")).toHaveText("1 konu");
  await page.goto("/forum?ara=destek");
  await expect(page.getByTestId("forum-total")).toContainText("1 konu");

  // Yönetici konuyu gizler → forumdan kalkar.
  await admin.getByRole("link", { name: "Forum onayları" }).click();
  await admin.getByRole("tab", { name: "Bütün konular" }).click();
  const row = admin.getByTestId(/^admin-topic-/).filter({ hasText: "SOL için destek seviyeleri" });
  await row.getByRole("button", { name: /Gizle$/ }).click();
  await expect(row).toContainText("Gizli");
  await page.goto("/forum");
  await expect(page.getByTestId(/^topic-\d+$/)).toHaveCount(1);
});

test("yeni coin haberinden otomatik taslak onaya düşer, düzenlenip yayımlanır", async () => {
  // Haber çekme turu taslağı böyle hazırlar (tur bulut testlerinde sınanır; burada dış kaynak yok).
  await sql(
    "WITH t AS (INSERT INTO forum_topics (author_kind, author_name, category, title, body, coin_symbol, source_name, " +
      "source_url, status, flags) VALUES ('team', 'AI Trading Ekibi', 'yeni-coin', 'Binance Otocoin (OTO) listeliyor', " +
      "'Yeni coin haberi: “Binance Will List Otocoin (OTO)”. Bilgilendirme amaçlıdır; yatırım tavsiyesi değildir.', 'OTO', " +
      "'Binance duyuruları', 'https://www.binance.com/en/support/announcement/detail/oto', 'pending', '{otomatik taslak}') RETURNING id) " +
      "INSERT INTO coin_news (source, external_id, kind, title, url, symbols, published_at, status, topic_id) " +
      "SELECT 'binance', 'e2e-oto', 'listing', 'Binance Will List Otocoin (OTO)', " +
      "'https://www.binance.com/en/support/announcement/detail/oto', '{OTO}', now(), 'drafted', id FROM t",
  );
  await admin.goto("/yonetim/haberler");
  await expect(admin.getByTestId("auto-draft")).toContainText("1 taslak onay bekliyor");
  await expect(admin.getByTestId("auto-draft").getByLabel("Yeni coin haberlerinden otomatik taslak oluştur")).toBeChecked();
  await expect(admin.getByTestId("nav-badge-forum")).toContainText("1");
  await admin.getByRole("tab", { name: /Onay bekleyen taslaklar/ }).click();
  await expect(admin.getByTestId(/^news-[0-9a-f]{8}$/).filter({ hasText: "Otocoin" })).toContainText(/Otomatik taslak onay bekliyor: konu #\d+/);
  await noAxeViolations(admin);

  await admin.getByTestId("auto-draft").getByRole("link", { name: /taslak onay bekliyor/ }).click();
  const draft = admin.getByTestId(/^queue-topic-/).filter({ hasText: "Otocoin" });
  await expect(draft).toContainText("Otomatik taslak (yeni coin haberi)");
  await expect(draft).toContainText("Kaynak: Binance duyuruları");
  await draft.getByRole("button", { name: "Düzenle" }).click();
  const edit = draft.getByTestId("edit-draft");
  await edit.getByLabel("Başlık").fill("Binance Otocoin (OTO) listeliyor: ayrıntılar");
  await noAxeViolations(admin);
  await edit.getByRole("button", { name: "Değişiklikleri kaydet" }).click();
  await expect(admin.getByRole("status").filter({ hasText: "Taslak güncellendi" })).toBeVisible();
  const edited = admin.getByTestId(/^queue-topic-/).filter({ hasText: "listeliyor: ayrıntılar" });
  await edited.getByRole("button", { name: /onayla$/ }).click();
  await expect(admin.getByRole("status").filter({ hasText: "Onaylandı ve yayımlandı" })).toBeVisible();
  await expect(admin.getByTestId("nav-badge-forum")).toHaveCount(0);

  const news = await sql<{ status: string }>("SELECT status FROM coin_news WHERE external_id = 'e2e-oto'");
  expect(news).toEqual([{ status: "shared" }]);
  await page.goto("/forum?kategori=yeni-coin");
  const row = page.getByTestId(/^topic-\d+$/).filter({ hasText: "Binance Otocoin (OTO) listeliyor: ayrıntılar" });
  await expect(row).toContainText("Ekip");
  await page.goto("/forum/rutbeler");
  await expect(page.getByTestId("rank-1")).toContainText("Bitcoin");
  await expect(page.getByTestId("rank-10")).toContainText("Başlangıç");
  await noAxeViolations(page);
});

test("ikinci üye: beğeni, yükseliş oyu, alıntıyla yanıt, kalıcı ad, profil ve liderlik tablosu", async ({ browser }) => {
  const token = randomBytes(32).toString("base64url");
  await sql(
    "WITH c AS (INSERT INTO customers (email, password_hash, email_verified_at) VALUES ('okur@example.com', " +
      "'$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA', now()) RETURNING id) " +
      "INSERT INTO customer_sessions (customer_id, refresh_token_hash, client_kind, expires_at) " +
      "SELECT id, sha256(convert_to($1, 'UTF8')), 'web', now() + interval '1 day' FROM c",
    [token],
  );
  const ctx = await browser.newContext({ locale: "tr-TR", timezoneId: "Europe/Istanbul", baseURL: "http://127.0.0.1:3100" });
  await ctx.addCookies([{ name: "ati_session", value: token, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Strict" }]);
  const okur = await ctx.newPage();
  const [row] = await sql<{ number: string }>("SELECT number FROM forum_topics WHERE title = 'Binance Testcoin (TST) listeliyor'");
  await okur.goto(`/forum/${row!.number}`);
  await expect(okur).toHaveTitle(/Binance Testcoin/);

  const like = okur.getByTestId("like-topic");
  await expect(like).toContainText("Faydalı 0");
  await like.click();
  await expect(like).toHaveAttribute("aria-pressed", "true");
  await expect(like).toContainText("Faydalı 1");

  const poll = okur.getByTestId("sentiment");
  await poll.getByTestId("vote-bull").click();
  await expect(poll.getByTestId("sentiment-counts")).toContainText("Yükseliş %100 (1)");
  await expect(poll.getByTestId("vote-bull")).toHaveAttribute("aria-pressed", "true");

  await okur.getByTestId("post-1").getByRole("button", { name: "Alıntıla" }).click();
  const reply = okur.getByTestId("reply-form");
  await expect(reply.getByLabel("Yanıtınız")).toHaveValue(/^> AI Trading Ekibi yazdı:\n> /);
  await reply.getByLabel("Yanıtınız").press("End");
  await reply.getByLabel("Yanıtınız").pressSequentially("Takipteyim.");
  // Ad başka üyede: reddedilir; başka ad seçilince yanıt onaya gider ve ad kalıcı olur.
  await reply.getByLabel("Forumda görünecek adınız").fill("Deneme Yatırımcı");
  await reply.getByRole("button", { name: "Onaya gönder" }).click();
  await expect(reply.getByRole("alert")).toContainText("başka bir üyede");
  await reply.getByLabel("Forumda görünecek adınız").fill("Okur Ali");
  await reply.getByRole("button", { name: "Onaya gönder" }).click();
  await expect(reply.getByRole("status")).toContainText("onayından sonra");
  await expect(reply.getByLabel("Forumda görünecek adınız")).toHaveAttribute("readonly", "");
  await noAxeViolations(okur);

  await admin.goto("/yonetim/forum");
  await admin.getByTestId("queue-reply").filter({ hasText: "Takipteyim" }).getByRole("button", { name: /onayla$/ }).click();
  await expect(admin.getByTestId("queue-reply")).toHaveCount(0);

  await okur.reload();
  const post = okur.getByTestId("post-2");
  await expect(post.locator("blockquote")).toContainText("AI Trading Ekibi yazdı:");
  await expect(post).toContainText("Takipteyim.");
  await post.getByRole("link", { name: "Okur Ali" }).click();
  await expect(okur.getByTestId("member-name")).toHaveText("Okur Ali");
  await expect(okur.getByTestId("member-stats")).toContainText("Mesaj1");
  await expect(okur.getByTestId("rank-10")).toContainText("Sui");
  await noAxeViolations(okur);

  await okur.goto("/forum/rutbeler");
  const board = okur.getByTestId("leaderboard");
  await expect(board).toContainText("Deneme Yatırımcı");
  await expect(board).toContainText("Okur Ali");
  await ctx.close();
});
