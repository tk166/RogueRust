// 闸门 27 `ui-pure`：P1 的**纯函数**回归（不需要浏览器、不需要 WebGL）。
//
// 覆盖参考包自带的测试（队形 0–6 个敌人、屏幕命中、状态机），并补上本仓库自己关心的三条：
//   * 队形**不按数组下标**重编号（业务 slot 必须原样带出来）；
//   * 超过 6 个敌人与重复 slot **响亮失败**（`RangeError`，不静默截掉可攻击目标）；
//   * 无目标牌丢在敌人身上仍然落到 `slot = -1`（§352 P1-B），以及 `dismiss` 不产生提交。
//
// 为什么与闸门 25/26 分开：红了要能一眼看出坏在**纯逻辑**、**接线**还是**渲染**。
// 编译用跑本脚本的这个 node 去执行 typescript 的 tsc.js，**不依赖 PATH**（验收链给的是收窄的 PATH）。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-pure-"));

let bad = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) bad += 1;
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
      "src/input/pointerMachine.ts",
      "src/input/hitTest.ts",
      "src/stage/formation.ts",
      "src/stage/combatLayout.ts",
      "src/stage/layout.ts",
      "src/wasm/snapshot.ts",
      "src/view/choiceText.ts",
      "src/i18n/index.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const formation = await import(pathToFileURL(join(out, "stage/formation.js")).href);
  const combat = await import(pathToFileURL(join(out, "stage/combatLayout.js")).href);
  const snapshotMod = await import(pathToFileURL(join(out, "wasm/snapshot.js")).href);
  const choiceText = await import(pathToFileURL(join(out, "view/choiceText.js")).href);
  const i18n = await import(pathToFileURL(join(out, "i18n/index.js")).href);
  const hit = await import(pathToFileURL(join(out, "input/hitTest.js")).href);
  const machine = await import(pathToFileURL(join(out, "input/pointerMachine.js")).href);

  // ── 队形：0–6 个敌人，横竖屏 ─────────────────────────────────────────────
  const portrait = { width: 390, height: 844, halfW: 1.82, halfH: 3.93 };
  const desktop = { width: 1280, height: 800, halfW: 3.98, halfH: 2.49 };
  let formationOk = true;
  let slotOk = true;
  let rowOk = true;
  let heroOk = true;
  for (let n = 0; n <= 6; n += 1) {
    // 故意用**非连续**的 slot：证明队形不按下标重编号（业务身份原样带出来）
    const slots = Array.from({ length: n }, (_, i) => i * 7 + 3);
    for (const view of [portrait, desktop]) {
      const result = formation.computeCombatFormation(slots, view);
      if (result.enemies.length !== n) formationOk = false;
      if (JSON.stringify(result.enemies.map((e) => e.slot)) !== JSON.stringify(slots)) slotOk = false;
      if (!(result.hero.x < 0)) heroOk = false;
    }
    const wide = formation.computeCombatFormation(slots, desktop);
    const upper = wide.enemies.filter((e) => e.row === 0).length;
    const lower = wide.enemies.filter((e) => e.row === 1).length;
    // 规则：**n ≤ 4 单排**（用户明确需求），n ≥ 5 才分两排（5 → 3+2、6 → 3+3）。
    const wantUpper = n <= 4 ? n : Math.ceil(n / 2);
    const wantLower = n - wantUpper;
    if (upper !== wantUpper || lower !== wantLower) rowOk = false;
  }
  check(formationOk, "队形：0–6 个敌人在横竖屏都生成正确数量");
  check(slotOk, "队形：业务 slot 原样带出（不按数组下标重编号）");
  check(rowOk, "队形：横屏 n≤4 一排、n≥5 两排（5 → 3+2、6 → 3+3）");
  check(heroOk, "队形：我方永远在左侧");

  const portrait2 = formation.computeCombatFormation([0, 1], portrait);
  const gap2 = Math.abs(portrait2.enemies[0].y - portrait2.enemies[1].y);
  check(gap2 >= 1.3, "竖屏两个敌人的纵向间距放得下三行标签", `gap=${gap2.toFixed(2)}`);

  // ⚠️ 回归守卫：横屏 n=2 曾经"每排各 1 名、x 都是 mid" ⇒ 两个怪上下叠成一条竖线，
  // 横屏看起来像竖屏（截图抓到的就是这个）。现在必须**同一排、不同 x**。
  const wide2 = formation.computeCombatFormation([0, 1], desktop);
  check(
    wide2.enemies.every((enemy) => enemy.row === 0),
    "队形：横屏 2 个敌人**同一排**（不是上下叠）",
    JSON.stringify(wide2.enemies.map((enemy) => ({ slot: enemy.slot, row: enemy.row })))
  );
  check(
    Math.abs(wide2.enemies[0].x - wide2.enemies[1].x) > 0.5,
    "队形：横屏 2 个敌人的 x 明显分开",
    JSON.stringify(wide2.enemies.map((enemy) => Number(enemy.x.toFixed(2))))
  );
  check(
    Math.abs(wide2.enemies[0].y - wide2.enemies[1].y) < 1e-9,
    "队形：横屏 2 个敌人的 y 相同（同一排）",
    JSON.stringify(wide2.enemies.map((enemy) => Number(enemy.y.toFixed(2))))
  );
  // ⚠️ §397：n=4 **必须**一排 4 名（用户原话"n<=4 的时候都只有一排"）。
  // 这条断言在 §361 被改成"4 = 2+2"，理由是"每排至多 3 名"——而那条约束**不存在**
  // （只出现在上一轮审阅的措辞里）。审阅不能盖过用户明确说过的需求。
  const wide4 = formation.computeCombatFormation([0, 1, 2, 3], desktop);
  const upper4 = wide4.enemies.filter((enemy) => enemy.row === 0).length;
  const lower4 = wide4.enemies.filter((enemy) => enemy.row === 1).length;
  check(
    upper4 === 4 && lower4 === 0,
    "队形：横屏 4 个敌人**一排 4 名**（§397 用户需求）",
    JSON.stringify({ upper: upper4, lower: lower4 })
  );
  check(
    wide4.enemies.every((enemy) => enemy.row === 0) &&
      new Set(wide4.enemies.map((enemy) => Number(enemy.x.toFixed(2)))).size === 4,
    "队形：横屏 4 名**同一排且 x 两两不同**（不叠）",
    JSON.stringify(wide4.enemies.map((enemy) => Number(enemy.x.toFixed(2))))
  );
  const wide5 = formation.computeCombatFormation([0, 1, 2, 3, 4], desktop);
  check(
    wide5.enemies.filter((enemy) => enemy.row === 0).length === 3 &&
      wide5.enemies.filter((enemy) => enemy.row === 1).length === 2,
    "队形：横屏 5 个敌人 = 3+2",
    JSON.stringify(wide5.enemies.map((enemy) => enemy.row))
  );

  let threw6 = false;
  try {
    formation.computeCombatFormation([0, 1, 2, 3, 4, 5, 6], desktop);
  } catch (error) {
    threw6 = error instanceof RangeError;
  }
  check(threw6, "7 个敌人 ⇒ RangeError（不静默截掉可攻击目标）");

  let threwDup = false;
  try {
    formation.computeCombatFormation([1, 1], desktop);
  } catch (error) {
    threwDup = error instanceof RangeError;
  }
  check(threwDup, "重复 slot ⇒ RangeError");

  // ── 版面区域模型（UX-3）────────────────────────────────────────────────
  const portraitView = { width: 390, height: 844 };
  const wideView = { width: 1280, height: 800 };
  let ordered = true;
  let outerInside = true;
  let strideOk = true;
  let finite = true;
  for (const view of [portraitView, wideView]) {
    for (const n of [1, 2, 3, 5, 10, 12]) {
      const L = combat.computeCombatLayout(view, n);
      const r = L.regions;
      if (!(r.hudTop <= r.hudBottom && r.hudBottom < r.combatTop && r.combatTop < r.combatBottom
        && r.combatBottom <= r.handBottom && r.handBottom < r.actionsTop && r.actionsTop < view.height)) {
        ordered = false;
      }
      // 最外侧那张牌的外缘必须留在视口内
      const outerEdge = L.fanSpread + combat.CARD_W / 2;
      if (outerEdge > L.halfW + 1e-6) outerInside = false;
      if (!Number.isFinite(L.fanCenterY) || !Number.isFinite(L.fanSpread)) finite = false;
      if (n > 1) {
        const pxPerWorld = combat.pxPerWorldAt(L.cameraDistance, combat.FAN_Z, view.height);
        const stridePx = ((2 * L.fanSpread) / (n - 1)) * pxPerWorld;
        // 至少露出 20px（紧凑态阈值），除非"装得下"与"露出够宽"不可兼得
        const maxStridePx = ((2 * (L.halfW * 0.98 - combat.CARD_W / 2)) / (n - 1)) * pxPerWorld;
        if (stridePx < Math.min(20, maxStridePx) - 0.5) strideOk = false;
      }
    }
  }
  check(ordered, "版面区域严格有序（HUD < 战场 < 手牌 < 操作栏），1–12 张手牌 × 两种视口");
  check(outerInside, "手牌 1–12 张时最外侧那张的外缘仍在视口内");
  check(strideOk, "手牌 1–12 张时牌与牌之间至少露出 20px（或已到可用的上限）");
  check(finite, "手牌 1 张时不除零（fanSpread / fanCenterY 都是有限值）");

  const safe = combat.computeCombatLayout({ width: 390, height: 844, safeTop: 44, safeBottom: 34 }, 10);
  check(
    safe.regions.hudBottom === 44 + 86 && safe.regions.actionsTop === 844 - 34 - 56,
    "安全区把 HUD 往下推、把操作栏往上推",
    JSON.stringify(safe.regions)
  );

  let threwViewport = false;
  try {
    combat.computeCombatLayout({ width: 0, height: 844 }, 10);
  } catch (error) {
    threwViewport = error instanceof RangeError;
  }
  check(threwViewport, "非法视口（宽 0）⇒ RangeError");

  // ── 屏幕命中 ────────────────────────────────────────────────────────────
  const enemies = [
    { slot: 4, x: 200, y: 120, r: 40 },
    { slot: 5, x: 300, y: 120, r: 40 },
  ];
  check(hit.enemyAtScreen(enemies, 210, 120, new Set([4, 5])) === 4, "命中最近的合法敌人");
  check(hit.enemyAtScreen(enemies, 210, 120, new Set([5])) === -1, "不在合法集合里的敌人不算命中");
  check(hit.enemyAtScreen(enemies, 10, 10, new Set([4, 5])) === -1, "空白处不命中");
  const cards = [
    { slot: 0, hitX: 50, hitY: 400, visibleW: 30, h: 90 },
    { slot: 1, hitX: 80, hitY: 400, visibleW: 30, h: 90 },
  ];
  check(hit.cardAtScreen(cards, 50, 400) === 0 && hit.cardAtScreen(cards, 80, 400) === 1,
    "手牌命中按**露出条**中心（hitX），不按被遮住的牌心");
  check(hit.cardAtScreen(cards, 10, 100) === -1, "手牌外不命中");

  // ── 观察向量解码（合成向量，不需要 wasm）────────────────────────────────
  // 布局与 `kernel/rd-wasm/src/lib.rs` 的 `OFF_*` 一致：header 12 / 英雄状态 5 /
  // 敌人 6×8 / 敌人状态 6×5 / 手牌 10×4 / 牌堆 5 / 保留 8 = 148。
  const OBS = 148;
  const makeObs = () => {
    const obs = new Int32Array(OBS).fill(-1);
    for (let index = 135; index < 140; index += 1) obs[index] = 0; // 牌堆是计数，0 有意义
    return obs;
  };
  const decode = snapshotMod.decodeCombat;

  const obs = makeObs();
  obs[0] = 3; // round
  obs[1] = 2; // turn
  obs[2] = 1; // phase inProgress
  obs[3] = 0; // ongoing
  obs[4] = 61; obs[5] = 80; obs[6] = 5; obs[8] = 2; obs[9] = 3;
  obs[10] = 2; // hand count
  obs[11] = 1; // enemy count
  obs[12] = 2; // hero strength
  // 敌人槽 0：alive, hp 30/44, block 4, ward -1, intent 1/9, statuses 1
  obs[17] = 1; obs[18] = 30; obs[19] = 44; obs[20] = 4; obs[21] = -1; obs[22] = 1; obs[23] = 9; obs[24] = 1;
  // 手牌：槽 0 数字费 3；槽 1 是 X 费（-2）
  obs[95] = 1; obs[96] = 3; obs[97] = 7; obs[98] = 0;
  obs[99] = 1; obs[100] = snapshotMod.X_COST_DISPLAY; obs[101] = 8; obs[102] = 0;
  obs[135] = 4; obs[136] = 2; obs[137] = 1;

  const decoded = decode(obs, [
    snapshotMod.decodeAction(0, 0, 0, 0),
    snapshotMod.decodeAction(1, 1, -1, -1),
  ]);
  check(decoded.round === 3 && decoded.turn === 2 && decoded.phase === "inProgress", "解码：头部字段");
  check(decoded.hero.hp === 61 && decoded.hero.block === 5 && decoded.hero.energy === 2, "解码：英雄");
  check(decoded.hero.statuses.strength === 2, "解码：英雄状态轴（ABI 顺序）");
  check(decoded.enemies.length === 1 && decoded.enemies[0].hp === 30, "解码：只解出**存在**的敌人槽（其余是 -1）");
  check(decoded.enemies[0].intentKind === 1 && decoded.enemies[0].intentDamage === 9, "解码：敌人意图");
  check(
    decoded.hand.length === 2 && decoded.hand[0].cost === 3 && decoded.hand[1].cost === "X",
    "解码：数字费与 X 费（-2 ⇒ \"X\"）",
    JSON.stringify(decoded.hand.map((card) => card.cost))
  );
  check(
    decoded.piles.draw === 4 && decoded.piles.hand === 2 && decoded.piles.discard === 1,
    "解码：牌堆计数（0 有意义，不是 -1）"
  );
  check(decoded.actions[1].kind === "endTurn" && decoded.actions[1].handSlot === -1, "解码：动作表 endTurn");

  const mismatch = makeObs();
  mismatch[11] = 2; // header 说 2 个敌人，但一个槽都没有
  let threwMismatch = false;
  try {
    decode(mismatch, []);
  } catch (error) {
    threwMismatch = error instanceof RangeError;
  }
  check(threwMismatch, "解码：header 敌人计数与槽位不符 ⇒ RangeError（不渲染幽灵敌人）");

  // ── 选牌句子：`kind` **十种**每种都要有自己的一句话 ─────────────────────
  // 第一版只写了 kind 0/1/2（还 `as` 强转），夹具一喝 Attack Potion 就返回 3 ⇒ 这里穷举。
  const sentenceFor = (source, kind, min, max, copies = 0) =>
    choiceText.choiceSentence({ source, kind, min, max, copies, options: [] });
  const kinds = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const sentences = kinds.map((kind) => sentenceFor(1, kind, 1, 1));
  check(
    sentences.every((line) => typeof line === "string" && line.length > 0),
    "十种 kind 都能写出句子",
    JSON.stringify(sentences)
  );
  check(
    new Set(sentences).size === kinds.length,
    "十种 kind 的句子**互不相同**（同句 = 页面把两件事说成一件）",
    JSON.stringify(sentences.filter((line, index) => sentences.indexOf(line) !== index))
  );
  check(
    sentenceFor(2, 3, 1, 1).includes("候选") && sentenceFor(1, 3, 1, 1).includes("牌堆"),
    "同样的 kind 3，source 不同句子不同（三选一 vs 从牌堆拿）",
    JSON.stringify([sentenceFor(2, 3, 1, 1), sentenceFor(1, 3, 1, 1)])
  );
  check(
    sentenceFor(1, 1, 1, 1).includes("1 张") && sentenceFor(1, 1, 1, 3).includes("1–3 张"),
    "数量：min == max 写 n 张，否则写 m–n 张",
    JSON.stringify([sentenceFor(1, 1, 1, 1), sentenceFor(1, 1, 1, 3)])
  );
  check(
    sentenceFor(2, 4, 1, 1, 2).includes("2 份"),
    "复制问句写出份数（copies 来自内核，不由 `+` 推断）",
    sentenceFor(2, 4, 1, 1, 2)
  );
  check(
    sentenceFor(1, 99, 1, 1).includes("未知"),
    "未知 kind ⇒ 说实话（不猜一句像话的）",
    sentenceFor(1, 99, 1, 1)
  );

  // ── i18n：精确 / `+` 剥壳 / 回退 三层 ─────────────────────────────────
  i18n.resetCoverage();
  check(i18n.displayName("cards", "strike") === "打击", "i18n：精确命中（strike → 打击）", i18n.displayName("cards", "strike"));
  check(
    i18n.displayName("cards", "strike+") === "打击+",
    "i18n：`+` 变体剥壳后查基础条目并补回 +",
    i18n.displayName("cards", "strike+")
  );
  check(
    i18n.displayText("cards", "strike").length > 0,
    "i18n：介绍文本非空",
    i18n.displayText("cards", "strike")
  );
  check(
    i18n.displayName("statuses", "standard.vulnerable") === "易伤",
    "i18n：ABI 状态轴（standard.vulnerable → 易伤）",
    i18n.displayName("statuses", "standard.vulnerable")
  );
  const unknown = i18n.displayName("cards", "no_such_card_xyz");
  check(
    unknown === "no_such_card_xyz",
    "i18n：未知 id 回退成 id 本身（不编名字）",
    unknown
  );
  const report = i18n.coverage();
  check(
    report.cards.fallbacks === 1 && report.cards.ids[0] === "no_such_card_xyz",
    "i18n：回退被计数（静默回退 = 假装翻译过）",
    JSON.stringify(report.cards)
  );
  check(
    report.cards.entries > 200 && report.monsters.entries > 30 && report.statuses.entries >= 13,
    "i18n：表有内容（卡 >200 / 怪 >30 / 状态 >=13）",
    JSON.stringify({ cards: report.cards.entries, monsters: report.monsters.entries, statuses: report.statuses.entries })
  );

  // ── i18n：事件表（P5：id 对照表 + 选项标签）──────────────────────────────
  //
  // 判据不是"有多少条"，而是三件具体的事：
  //   1. 内容里的**每一个**事件根 id 都有中文名（表覆盖，不是碰巧有几个）；
  //   2. 事件**选项标签**能翻成中文（英文短句 → 中文，查不到要回退并计数）；
  //   3. 子节点正文**没有**官方中文来源 ⇒ 必须回退到英文并**计数**（不静默）。
  i18n.resetCoverage();
  const events = report.events;
  check(events.entries >= 36, "i18n：事件表覆盖 >= 36 个根事件", String(events.entries));
  const golden = i18n.eventName("golden_idol");
  check(golden === "金神像", "i18n：事件名（golden_idol → 金神像）", golden);
  check(i18n.eventName("shining_light") === "闪耀之光", "i18n：事件名（shining_light → 闪耀之光）");
  check(i18n.eventName("scrap_pile") === "破烂软泥", "i18n：别名对照（scrap_pile → 破烂软泥）", i18n.eventName("scrap_pile"));
  check(i18n.eventName("no_such_event") === "no such event", "i18n：未知事件 id 回退（下划线变空格）", i18n.eventName("no_such_event"));
  const body = i18n.eventText("golden_idol", "An idol of gold sits on a mossy altar.");
  check(body !== "An idol of gold sits on a mossy altar." && body.length > 0, "i18n：事件正文有中文", body.slice(0, 24));
  const subBody = i18n.eventText("golden_idol.boulder", "You hear a rumble above you.");
  check(subBody === "You hear a rumble above you.", "i18n：子节点正文回退英文（没有官方中文来源）", subBody);
  check(i18n.eventOptionLabel("Take it") === "拿走", "i18n：选项标签（Take it → 拿走）", i18n.eventOptionLabel("Take it"));
  check(i18n.eventOptionLabel("Reach Inside") === "伸手进去", "i18n：选项标签（Reach Inside → 伸手进去）");
  const unknownLabel = i18n.eventOptionLabel("Do something impossible");
  check(unknownLabel === "Do something impossible", "i18n：未知标签回退英文", unknownLabel);
  const fallbacks = i18n.eventI18nFallbacks();
  check(
    fallbacks.texts >= 1 && fallbacks.labels >= 1,
    "i18n：事件回退被计数（正文 + 标签各一条）",
    JSON.stringify(fallbacks)
  );

  // ── 状态机 ──────────────────────────────────────────────────────────────
  const targeted = [
    { slot: 0, actionIndex: 1, label: "a" },
    { slot: 1, actionIndex: 2, label: "b" },
  ];
  const untargeted = [{ slot: -1, actionIndex: 9, label: "skill" }];
  let session = machine.INITIAL;
  const play = (options, hoverSlot, distance = 40) => {
    session = machine.reduce(session, { type: "down", handSlot: 0, options });
    session = machine.reduce(session, { type: "move", hoverSlot, distance });
    session = machine.reduce(session, { type: "up", hoverSlot, distance });
    return session;
  };
  const first = play(targeted, 1);
  const second = play(targeted, 1);
  check(
    second.resultSeq === first.resultSeq + 1,
    "同一动作做两次 ⇒ 事件序号递增（不按 payload 去重）",
    `seq ${first.resultSeq} -> ${second.resultSeq}`
  );
  const onEnemy = play(untargeted, 1);
  check(
    onEnemy.lastResult?.kind === "commit" && onEnemy.lastResult.targetSlot === -1,
    "无目标牌丢在敌人身上 ⇒ commit 且 targetSlot = -1",
    JSON.stringify(onEnemy.lastResult)
  );
  const tiny = play(targeted, 1, machine.DRAG_THRESHOLD_PX - 1);
  check(tiny.lastResult === null, "位移小于阈值 ⇒ 不产生结果（点按语义）");

  let dismissed = machine.reduce(machine.INITIAL, { type: "down", handSlot: 0, options: targeted });
  dismissed = machine.reduce(dismissed, { type: "dismiss" });
  check(
    dismissed.phase === "idle" && dismissed.lastResult === null,
    "dismiss（长按看详情）⇒ 回 idle 且不产生提交",
    JSON.stringify(dismissed.lastResult)
  );

  await rm(out, { recursive: true, force: true });
  console.log("");
  if (bad > 0) {
    console.error(`UI_PURE FAIL: ${bad} 条`);
    process.exit(1);
  }
  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4 layout=6 decode=8 choice=6 i18n=18 rows=4`);
} catch (error) {
  await rm(out, { recursive: true, force: true }).catch(() => {});
  console.error(`UI_PURE ERROR: ${error.message}`);
  process.exit(1);
}
