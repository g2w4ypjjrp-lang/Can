// Paylaşılan protokol şemasından TypeScript tiplerini üretir.
// `--check`: üretilen dosya güncel değilse hata verir (CI).
import { readFile, writeFile } from "node:fs/promises";
import { compile } from "json-schema-to-typescript";

const SCHEMA = new URL("../../shared/protocol/engine-local-api.schema.json", import.meta.url);
const OUT = new URL("../src/api/types.gen.ts", import.meta.url);

const schema = JSON.parse(await readFile(SCHEMA, "utf8"));

// Pydantic her alana "title" yazar; derleyici bunları ayrı takma ad tiplerine çevirir.
// Yalnızca tanım köklerindeki başlıklar korunur, alanlarınki silinir (tipler satır içi olur).
function stripTitles(node, isRoot = false) {
  if (Array.isArray(node)) return node.map((n) => stripTitles(n));
  if (node === null || typeof node !== "object") return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === "title" && !isRoot) continue;
    if (key === "properties" || key === "$defs") {
      out[key] = Object.fromEntries(
        Object.entries(value).map(([k, v]) => [k, stripTitles(v, key === "$defs")]),
      );
    } else {
      out[key] = stripTitles(value);
    }
  }
  return out;
}

const defs = stripTitles({ $defs: schema.$defs ?? {} }).$defs;
for (const [name, def] of Object.entries(defs)) def.title = name;
// Tüm tanımları tek kök altında topla: her biri dışa aktarılan ayrı tip olur.
const root = {
  title: "EngineProtocol",
  type: "object",
  properties: Object.fromEntries(Object.keys(defs).map((k) => [k, { $ref: `#/$defs/${k}` }])),
  additionalProperties: false,
  $defs: defs,
};
let ts = await compile(root, "EngineProtocol", {
  bannerComment:
    "/* Otomatik üretildi: shared/protocol/engine-local-api.schema.json — elle düzenlemeyin.\n" +
    " * Yeniden üretmek için: npm run gen:types */",
  additionalProperties: false,
  declareExternallyReferenced: true,
  unreachableDefinitions: true,
  format: true,
  style: { singleQuote: false, printWidth: 100 },
});
ts += `\nexport const PROTOCOL_VERSION = ${JSON.stringify(schema["x-protocol-version"] ?? 0)};\n`;

if (process.argv.includes("--check")) {
  const current = await readFile(OUT, "utf8").catch(() => "");
  if (current !== ts) {
    console.error("src/api/types.gen.ts güncel değil: npm run gen:types çalıştırın");
    process.exit(1);
  }
  console.log("Tipler güncel.");
} else {
  await writeFile(OUT, ts);
  console.log(`Yazıldı: ${OUT.pathname}`);
}
