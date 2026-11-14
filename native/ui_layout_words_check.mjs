// 闸门 56 `ui-layout-words`：**布局宽度**与**词表**这两类"看起来没坏、其实在骗人"的错。
//
// 玩家第二轮实机报的四条，分两组：
//
// ## ① 布局（像素）
//
// * 地图宽度塌了（节点互相压住）；
// * 奖励屏的悬浮窗宽度不固定，卡牌在"一列/两列"之间来回跳。
//
// 根因是同一个：`.scene` 的 `margin: 0 auto` 让 flex item 失去 stretch，宽度退回 **fit-content**；
// 而悬浮面板是 `sticky`（**在流内**）⇒ 它一出现就改变容器宽度 ⇒ 卡牌重排 ⇒ 鼠标下的牌换位置
// ⇒ hover 换目标 ⇒ 面板换文字 ⇒ 死循环抖动。
//
// 判据：**同一屏在"没有面板 / 指着 A / 指着 B"三种状态下，场景宽度、面板宽度、卡牌行数都不许变**。
// 这条断言正好是"抖动"的定义，而且它是**自比**（不依赖某个具体像素值）。
//
// ## ② 词表（语义）
//
// * `观察弱点`（`spot_weakness`）不选敌人就结算了；
// * 事件「翅膀雕像」的 `[祈祷]` 选项显示"未知效果 6（0）"。
//
// 判据：
// * `cardMeta` 里**每一张**提到事件目标（`sel.eventTarget` / `intent.target*`）的牌都必须被标成
//   `singleEnemy` —— 穷尽遍历 295 张，不是抽查；
// * `effectLabel` 对内核闭集 1..16 **每一条**都给出人话，且 `-1`（没有效果码）返回**空串**
//   而不是"未知效果"。同样遍历，不抽查。
//
// 两条语义断言都是**纯函数**（编译 `cardMeta.ts` / `models.ts` 直接跑），不需要浏览器。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_LAYOUT_WORDS";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const REPO = fileURLToPath(new URL("..", import.meta.url));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { cards: 0, effects: 0, widths: 0, rows: 0 };

// ── ② 词表：纯函数部分 ─────────────────────────────────────────────────────
const out = await mkdtemp(join(tmpdir(), "rd-words-"));
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
      "src/run/models.ts",
      "src/view/cardMeta.ts",
      // §381 的落点断言要直接跑 `viewFromWasm`（"定向牌必须给每个敌人一个落点"），
      // 而不是靠在浏览器里抽到那张牌 —— Uncommon 起手抽不到，靠运气就是在写假闸门。
      "src/view/combatView.ts",
      // §384：选牌弹窗的标签（`武装`/`头击` 要选一张手牌时那一屏）。
      "src/view/choiceText.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const meta = (await import(pathToFileURL(join(out, "view/cardMeta.js")).href)).default;
  const models = await import(pathToFileURL(join(out, "run/models.js")).href);
  const view = await import(pathToFileURL(join(out, "view/combatView.js")).href);
  const choiceText = await import(pathToFileURL(join(out, "view/choiceText.js")).href);

  // ── 定向牌：内容里提到事件目标的牌，一张都不许漏 ────────────────────────
  const content = JSON.parse(
    await readFile(join(REPO, "tools/contentc/packages/sts/sts.roguedeck.json"), "utf8")
  );
  const needsTarget = [];
  for (const card of content.Cards ?? []) {
    const program =
      JSON.stringify(card.Program ?? null) + JSON.stringify(card.LifecyclePrograms ?? null);
    if (program.includes("sel.eventTarget") || program.includes("intent.target")) {
      needsTarget.push(card.Id);
    }
  }
  const missed = needsTarget.filter((id) => meta[id]?.targeting !== "singleEnemy");
  check(
    missed.length === 0,
    "每一张**提到事件目标**的牌都被标成定向（穷尽 295 张）",
    missed.length === 0 ? `${needsTarget.length} 张定向牌` : JSON.stringify(missed)
  );
  // 反证：`观察弱点` 必须是定向的（玩家报的那一张，单独钉住它）。
  check(
    meta.spot_weakness?.targeting === "singleEnemy" &&
      meta["spot_weakness+"]?.targeting === "singleEnemy",
    "`观察弱点`（含 `+`）被标成**定向**（不选敌人不该结算）",
    JSON.stringify({ base: meta.spot_weakness?.targeting, plus: meta["spot_weakness+"]?.targeting })
  );
  summary.cards = needsTarget.length;

  // ── §388：状态表必须覆盖内容里**每一条** status（穷尽）────────────────────
  //
  // 玩家报的："一些状态依旧显示英文例如 orichalcum 和 incense_burner"。
  // 那两条是**遗物挂的状态**（`StartCombatStatus`），旧的 13 条小表里没有 ⇒ 屏幕上就是英文 id。
  const zhSource = await readFile(join(REPO, "web-next/src/i18n/zh.ts"), "utf8");
  const statusesBlock = /"statuses": (\{[\s\S]*?\n \}),\n/.exec(zhSource);
  check(statusesBlock !== null, "`zh.ts` 里有 statuses 表");
  const statusKeys = new Set(
    [...(statusesBlock ? statusesBlock[1] : "").matchAll(/"([^"]+)": \{/g)].map((m) => m[1])
  );
  const missingStatus = [];
  for (const status of content.Statuses ?? []) {
    if (!statusKeys.has(status.Id)) missingStatus.push(status.Id);
  }
  check(
    missingStatus.length === 0,
    "内容里**每一条**状态都有中文名（穷尽 150 条）",
    missingStatus.length === 0 ? `${statusKeys.size} 条` : JSON.stringify(missingStatus.slice(0, 6))
  );
  // 玩家点名的两条，单独钉住（回归时最想知道的就是它们）。
  for (const id of ["standard.orichalcum", "standard.incense_burner"]) {
    const row = new RegExp(`"${id.replace(/[.]/g, "\\.")}": \\{\\s*"name": "([^"]+)"`).exec(zhSource);
    check(
      row !== null && /[\u4e00-\u9fa5]/.test(row[1]),
      `\`${id}\` 有中文名（玩家点名的那两条之一）`,
      row ? row[1] : "缺"
    );
  }

  // ── 落点：定向牌必须**每个敌人一个落点**，无目标牌才归并成一个 ──────────
  //
  // 玩家报的"没有选择敌人就直接触发了"在视图层长这样：`optionsFor` 把内核给的
  // "牌 × 每个活敌人"的多条动作**归并成一个** `slot: -1`。归并只对 `targeting === "none"`
  // 合法 —— 对定向牌归并，玩家就永远没有机会选目标。
  const snapshot = {
    round: 1,
    turn: 1,
    phase: "waiting",
    result: "ongoing",
    hero: { hp: 80, hpMax: 80, block: 0, energy: 3, energyMax: 3, statuses: {} },
    enemies: [
      { slot: 0, alive: true, hp: 20, hpMax: 20, block: 0, intentKind: 1, intentDamage: 6, statuses: {} },
      { slot: 1, alive: true, hp: 20, hpMax: 20, block: 0, intentKind: 1, intentDamage: 6, statuses: {} },
    ],
    hand: [{ slot: 0, cost: 1, defSlot: 0, upgraded: false }],
    handCount: 1,
    piles: { draw: 0, hand: 1, discard: 0, exhaust: 0, queue: 0 },
    actions: [
      { index: 0, kind: "play", handSlot: 0, targetSlot: 0 },
      { index: 1, kind: "play", handSlot: 0, targetSlot: 1 },
      { index: 2, kind: "endTurn", handSlot: -1, targetSlot: -1 },
    ],
  };
  const namesFor = (cardId) => ({
    cardName: () => cardId,
    cardText: () => "",
    enemyName: (slot) => (slot === 0 ? "cultist" : "jaw_worm"),
    statuses: () => [],
  });
  const spot = view.viewFromWasm(snapshot, namesFor("spot_weakness"), 1);
  const spotOptions = spot.optionsFor(0);
  check(
    spotOptions.length === 2 && spotOptions.every((option) => option.slot >= 0),
    "`观察弱点` 的落点是**每个敌人一个**（不是归并成一个无目标出牌）",
    JSON.stringify(spotOptions.map((option) => option.slot))
  );
  // 反证：`防御`（无目标）仍然归并成一个 `slot: -1` —— 否则就是"所有牌都变定向"。
  const defend = view.viewFromWasm(snapshot, namesFor("defend"), 1);
  const defendOptions = defend.optionsFor(0);
  check(
    defendOptions.length === 1 && defendOptions[0].slot === -1,
    "`防御`（无目标）仍然归并成一个 `slot: -1` 的落点",
    JSON.stringify(defendOptions.map((option) => option.slot))
  );

  // ── 效果词表：内核闭集 1..16 每一条都要有人话 ───────────────────────────
  const codes = [
    [1, "heal"], [2, "gold"], [3, "damage"], [4, "max_hp"], [5, "nothing"],
    [6, "remove_card"], [7, "upgrade_card"], [8, "transform_card"],
    [9, "curse"], [10, "relic"], [11, "damage_pct"], [12, "max_hp_pct"],
    [13, "gold_cost"], [14, "heal_pct"], [15, "heal_full"], [16, "gold_random"],
  ];
  const unknown = [];
  for (const [code, atom] of codes) {
    const label = models.effectLabel(code, 100);
    if (!label || label.startsWith("未知效果")) unknown.push(`${code}(${atom}) → ${label}`);
  }
  check(
    unknown.length === 0,
    "内核的效果闭集 1..16 **每一条**都有人话（不是抽查）",
    unknown.length === 0 ? `${codes.length} 条` : JSON.stringify(unknown)
  );
  summary.effects = codes.length;

  // ── §384：选牌弹窗的一行必须是**中文名**（不是内核的英文 NameKey）─────────
  //
  // 玩家报的："武装 / 头击 要选一张手牌时，弹窗显示的是牌的英文名"。
  // 穷尽遍历内容里的每一张牌：`choiceOptionLabel` 给的 `name` 不许等于英文 `NameKey`。
  // 判据分两层：
  //   a. **一张都不许显示英文 NameKey**（这是玩家报的那件事）；
  //   b. 没翻译的牌只能落在**显式白名单**里（14 张观者/特殊牌，本移植拿不到），
  //      它们显示的是"美化 id"（`patient_guard` → `patient guard`）而不是机器码。
  //      ⇒ 新增一张没翻译的牌会让这条红（而不是静默变回英文名）。
  const UNTRANSLATED = [
    "patient_guard", "insight", "miracle", "omega", "expunger", "shiv", "smite", "beta",
    // ⚠️ 内容是 `jax` **和** `j.a.x.` 两个 id：前者在表里但名字是英文 `J.A.X.`，
    // 后者根本不在表里 —— 两个都算没翻译。
    "through_violence", "jax", "j.a.x.", "safety", "become_almighty", "live_forever",
    "fame_and_fortune",
  ];
  const untranslated = new Set();
  const noChinese = [];
  const rawIds = [];
  let labelCount = 0;
  for (const card of content.Cards ?? []) {
    const nameKey = String(card.NameKey ?? "");
    const label = choiceText.choiceOptionLabel({ id: card.Id, title: nameKey });
    labelCount += 1;
    const hasChinese = /[一-龥]/.test(label.name);
    if (!hasChinese) {
      untranslated.add(card.Id.replace(/\++$/, ""));
      // 第二层必须是**美化**过的 id（`patient guard`），不许把机器码原样印出来。
      // ⚠️ 只在 id 里**有东西可美化**时判（`omega` 这种单词 id 美化后就是它自己）。
      if (/[_.]/.test(card.Id) && label.name === card.Id) rawIds.push(card.Id);
    }
  }
  // 白名单之外的每一张牌都必须有汉字名（这就是"不再显示英文"的可判定形式）。
  for (const card of content.Cards ?? []) {
    const label = choiceText.choiceOptionLabel({ id: card.Id, title: String(card.NameKey ?? "") });
    if (!/[一-龥]/.test(label.name) && !UNTRANSLATED.includes(card.Id.replace(/\++$/, ""))) {
      noChinese.push(card.Id);
    }
  }
  check(
    noChinese.length === 0,
    "白名单之外**每一张**牌都显示中文名（穷尽遍历内容里每一张牌）",
    noChinese.length === 0 ? `${labelCount} 张` : JSON.stringify(noChinese.slice(0, 5))
  );
  check(
    rawIds.length === 0,
    "没翻译的牌显示**美化 id**（`patient guard`），不是机器码",
    rawIds.length === 0 ? "0 处" : JSON.stringify(rawIds.slice(0, 5))
  );
  const unexpected = [...untranslated].filter((id) => !UNTRANSLATED.includes(id));
  check(
    unexpected.length === 0,
    "没有翻译的牌**只有白名单里那 14 张**（新增一张没翻译的牌会红）",
    unexpected.length === 0 ? `${untranslated.size} 张` : JSON.stringify(unexpected)
  );
  // 反证：玩家报的那两张牌 + 一个升级变体，单独钉住。
  const spotNames = ["headbutt", "armaments", "strike+"].map((id) => ({
    id,
    ...choiceText.choiceOptionLabel({
      id,
      title: (content.Cards ?? []).find((card) => card.Id === id)?.NameKey ?? id,
    }),
  }));
  check(
    spotNames.every((row) => /[一-龥]/.test(row.name)),
    "`头击` / `武装` / `打击+` 的名字里真的有汉字",
    JSON.stringify(spotNames.map((row) => `${row.id}→${row.name}`))
  );
  // ── 接线：组件必须**用**这个纯函数（纯函数测了但没人调，等于没修）──────────
  const modalSource = await readFile(join(REPO, "web-next/src/overlay/ChoiceModal.tsx"), "utf8");
  check(
    /choiceOptionLabel\s*\(/.test(modalSource),
    "`ChoiceModal` 真的调了 `choiceOptionLabel`（不是只把它写着好看）"
  );
  check(
    !/\{option\.title \|\| option\.id\}/.test(modalSource),
    "`ChoiceModal` 不再直接把内核的英文 `option.title` 印出来"
  );
  check(
    /badgeLook\("cards"/.test(modalSource) && /<CardTip/.test(modalSource),
    "`ChoiceModal` 有二维卡面（`badgeLook`）与悬浮详情（`<CardTip>`）"
  );

  check(
    spotNames.every((row) => /费|不可打出/.test(row.subtitle)),
    "选牌弹窗的副标题带**费用**（与商店/奖励的悬浮面板同一个来源）",
    JSON.stringify(spotNames.map((row) => row.subtitle))
  );

  // `-1` = "没有效果码"：**空串**，不是"未知效果 -1（0）"。
  check(
    models.effectLabel(-1, 0) === "",
    "`-1`（没有效果码）返回空串 —— 不许画成“未知效果”",
    JSON.stringify(models.effectLabel(-1, 0))
  );
  check(
    models.effectSummary([{ kind: -1, amount: 0 }]) === "",
    "全是 `-1` 的选项 ⇒ 摘要为空（调用方不画那一行）",
    JSON.stringify(models.effectSummary([{ kind: -1, amount: 0 }]))
  );
  // 反证：真的未知码仍然要**响亮**（把"未知"和"没有码"混成一件事的另一种错法）。
  check(
    models.effectLabel(99, 7).startsWith("未知效果"),
    "真的未知码仍然响亮（`未知效果 99`）",
    models.effectLabel(99, 7)
  );
  // 事件「翅膀雕像」的 [祈祷] 就是 `remove_card`(6)：它必须有一句人话。
  check(
    models.effectLabel(6, 0).includes("移除"),
    "`remove_card`(6) 有人话（玩家报的「翅膀雕像 · 祈祷」）",
    models.effectLabel(6, 0)
  );
} finally {
  await rm(out, { recursive: true, force: true });
}

// ── ① 布局：像素部分 ───────────────────────────────────────────────────────
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "",
  gate: GATE,
  viewport: { width: 1280, height: 900 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

await ev('window.__run.click("[data-start]")');
await sleep(250);
const blessings = await ev("window.__run.blessings()");
// ⚠️ 优先挑**需要选牌**的祝福：那样牌组选择器（§390 的被测对象）一定会开，
// 而不是"看运气抽到哪个祝福"。抽不到才退回不需要选牌的那个。
const needsCard = blessings.find((row) => row.needs > 0);
const simple = needsCard ?? blessings.find((row) => row.needs === 0) ?? blessings[0];
await ev(`window.__run.click("[data-blessing='${simple.slot}']")`);
await sleep(300);

// ── §390：牌组选择器（祝福选牌那条路一开局就能开）────────────────────────
{
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-01b") {
    const rows = await ev(`(() => {
      const list = document.querySelector("[data-deck-count]");
      if (!list) return null;
      return Array.from(list.querySelectorAll("[data-deck-pick]")).slice(0, 6).map((row) => ({
        id: row.dataset.deckPickId,
        name: row.querySelector(".deck-select-name")?.textContent.trim() ?? "",
        badges: row.querySelectorAll("[data-asset-badge]").length,
        width: Math.round(row.getBoundingClientRect().width * 10) / 10,
      }));
    })()`);
    check(rows !== null && rows.length > 0, "牌组选择器有行", JSON.stringify(rows?.length));
    check(
      rows !== null && rows.every((row) => row.badges > 0),
      "每一行都有**二维卡面**（§390）",
      JSON.stringify(rows?.map((row) => row.badges))
    );
    check(
      rows !== null && rows.every((row) => /[\u4e00-\u9fa5]/.test(row.name)),
      "每一行都是**中文名**（不是英文 id）",
      JSON.stringify(rows?.map((row) => row.name))
    );
    const widths = rows?.map((row) => row.width) ?? [];
    check(
      widths.length > 0 && new Set(widths).size === 1,
      "每一行**等宽**（玩家报的参差）",
      JSON.stringify(widths)
    );
    // 指着某一行 ⇒ 同一个面板给出"种类 · 费用 · 稀有度"。
    const point = await ev(`(() => {
      const el = document.querySelector("[data-deck-pick]");
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    if (point) {
      await page.send("Input.dispatchMouseEvent", {
        type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0,
      });
      await sleep(150);
      const sub = await ev(
        `document.querySelector("[data-card-tip] [data-tip-subtitle-text]")?.textContent.trim() ?? ""`
      );
      check(/费|不可打出/.test(sub), "牌组选择器的详情带**费用**", sub);
    }
    // 断言完就把这张牌选掉（后面的流程要在地图上）。
    await ev(`(() => {
      const node = document.querySelector("[data-deck-pick][data-deck-allowed='1']");
      if (node) node.click();
    })()`);
    await sleep(300);
  } else {
    check(true, `这一局没有祝福选牌（${scene.base}），牌组选择器部分跳过`);
  }
}


// 地图：场景宽度必须接近上限（560），节点之间不许互相压住。
const mapBox = await ev(`(() => {
  const scene = document.querySelector(".scene-map");
  const nodes = Array.from(document.querySelectorAll("[data-node]")).map((n) => {
    const r = n.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, row: Number(n.closest("[data-row]")?.dataset.row ?? -1) };
  });
  return { sceneW: Math.round(scene.getBoundingClientRect().width), nodes };
})()`);
check(
  mapBox.sceneW >= 540,
  "地图场景宽度接近上限（≥540px）—— 不再塌成文字宽度",
  `${mapBox.sceneW}px`
);
// 同一行内相邻节点不许重叠（玩家看到的是"节点压在一起"）。
const byRow = new Map();
for (const node of mapBox.nodes) {
  const list = byRow.get(node.row) ?? [];
  list.push(node);
  byRow.set(node.row, list);
}
let overlaps = [];
for (const [row, list] of byRow) {
  list.sort((a, b) => a.left - b.left);
  for (let i = 1; i < list.length; i += 1) {
    if (list[i].left < list[i - 1].right - 0.5) {
      overlaps.push(`row ${row}: ${Math.round(list[i - 1].right - list[i].left)}px 重叠`);
    }
  }
}
check(overlaps.length === 0, "同一行的节点**互不重叠**", overlaps.slice(0, 2).join(" / ") || "0 处");

// 走到奖励屏（打完一场）。
const map = await ev("window.__run.map()");
const first = map.nodes.find((node) => node.reachable);
await ev(`window.__run.click("[data-node='${first.index}']")`);
await sleep(250);
if ((await ev("window.__run.scene()")).base === "SC-03") {
  await ev('window.__run.click("[data-fight-begin]")');
  await sleep(400);
  // §391：战斗里顶栏 HP 必须跟**战斗快照**（不是运行层那份陈旧值）。
  // 玩家被史莱姆老大砸了 35 点、血条纹丝不动，就是因为读了运行层。
  const pair = await ev(`(() => {
    const hp = document.querySelector("[data-run-hp]")?.dataset.runHp ?? "";
    const combat = window.__run.hand();
    return { topbar: hp, combat: combat ? combat.heroHp : null };
  })()`);
  check(
    pair.combat !== null && pair.topbar.split("/")[0] === String(pair.combat),
    "战斗中顶栏 HP == 战斗快照的 HP（§391）",
    JSON.stringify(pair)
  );
}
for (let steps = 0; steps < 240; steps += 1) {
  const hand = await ev("window.__run.hand()");
  if (!hand || hand.result !== "ongoing") break;
  const play = hand.actions.find((action) => action.kind === "play");
  const result = play
    ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
    : await ev("window.__run.endTurn()");
  if (result?.accepted === false) break;
}
await ev('(() => { const n = document.querySelector("[data-combat-continue]"); if (n) n.click(); })()');
await sleep(300);

const scene = await ev("window.__run.scene()");
if (scene.base === "SC-04") {
  /** 读一次布局指纹（场景宽 / 面板宽 / 卡牌行数）。 */
  const fingerprint = () =>
    ev(`(() => {
      const scene = document.querySelector(".scene");
      const tip = document.querySelector("[data-card-tip]");
      const cards = Array.from(document.querySelectorAll("[data-reward-card]"));
      // ⚠️ 用 offsetTop（**布局位置**），不是 getBoundingClientRect().top：
      // .reward-card:hover 有 transform: translateY(-1px)，用 rect 会把"鼠标下那张高了 1px"
      // 数成"换了一行"（第一版就是这样，报了 [1,2,2,2] 的假红）。
      const rows = new Set(cards.map((c) => c.offsetTop));
      return {
        sceneW: Math.round(scene.getBoundingClientRect().width),
        tipW: tip ? Math.round(tip.getBoundingClientRect().width) : null,
        rows: rows.size,
        cards: cards.length,
      };
    })()`);

  // 先把鼠标放到角落（没有面板），再依次指三张牌。
  await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 4, y: 4, button: "none", buttons: 0 });
  await sleep(100);
  const idle = await fingerprint();
  const samples = [idle];
  for (const slot of [0, 1, 2]) {
    const point = await ev(`(() => {
      const el = document.querySelector("[data-reward-card='${slot}']");
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    })()`);
    if (!point) continue;
    await page.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y, button: "none", buttons: 0 });
    await sleep(140);
    samples.push(await fingerprint());
  }

  const widths = samples.map((sample) => sample.sceneW);
  const tipWidths = samples.filter((sample) => sample.tipW !== null).map((sample) => sample.tipW);
  const rowCounts = samples.map((sample) => sample.rows);
  summary.widths = new Set(widths).size;
  summary.rows = new Set(rowCounts).size;
  check(
    new Set(widths).size === 1,
    "奖励屏的**场景宽度**在“无面板 / 指第 1 张 / 第 2 张 / 第 3 张”下完全不变",
    JSON.stringify(widths)
  );
  check(
    new Set(tipWidths).size === 1 && tipWidths.length > 0,
    "悬浮面板宽度不随内容变（否则会把容器宽度顶来顶去）",
    JSON.stringify(tipWidths)
  );
  check(
    new Set(rowCounts).size === 1,
    "卡牌**行数**不来回跳（一列/两列抖动）",
    JSON.stringify(rowCounts)
  );
} else {
  check(true, `没走到奖励屏（${scene.base}），布局稳定性部分跳过`);
}

// ── §389：遗物条上的 chip 指着要出详情 ─────────────────────────────────────
{
  const chipPoint = await ev(`(() => {
    const el = document.querySelector("[data-relic-id]");
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, id: el.dataset.relicId };
  })()`);
  check(chipPoint !== null, "遗物条上有 chip 可指", chipPoint?.id);
  if (chipPoint) {
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: chipPoint.x, y: chipPoint.y, button: "none", buttons: 0,
    });
    await sleep(150);
    const tip = await ev(`(() => {
      const node = document.querySelector("[data-card-tip]");
      if (!node) return null;
      return {
        kind: node.dataset.tipKind,
        title: node.querySelector("[data-tip-title-text]")?.textContent.trim() ?? "",
      };
    })()`);
    check(tip !== null, "指着遗物 ⇒ 出现详情面板（§389 的唯一面板）");
    check(tip !== null && tip.kind === "relic", "面板说的是**遗物**", tip?.kind);
    check(
      tip !== null && /[\u4e00-\u9fa5]/.test(tip.title),
      "遗物详情标题是中文名",
      tip?.title
    );
  }
}

// ── §391：战斗中顶栏 HP 必须跟战斗快照 ───────────────────────────────────
{
  const scene = await ev("window.__run.scene()");
  if (scene.base === "SC-03b") {
    const pair = await ev(`(() => {
      const hp = document.querySelector("[data-run-hp]")?.dataset.runHp ?? "";
      const combat = window.__run.hand();
      return { topbar: hp, combat: combat ? combat.heroHp : null };
    })()`);
    check(
      pair.combat !== null && pair.topbar.split("/")[0] === String(pair.combat),
      "战斗中顶栏 HP == 战斗快照的 HP（不是运行层那份陈旧值）",
      JSON.stringify(pair)
    );
  } else {
    check(true, `现在不在战斗里（${scene.base}），顶栏 HP 部分跳过`);
  }
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_LAYOUT_WORDS PASS cards=${summary.cards} effects=${summary.effects} ` +
    `scene-widths=${summary.widths} row-counts=${summary.rows}`
);
