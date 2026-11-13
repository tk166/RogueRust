// 闸门 45 `ui-assets`：素材流水线的**纯函数**回归（不需要浏览器）。
//
// 这一层守的是"流水线没有洞"，四件事：
//
// 1. **清单覆盖**：内容镜像里的**每一个** id 都在清单里（61 敌 / 295 卡 / 152 遗物 / 33 药水 /
//    150 状态）。清单是生成的，所以"内容加了东西而美术没跟上"会**在生成时**就暴露，而不是
//    等玩家看到一个灰块。
// 2. **字母规则**：两位大写、确定性、升级后缀不改变字母（`strike+` 与 `strike` 同一组）。
//    同时**统计碰撞**（不同 id 撞同一组字母）—— 这一版接受碰撞，但必须**量出来**（下面有数）。
// 3. **原型目录**：清单里引用的每个原型都在 `geometry.ts` 里；每种原型 ≥2 个基本体；
//    只引用已知形状/角色（渲染层只认这几种）。
// 4. **降级被计数**：清单里没有的 id 走 `lettersOf` 现算/确定性原型，并进 `unknownAssets()`。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GATE = "UI_ASSETS";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const ROOT = fileURLToPath(new URL("../", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-assets-"));

let bad = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) bad += 1;
  return ok;
};
const summary = { enemies: 0, cards: 0, relics: 0, potions: 0, statuses: 0, archetypes: 0, collisions: 0 };

try {
  // ── 1. 编译纯逻辑 ────────────────────────────────────────────────────────
  const tscJs = join(WEB_NEXT, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tscJs)) throw new Error(`找不到 ${tscJs}；先在 web-next 里 npm ci`);
  execFileSync(
    process.execPath,
    [
      tscJs,
      "--target", "es2022",
      "--module", "es2022",
      "--moduleResolution", "bundler",
      "--skipLibCheck",
      "--rootDir", "src",
      "--outDir", out,
      "src/assets/registry.ts",
      "src/assets/geometry.ts",
      "src/assets/manifest.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const registry = await import(pathToFileURL(join(out, "assets/registry.js")).href);
  const geometry = await import(pathToFileURL(join(out, "assets/geometry.js")).href);
  const manifest = await import(pathToFileURL(join(out, "assets/manifest.js")).href);

  // ── 2a. 清单自洽：`ASSET_COUNTS` 必须等于实际条目数 ────────────────────────
  //
  // ⚠️ 这里**不**调 `python native/build_assets.py --check`：验收链的 PATH 是剥空的，
  // 子进程找不到 `python`（第一次跑闸门 45 就是这么在验收里红的，而单独跑却是绿的）。
  // "生成器有没有跑过"由下面 2b 的**逐个 id 对账**保证 —— 内容变了而清单没重跑，id 就会对不上。
  const countsMatch =
    manifest.ASSET_COUNTS.enemies === Object.keys(manifest.ENEMY_ASSETS).length &&
    manifest.ASSET_COUNTS.cards === Object.keys(manifest.BADGE_ASSETS.cards).length &&
    manifest.ASSET_COUNTS.relics === Object.keys(manifest.BADGE_ASSETS.relics).length &&
    manifest.ASSET_COUNTS.potions === Object.keys(manifest.BADGE_ASSETS.potions).length &&
    manifest.ASSET_COUNTS.statuses === Object.keys(manifest.BADGE_ASSETS.statuses).length;
  check(countsMatch, "清单自洽：ASSET_COUNTS 等于实际条目数", JSON.stringify(manifest.ASSET_COUNTS));

  // ── 2. 清单覆盖：与内容镜像逐个对账（不是只看条数）─────────────────────
  const content = JSON.parse(
    await readFile(join(ROOT, "tools", "contentc", "packages", "sts", "sts.roguedeck.json"), "utf8")
  );
  const idsOf = (key) => (content[key] ?? []).map((row) => row.Id).filter(Boolean);
  const compare = (label, wanted, actual) => {
    const missing = wanted.filter((id) => !(id in actual));
    const extra = Object.keys(actual).filter((id) => !wanted.includes(id));
    check(
      missing.length === 0 && extra.length === 0,
      `${label}：清单与内容**逐个**一致（${wanted.length} 条）`,
      missing.length || extra.length ? `缺 ${missing.slice(0, 3)} 多 ${extra.slice(0, 3)}` : ""
    );
    return wanted.length;
  };
  summary.enemies = compare("敌人", idsOf("Monsters"), manifest.ENEMY_ASSETS);
  summary.cards = compare("卡牌", idsOf("Cards"), manifest.BADGE_ASSETS.cards);
  summary.relics = compare("遗物", idsOf("Relics"), manifest.BADGE_ASSETS.relics);
  summary.potions = compare("药水", idsOf("Potions"), manifest.BADGE_ASSETS.potions);
  summary.statuses = compare("状态", idsOf("Statuses"), manifest.BADGE_ASSETS.statuses);

  // ── 3. 字母规则（两位大写 / 确定性 / 升级不改字母）──────────────────────
  const lettersOf = registry.lettersOf;
  check(lettersOf("twin_strike") === "TS", "字母：twin_strike → TS", lettersOf("twin_strike"));
  check(lettersOf("strike") === "ST", "字母：单词取前两位（strike → ST）", lettersOf("strike"));
  check(lettersOf("strike+") === "ST", "字母：升级后缀不改变字母（strike+ → ST）", lettersOf("strike+"));
  check(lettersOf("standard.vulnerable") === "SV", "字母：点分词（standard.vulnerable → SV）", lettersOf("standard.vulnerable"));
  check(lettersOf("a") === "AX", "字母：不足两位用 X 补齐（a → AX）", lettersOf("a"));
  check(lettersOf("") === "XX", "字母：空 id 也给两位（XX）", lettersOf(""));
  let allUpper = true;
  let allTwo = true;
  for (const kind of ["cards", "relics", "potions", "statuses"]) {
    for (const [id, asset] of Object.entries(manifest.BADGE_ASSETS[kind])) {
      if (!/^[A-Z]{2}$/.test(asset.letters)) allTwo = false;
      if (asset.letters !== asset.letters.toUpperCase()) allUpper = false;
      if (asset.letters !== lettersOf(id)) allTwo = false;
    }
  }
  check(allTwo, "清单里每一组字母都恰好两位、且等于规则算出来的", "逐条比对");
  check(allUpper, "清单里每一组字母都是大写");

  // 碰撞：这一版**接受**碰撞，但必须量出来（将来换成图标时它就该是 0）。
  const buckets = new Map();
  for (const [id, asset] of Object.entries(manifest.BADGE_ASSETS.cards)) {
    const key = asset.letters;
    buckets.set(key, (buckets.get(key) ?? 0) + 1);
  }
  summary.collisions = Array.from(buckets.values()).filter((count) => count > 1).length;
  check(
    summary.collisions <= 200,
    "卡牌字母碰撞数在预算内（这一版接受碰撞，但要有数）",
    `${summary.collisions} 组撞车 / ${buckets.size} 组`
  );

  // ── 4. 原型目录：清单引用的原型都存在、且每种 ≥2 个基本体 ────────────────
  const archetypes = manifest.ARCHETYPES;
  summary.archetypes = archetypes.length;
  check(archetypes.length >= 12, "原型数量 >= 12（这一版是 16）", String(archetypes.length));
  const missingArchetype = archetypes.filter((name) => !geometry.FIGURES[name]);
  check(missingArchetype.length === 0, "清单里的每个原型都在 geometry.ts 里", JSON.stringify(missingArchetype));
  const usedBy = new Map();
  for (const [id, asset] of Object.entries(manifest.ENEMY_ASSETS)) {
    usedBy.set(asset.archetype, (usedBy.get(asset.archetype) ?? 0) + 1);
    if (!geometry.FIGURES[asset.archetype]) check(false, `敌人 ${id} 引用了不存在的原型 ${asset.archetype}`);
  }
  check(usedBy.size === archetypes.length, "16 个原型**都被用到**（没有死目录）", `${usedBy.size}/${archetypes.length}`);

  let thin = [];
  let unknownShape = [];
  let unknownRole = [];
  for (const [name, figure] of Object.entries(geometry.FIGURES)) {
    if (figure.parts.length < 2) thin.push(name);
    for (const part of figure.parts) {
      if (!geometry.SHAPES.includes(part.shape)) unknownShape.push(`${name}:${part.shape}`);
      if (!geometry.ROLES.includes(part.role)) unknownRole.push(`${name}:${part.role}`);
      if (part.size.some((value) => !(value > 0))) unknownShape.push(`${name}:size`);
    }
  }
  check(thin.length === 0, "每种原型至少 2 个基本体（1 个基本体不算排列组合）", JSON.stringify(thin));
  check(unknownShape.length === 0, "只引用已知形状（渲染层只认这几种）", JSON.stringify(unknownShape.slice(0, 4)));
  check(unknownRole.length === 0, "只引用已知角色（body/accent/eye）", JSON.stringify(unknownRole.slice(0, 4)));

  // ── 5. 确定性 + 降级计数 ────────────────────────────────────────────────
  registry.resetUnknownAssets();
  const first = registry.enemyLook("cultist");
  const second = registry.enemyLook("cultist");
  check(
    JSON.stringify(first) === JSON.stringify(second),
    "同一 id 两次解析结果完全相同（确定性）"
  );
  check(first.fallback === false, "清单里的敌人不走降级", String(first.fallback));
  const ghost = registry.enemyLook("not_a_real_enemy");
  check(ghost.fallback === true, "清单外的敌人走降级（fallback=true）");
  check(ghost.figure.parts.length >= 2, "降级也有东西可画（不是空 figure）");
  check(
    registry.unknownAssets().some((key) => key.includes("not_a_real_enemy")),
    "降级被计数（静默降级 = 假装有素材）",
    JSON.stringify(registry.unknownAssets())
  );
  registry.resetUnknownAssets();
  check(registry.unknownAssets().length === 0, "reset 之后计数清零");

  // 清单里的每个敌人都能解析出 figure（渲染层不会拿到 undefined）。
  const broken = Object.keys(manifest.ENEMY_ASSETS).filter((id) => {
    const look = registry.enemyLook(id);
    return !look.figure || look.figure.parts.length === 0;
  });
  check(broken.length === 0, "清单里 61 个敌人都能解析出可画的 figure", JSON.stringify(broken.slice(0, 4)));
} finally {
  await rm(out, { recursive: true, force: true });
}

console.log("");
if (bad > 0) {
  console.error(`${GATE} FAIL: ${bad} 条`);
  process.exit(1);
}
console.log(
  `UI_ASSETS PASS enemies=${summary.enemies} cards=${summary.cards} relics=${summary.relics} ` +
    `potions=${summary.potions} statuses=${summary.statuses} archetypes=${summary.archetypes} ` +
    `collisions=${summary.collisions}`
);
