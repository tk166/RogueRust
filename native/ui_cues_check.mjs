// 闸门 57 `ui-cues`：**表现层契约**（§399，审阅 §6/§7 的垂直切片）。
//
// 纯函数闸门（不需要浏览器）：把"演出怎么从 Beat 变成视觉"这件事钉死。
//
// ## 为什么值得一道闸门
//
// 审阅的核心批评是：`planBeats` 把内核 Beat 的 `def`/`actor`/`flags` 丢了，于是
// "Strike 的斩击"与"Bash 的重击"在数据上一模一样，将来做动画只能靠数值/文案反推原因。
// 这一轮把 `presentation/cues.ts`（Beat → Cue，带 origin）与
// `presentation/registry.ts`（effectKey → 视觉配方）建成**纯函数 + 纯数据**，
// 所以"每一条都能翻、每一 key 都有配方、未知的不静默"可以**穷尽**断言。
//
// ## 六条判据
//
// 1. **穷尽 kind**：内核 13 种 beat kind 每一种都能翻出 Cue，且 `effectKey` 非空；
// 2. **origin 不猜**：`def` 为空 ⇒ `system`；`standard.*` 且是状态类 kind ⇒ `status`；
//    出牌且非 `standard.` ⇒ `card`。其余一律 `system`（不许把伤害猜成某张卡）；
// 3. **逐卡可分**：`strike` 与 `bash` 的 `effectKey` **不同**（这是审阅要的那条），
//    且两者的配方 `motion` 不同；
// 4. **配方回退显式**：未列出的 `card.<id>` 落到 `card.play`（fallback=false）；
//    真正未知的 key 落到兜底并**报 fallback=true**（调用方据此计数，不静默）；
// 5. **冻结锚点**：Cue 带上创建时的 `appearanceId`；`planBeats` 之后 BeatEffect 里仍在；
// 6. **纯函数**：`translate` 不改输入（导演层"演出不改变状态"的延伸）。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GATE = "UI_CUES";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-cues-"));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { kinds: 0, keys: 0, cards: 0 };

try {
  const tscJs = join(WEB_NEXT, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tscJs)) throw new Error(`找不到 ${tscJs}`);
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
      "src/presentation/cues.ts",
      "src/presentation/registry.ts",
      "src/combat/beats.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const cues = await import(pathToFileURL(join(out, "presentation/cues.js")).href);
  const registry = await import(pathToFileURL(join(out, "presentation/registry.js")).href);
  const beats = await import(pathToFileURL(join(out, "combat/beats.js")).href);

  const KINDS = Object.values(cues.CUE_KIND);
  const context = { appearanceOf: (slot) => (slot < 0 ? "hero" : `enemy${slot}`) };
  const beatOf = (kind, extra = {}) => ({
    kind,
    actor: -1,
    target: 0,
    flags: 0,
    a: 6,
    b: 0,
    c: 0,
    def: "",
    ...extra,
  });

  // ── 1. 穷尽 kind ─────────────────────────────────────────────────────────
  const noKey = [];
  for (const kind of KINDS) {
    const cue = cues.translate(beatOf(kind), 0, context);
    if (!cue.effectKey || cue.effectKey.length === 0) noKey.push(kind);
  }
  summary.kinds = KINDS.length;
  check(
    KINDS.length === 13 && noKey.length === 0,
    "内核 13 种 beat kind **每一种**都翻得出 Cue（effectKey 非空）",
    noKey.length === 0 ? `${KINDS.length} 种` : JSON.stringify(noKey)
  );

  // ── 2. origin 不猜 ───────────────────────────────────────────────────────
  const originCases = [
    ["空 def ⇒ system", beatOf(cues.CUE_KIND.damage), "system"],
    ["状态类 kind + standard.* ⇒ status", beatOf(cues.CUE_KIND.statusChanged, { def: "standard.weak" }), "status"],
    ["出牌 + 卡 id ⇒ card", beatOf(cues.CUE_KIND.cardPlayed, { def: "bash" }), "card"],
    // 反证：**伤害**即使带 def 也不许猜成卡（毒/荆棘/遗物都能造成伤害）。
    ["伤害 + 卡 id ⇒ 仍然是 system（不猜）", beatOf(cues.CUE_KIND.damage, { def: "strike" }), "system"],
  ];
  let originBad = [];
  for (const [label, beat, want] of originCases) {
    const got = cues.translate(beat, 0, context).origin.kind;
    if (got !== want) originBad.push(`${label}: ${got}`);
  }
  check(originBad.length === 0, "origin 只写能证明的来源（4 个夹具，含一个反证）", originBad.join(" / ") || "4/4");

  // ── 3. 逐卡可分（审阅 §6 的核心诉求）─────────────────────────────────────
  const strike = cues.translate(beatOf(cues.CUE_KIND.cardPlayed, { def: "strike" }), 0, context);
  const bash = cues.translate(beatOf(cues.CUE_KIND.cardPlayed, { def: "bash" }), 0, context);
  check(
    strike.effectKey === "card.strike" && bash.effectKey === "card.bash",
    "`strike` 与 `bash` 的 effectKey **不同**（不再只能靠数值反推）",
    `${strike.effectKey} vs ${bash.effectKey}`
  );
  const strikeRecipe = registry.recipeFor(strike.effectKey).recipe;
  const bashRecipe = registry.recipeFor(bash.effectKey).recipe;
  check(
    strikeRecipe.motion !== bashRecipe.motion,
    "两者的**视觉配方**也不同（斩击 vs 重击）",
    `${strikeRecipe.motion} vs ${bashRecipe.motion}`
  );
  summary.cards = 2;

  // ── 4. 配方回退显式 ──────────────────────────────────────────────────────
  const known = registry.recipeFor("damage.direct");
  check(known.fallback === false && known.recipe.shake === true, "`damage.direct` 有显式配方且震屏");
  const dot = registry.recipeFor("damage.dot");
  check(
    dot.recipe.shake === false,
    "`damage.dot` **不震屏**（持续伤害没有「被打」的动作，震屏会误导）",
    String(dot.recipe.shake)
  );
  const unknownCard = registry.recipeFor("card.some_new_card");
  check(
    unknownCard.fallback === false && unknownCard.recipe.shape === "card",
    "未列出的卡落到 `card.play` 通用配方（fallback=false，不是兜底灰）",
    JSON.stringify(unknownCard.recipe.shape)
  );
  const trulyUnknown = registry.recipeFor("something.else");
  check(
    trulyUnknown.fallback === true,
    "真正未知的 key ⇒ fallback=true（调用方据此计数，不静默）",
    String(trulyUnknown.fallback)
  );
  // 穷尽：显式配方表里每一条都必须字段完整、颜色是合法 CSS 色。
  const keys = registry.recipeKeys();
  summary.keys = keys.length;
  const badRecipes = keys.filter((key) => {
    const { recipe } = registry.recipeFor(key);
    return (
      typeof recipe.color !== "string" ||
      !/^#[0-9a-fA-F]{6}$/.test(recipe.color) ||
      typeof recipe.duration !== "number" ||
      recipe.duration <= 0 ||
      typeof recipe.shape !== "string" ||
      typeof recipe.motion !== "string"
    );
  });
  check(
    keys.length >= 15 && badRecipes.length === 0,
    "显式配方表**每一条**都字段完整（颜色/时长/形状/motion）",
    badRecipes.length === 0 ? `${keys.length} 条` : JSON.stringify(badRecipes.slice(0, 4))
  );

  // ── 5. 冻结锚点：Cue → BeatEffect 一路都在 ───────────────────────────────
  const cue = cues.translate(beatOf(cues.CUE_KIND.damage, { target: 2 }), 0, context);
  check(
    cue.anchorSlot === 2 && cue.appearanceId === "enemy2",
    "Cue 冻结了锚点（槽位 + 当时的外观 id）",
    JSON.stringify({ slot: cue.anchorSlot, appearance: cue.appearanceId })
  );
  const planned = beats.planBeats(
    [beatOf(cues.CUE_KIND.damage, { target: 2 })],
    0,
    { reducedMotion: false },
    context
  );
  const effect = planned.effects[0];
  check(
    effect?.appearanceId === "enemy2" && effect?.effectKey === "damage.direct",
    "`planBeats` 把 effectKey 与冻结锚点带进 BeatEffect（不再丢因果）",
    JSON.stringify({ key: effect?.effectKey, appearance: effect?.appearanceId })
  );

  // ── 6. 纯函数：不改输入 ──────────────────────────────────────────────────
  const input = beatOf(cues.CUE_KIND.statusChanged, { def: "standard.strength", a: 3 });
  const before = JSON.stringify(input);
  cues.translate(input, 7, context);
  check(JSON.stringify(input) === before, "`translate` 不改输入（演出绝不改变事实）");

  // ── 7. 未知 kind 也产出 Cue（不静默丢掉）─────────────────────────────────
  const weird = cues.translate(beatOf(99), 0, context);
  check(
    weird.effectKey === "unknown.99" && registry.recipeFor(weird.effectKey).fallback === true,
    "未知 kind 也产出一条 Cue，并落到兜底配方（可计数）",
    weird.effectKey
  );
} finally {
  await rm(out, { recursive: true, force: true });
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(`UI_CUES PASS kinds=${summary.kinds} recipes=${summary.keys} cards=${summary.cards}`);
