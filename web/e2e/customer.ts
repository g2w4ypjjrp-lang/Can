// Müşteri hesabı adımları (uçtan uca testlerde ortak): kayıt → e-posta doğrulama → giriş.
import { expect, type Page } from "@playwright/test";

import { latestLink } from "./db";

export const PASSWORD = "Uzun-Bir-Parola-2026";

export async function register(page: Page, email: string, password = PASSWORD) {
  await page.goto("/kayit");
  await page.getByLabel("Ad soyad").fill("Deneme Kullanıcı");
  await page.getByLabel("E-posta", { exact: true }).fill(email);
  await page.getByLabel("Parola", { exact: true }).fill(password);
  await page.getByLabel(/Kullanım koşullarını/).check();
  await page.getByRole("button", { name: "Hesap oluştur" }).click();
  await expect(page.getByRole("status")).toContainText("E-postanızı kontrol edin");
}

export async function verify(page: Page, email: string) {
  const link = await latestLink(email, "verify_email");
  expect(link.startsWith("http://127.0.0.1:3100/eposta-dogrula?token=")).toBe(true);
  await page.goto(link.replace("http://127.0.0.1:3100", ""));
  // Belirteç adres çubuğundan silinir (geçmişte ve ekran görüntülerinde kalmaz).
  await expect(page).toHaveURL(/\/eposta-dogrula$/);
  await page.getByRole("button", { name: "E-postamı doğrula" }).click();
  await expect(page.getByRole("status")).toContainText("doğrulandı");
}

export async function login(page: Page, email: string, password = PASSWORD, path = "/giris") {
  await page.goto(path);
  await page.getByLabel("E-posta", { exact: true }).fill(email);
  await page.getByLabel("Parola", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Giriş yap" }).click();
}
