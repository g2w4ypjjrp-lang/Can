import assert from "node:assert/strict";
import { test } from "node:test";
import { formatMoney, metricText } from "./format.ts";

test("veri yoksa sayı uydurulmaz", () => {
  assert.equal(metricText({ value: null, status: "not_connected" }), "Bağlı değil");
  assert.equal(metricText({ value: null, status: "no_data" }), "Henüz veri yok");
  assert.equal(metricText({ value: 5, status: "no_data" }), "Henüz veri yok");
});

test("gerçek veri biçimlenir", () => {
  assert.equal(metricText({ value: 12500, status: "ok" }), "12.500");
});

test("para birimleri ayrı gösterilir, dönüştürülmez", () => {
  const out = formatMoney([{ currency: "USD", amount: "35.50" }, { currency: "TRY", amount: "100" }]);
  assert.equal(out.length, 2);
  assert.match(out[0], /35,50/);
  assert.match(out[1], /100,00/);
});
