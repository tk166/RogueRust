// 闸门 35 `ui-p4-models`：P4 的**纯展示逻辑**回归（不需要浏览器）。
//
// 这一层是"内核给一个数字，界面要变成一句话/一个按钮"的映射 —— 最容易与内核漂的地方
// （同一个词表两处认识）。所以这里把每个判别值**逐个**钉住：
//
//   * 篝火位掩码：6 个位各一次、组合、以及"UI 不认识的位"必须被报出来；
//   * 效果判别值：5 个已知 + 未知（`nothing` 是 5，**不是** 0 —— 拿 0 判"无"会把未知吞掉）；
//   * 商店：`-1` 已售、买得起/买不起的边界（价格 == 金币时买得起）；
//   * 删卡服务：`removalAvailable` 三种取值；
//   * 牌组选择器：锻造只能选**没升级**的牌；过滤不改变下标；
//   * 药水：四种用法 + "战斗外只能用 run-only 的"。
//
// 编译方式与闸门 27/33 一致：用跑本脚本的 node 执行 typescript 的 tsc.js，**不依赖 PATH**。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GATE = "UI_P4_MODELS";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-p4models-"));

let bad = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) bad += 1;
  return ok;
};

try {
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
      "src/run/models.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const m = await import(pathToFileURL(join(out, "run/models.js")).href);

  // ── 1. 篝火位掩码（`§259`：位序是硬约定）────────────────────────────────
  check(m.CAMPFIRE.rest === 1, "位序：Rest = 1");
  check(m.CAMPFIRE.smith === 2, "位序：Smith = 2");
  check(m.CAMPFIRE.recall === 4, "位序：Recall = 4");
  check(m.CAMPFIRE.lift === 8, "位序：Lift = 8");
  check(m.CAMPFIRE.toke === 16, "位序：Toke = 16");
  check(m.CAMPFIRE.dig === 32, "位序：Dig = 32");

  check(m.campfireOptionsFromMask(0).length === 0, "掩码 0 ⇒ 没有选项");
  check(m.campfireOptionsFromMask(1).map((o) => o.id).join(",") === "rest", "掩码 1 ⇒ 只有休息");
  check(
    m.campfireOptionsFromMask(63).map((o) => o.id).join(",") === "rest,smith,recall,lift,toke,dig",
    "掩码 63 ⇒ 六项，且按**位序**",
    JSON.stringify(m.campfireOptionsFromMask(63).map((o) => o.id))
  );
  check(m.campfireOptionsFromMask(3).length === 2, "掩码 3 ⇒ 两项（休息+锻造）");
  const needsDeck = m.campfireOptionsFromMask(63).filter((o) => o.needsDeck).map((o) => o.id);
  check(
    JSON.stringify(needsDeck) === JSON.stringify(["smith", "toke"]),
    "只有锻造/抽烟斗需要先选牌",
    JSON.stringify(needsDeck)
  );
  check(m.unknownCampfireBits(63) === 0, "掩码 63 没有未知位");
  check(m.unknownCampfireBits(64) === 64, "掩码 64（第 7 位）被报成未知", String(m.unknownCampfireBits(64)));
  check(m.unknownCampfireBits(1 | 128) === 128, "认识的位不算未知", String(m.unknownCampfireBits(1 | 128)));

  // ── 2. 效果判别值（与祝福同一套编码）────────────────────────────────────
  check(m.EFFECT.nothing === 5, "`nothing` 是 5（不是 0）");
  check(m.effectLabel(1, 7) === "回复 7 点生命", "1 = 回血", m.effectLabel(1, 7));
  check(m.effectLabel(2, 20) === "获得 20 金币", "2 = 金币", m.effectLabel(2, 20));
  check(m.effectLabel(3, 5) === "失去 5 点生命", "3 = 失去生命", m.effectLabel(3, 5));
  check(m.effectLabel(4, 8) === "生命上限 +8", "4 = 上限", m.effectLabel(4, 8));
  check(m.effectLabel(5, 0) === "无", "5 = 无", m.effectLabel(5, 0));
  check(m.effectLabel(9, 3).includes("未知"), "未知判别值不被显示成无", m.effectLabel(9, 3));
  check(m.effectLabel(0, 3).includes("未知"), "0 也不被当成无", m.effectLabel(0, 3));
  check(
    m.effectSummary([{ kind: 1, amount: 7 }, { kind: 2, amount: 20 }]) === "回复 7 点生命 · 获得 20 金币",
    "多条效果用 · 连起来",
    m.effectSummary([{ kind: 1, amount: 7 }, { kind: 2, amount: 20 }])
  );
  check(m.effectSummary([]) === "无", "空效果表显示无");

  // ── 3. 商店（价格只来自内核）────────────────────────────────────────────
  const rows = m.shelfRows(
    [
      { slot: 0, id: "strike", price: 50 },
      { slot: 1, id: "bash", price: -1 },
      { slot: 2, id: "defend", price: 100 },
      { slot: 3, id: "cleave", price: 0 },
    ],
    50
  );
  check(rows.length === 4, "四行都保留（已售的也保留位置）", String(rows.length));
  check(rows[0].forSale === true && rows[0].affordable === true, "价格 == 金币 ⇒ 买得起（边界）");
  check(rows[1].forSale === false, "价格 -1 ⇒ 已售", JSON.stringify(rows[1]));
  check(rows[1].affordable === false, "已售的不可买");
  check(rows[2].affordable === false, "价格 > 金币 ⇒ 买不起", String(rows[2].affordable));
  check(rows[3].forSale === true && rows[3].affordable === true, "价格 0 ⇒ 还在卖且买得起");

  check(m.removalUsable(1, 75, 100) === true, "删卡服务：可用 + 钱够 ⇒ 能点");
  check(m.removalUsable(1, 75, 50) === false, "删卡服务：钱不够 ⇒ 不能点");
  check(m.removalUsable(0, 75, 100) === false, "删卡服务：这家店用过了（0）⇒ 不能点");
  check(m.removalUsable(-1, 75, 100) === false, "删卡服务：没有局（-1）⇒ 不能点");

  // ── 4. 牌组选择器 ───────────────────────────────────────────────────────
  check(m.deckPickAllowed("smith", "strike") === true, "锻造：没升级的牌可选");
  check(m.deckPickAllowed("smith", "strike+") === false, "锻造：升级过的牌不可选");
  check(m.deckPickAllowed("remove", "strike+") === true, "删牌：升级过的牌也能删");
  check(m.deckPickAllowed("toke", "strike+") === true, "抽烟斗：升级过的牌也能删");
  const copyRemove = m.deckPickCopy("remove", 75);
  check(copyRemove.title.includes("删") && copyRemove.hint.includes("75"), "删牌标题里带价格", JSON.stringify(copyRemove));
  check(copyRemove.actionable === true, "删牌是可执行的选择");
  check(m.deckPickCopy("browse").actionable === false, "浏览模式不可执行");
  check(m.deckPickCopy("smith").title.includes("升级"), "锻造标题说清做什么", m.deckPickCopy("smith").title);

  // ── 5. 药水 ─────────────────────────────────────────────────────────────
  check(m.potionTargeting(1) === "enemy", "1 ⇒ 要敌人目标");
  check(m.potionTargeting(2) === "self", "2 ⇒ 自己/本局");
  check(m.potionTargeting(3) === "all", "3 ⇒ 全体");
  check(m.potionTargeting(0) === "unknown", "0 ⇒ 未知");
  check(m.potionUsable(0, false) === true, "run-only 的药水：战斗外能喝");
  check(m.potionUsable(1, false) === false, "需要战斗的药水：战斗外不能喝");
  check(m.potionUsable(1, true) === true, "需要战斗的药水：战斗内能喝");
  check(m.potionUsable(-1, true) === false, "没有这个槽 ⇒ 不能喝");
} finally {
  await rm(out, { recursive: true, force: true });
}

console.log("");
if (bad > 0) {
  console.error(`${GATE} FAIL: ${bad} 条`);
  process.exit(1);
}
console.log("UI_P4_MODELS PASS campfire=6 effects=5 shelves=4 picker=3 potions=4");
