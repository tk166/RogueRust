// 闸门 33 `ui-scene`：**场景判定**的纯函数回归（不需要浏览器、不需要 WebGL）。
//
// 这一道闸门守的是 P3 最核心的那条设计：**屏幕是算出来的，不是记出来的**。
// 所以它必须证明三件事：
//
// 1. **穷尽**：任何内核事实的组合都能得到一个场景（`resolveScene` 从不返回 `undefined`，
//    从不抛异常）。内核加了新相位而 UI 没跟上时，`unknownPending` 会**报出来**而不是静默画地图。
// 2. **顺序**：`docs/ui-state-model.md` 里两处"为什么排在这里"的陷阱必须成立 ——
//    `SC-03b` 在 `SC-03` 之前、`SC-02b` 在 `SC-02` 之前。顺序是**语义**，所以要断言，
//    而不是"我记得我写对了"。
// 3. **逐行**：18 行表的每一行都有一个手写夹具，断言 `base`/`overlays` 与表一致。
//
// 另外守两个"第一版真错过"的判据（都来自实测）：
//   * `SC-03` 必须要求"这一格还没结算"（`nodeResolved === false`）—— 少了它，领完奖励会
//     回到"战斗前"，点下去被内核拒绝；
//   * 战斗中的 HP 与运行层 HP **本来就不相等**（战斗结算才写回），所以对账口径要按
//     "在不在战斗"分开 —— 这条在闸门 34 里用真实数值验证。
//
// 编译方式与闸门 27 一致：用跑本脚本的 node 执行 typescript 的 tsc.js，**不依赖 PATH**。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GATE = "UI_SCENE";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-scene-"));

let bad = 0;
/** 摘要用的数字（在 `try` 里填；摘要行在 `try` **外**，所以不能直接用里面的 `const`）。 */
const summary = { order: 0, overlays: 0, pending: 0, rows: 20, exhaustive: 0 };
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
      "src/run/scene.ts",
      "src/run/observe.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const scene = await import(pathToFileURL(join(out, "run/scene.js")).href);
  const observe = await import(pathToFileURL(join(out, "run/observe.js")).href);
  const { resolveScene, SCENE, SCENE_ORDER, OVERLAY_ORDER, PENDING_SCENE, sceneLabel, isImplemented } =
    scene;

  /** 一个"什么都没有"的基线；每个夹具只改它关心的字段。 */
  const base = () => ({
    runExists: true,
    inFight: false,
    hasCombatSession: false,
    pending: 0,
    over: 0,
    bossBeaten: false,
    nodeKind: 1,
    nodeResolved: false,
    unknownRoom: 0,
    eventFight: 0,
    actionCount: 3,
    pickupPicks: 0,
    pickupAdd: 0,
  });
  const resolve = (overrides = {}) => resolveScene({ ...base(), ...overrides });

  // ── 1. 表本身：顺序与完整性 ────────────────────────────────────────────────
  check(SCENE_ORDER.length === 16, "SCENE_ORDER 有 16 条（18 行表去掉两个覆盖层）", String(SCENE_ORDER.length));
  check(new Set(SCENE_ORDER).size === SCENE_ORDER.length, "SCENE_ORDER 没有重复");
  check(OVERLAY_ORDER.length === 2, "覆盖层 2 条", String(OVERLAY_ORDER.length));
  check(
    !SCENE_ORDER.some((id) => OVERLAY_ORDER.includes(id)),
    "覆盖层不在 base 顺序表里（否则同一屏会被判两次）"
  );
  const allScenes = new Set(Object.values(SCENE));
  check(allScenes.size === 18, "SCENE 常量共 18 个", String(allScenes.size));
  check(
    SCENE_ORDER.every((id) => allScenes.has(id)) && OVERLAY_ORDER.every((id) => allScenes.has(id)),
    "顺序表里的每一项都是已知场景"
  );

  // 两处**顺序陷阱**（`docs/ui-state-model.md` 的"为什么排在这里"）。
  const idx = (id) => SCENE_ORDER.indexOf(id);
  check(idx(SCENE.combat) < idx(SCENE.preCombat), "SC-03b（战斗中）排在 SC-03（战斗前）之前");
  check(idx(SCENE.actEnd) < idx(SCENE.map), "SC-02b（幕尽头）排在 SC-02（地图兜底）之前");
  check(idx(SCENE.map) === SCENE_ORDER.length - 1, "SC-02 是最后一条（兜底）");

  // `pending` 表：1..9 每档都在，且 0 不许有值。
  const pendingKeys = Object.keys(PENDING_SCENE).map(Number).sort((a, b) => a - b);
  check(
    JSON.stringify(pendingKeys) === JSON.stringify([1, 2, 3, 4, 5, 6, 7, 8, 9]),
    "PENDING_SCENE 恰好覆盖 1..9（0 不是相位）",
    JSON.stringify(pendingKeys)
  );
  check(
    Object.values(PENDING_SCENE).every((id) => allScenes.has(id)),
    "PENDING_SCENE 的每一项都是已知场景"
  );

  // ── 2. 逐行夹具（18 行表的每一行）──────────────────────────────────────────
  const rows = [
    ["SC-00 未开局", { runExists: false }, SCENE.title, []],
    ["SC-03b 战斗中", { inFight: true, hasCombatSession: true }, SCENE.combat, []],
    ["SC-11a 遗物·改牌", { pending: 4, pickupPicks: 2 }, SCENE.reward, [SCENE.pickupChange]],
    ["SC-11b 遗物·加牌", { pending: 4, pickupAdd: 1 }, SCENE.reward, [SCENE.pickupAdd]],
    ["SC-12b 局终", { over: 1 }, SCENE.over, []],
    ["SC-12a 幕通关", { bossBeaten: true }, SCENE.actCleared, []],
    ["SC-01 塔底祝福", { pending: 6 }, SCENE.blessing, []],
    ["SC-01b 祝福选牌", { pending: 7 }, SCENE.blessingCard, []],
    ["SC-09 事件选牌", { pending: 8 }, SCENE.eventCard, []],
    ["SC-10 事件候选", { pending: 9 }, SCENE.eventOffer, []],
    ["SC-04 战斗奖励", { pending: 4 }, SCENE.reward, []],
    ["SC-08 事件", { pending: 5 }, SCENE.event, []],
    ["SC-07 宝箱", { pending: 3 }, SCENE.chest, []],
    ["SC-05 商店", { pending: 2 }, SCENE.shop, []],
    ["SC-06 篝火", { pending: 1 }, SCENE.rest, []],
    ["SC-03 战斗前", { nodeKind: 1 }, SCENE.preCombat, []],
    ["SC-03 `?`房掷出怪物", { nodeKind: 5, unknownRoom: 2 }, SCENE.preCombat, []],
    ["SC-03 事件里的战斗", { nodeKind: 5, unknownRoom: 1, eventFight: 1 }, SCENE.preCombat, []],
    ["SC-02b 幕尽头", { nodeKind: 4, actionCount: 0 }, SCENE.actEnd, []],
    ["SC-02 地图", { nodeKind: 3, actionCount: 2 }, SCENE.map, []],
  ];
  for (const [label, overrides, wantBase, wantOverlays] of rows) {
    const got = resolve(overrides);
    check(
      got.base === wantBase && JSON.stringify(got.overlays) === JSON.stringify(wantOverlays),
      label,
      `base=${got.base} overlays=[${got.overlays}]`
    );
  }

  // ── 3. 两条"第一版真错过"的判据 ───────────────────────────────────────────
  // 3a. 打完的格子（`nodeResolved === true`）**不是**"战斗前"。
  const resolvedNode = resolve({ nodeKind: 1, nodeResolved: true, actionCount: 3 });
  check(
    resolvedNode.base === SCENE.map,
    "已结算的战斗节点 → 地图（不是战斗前）",
    `base=${resolvedNode.base}`
  );
  const unresolvedNode = resolve({ nodeKind: 1, nodeResolved: false });
  check(unresolvedNode.base === SCENE.preCombat, "未结算的战斗节点 → 战斗前", `base=${unresolvedNode.base}`);

  // 3b. `?` 房掷出"事件"时**不能**显示"进入战斗"（把 ? 一律当战斗是错的）。
  check(
    resolve({ nodeKind: 5, unknownRoom: 1 }).base === SCENE.map,
    "`?` 房掷出事件 → 地图（不显示战斗前）"
  );
  check(
    resolve({ nodeKind: 5, unknownRoom: 0 }).base === SCENE.map,
    "`?` 房还没掷 → 地图"
  );

  // ── 4. 穷尽性：任何组合都有场景，且未知相位会报出来 ────────────────────────
  let total = 0;
  let thrown = 0;
  const seen = new Set();
  for (const runExists of [true, false]) {
    for (const inFight of [false, true]) {
      for (const hasCombatSession of [false, true]) {
        for (const pending of [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, -1]) {
          for (const over of [0, 1]) {
            for (const nodeKind of [0, 1, 2, 3, 4, 5, 6, 7, 8]) {
              for (const nodeResolved of [false, true]) {
                for (const actionCount of [0, 3]) {
                  for (const bossBeaten of [false, true]) {
                    total += 1;
                    try {
                      const got = resolveScene({
                        runExists,
                        inFight,
                        hasCombatSession,
                        pending,
                        over,
                        bossBeaten,
                        nodeKind,
                        nodeResolved,
                        unknownRoom: 0,
                        eventFight: 0,
                        actionCount,
                        pickupPicks: 0,
                        pickupAdd: 0,
                      });
                      if (typeof got.base !== "string") throw new Error("base 不是字符串");
                      if (!allScenes.has(got.base)) throw new Error(`未知 base ${got.base}`);
                      seen.add(got.base);
                      // `unknownPending` 只在 pending 越界时非 null。
                      const wantUnknown = pending < 0 || pending > 9;
                      if ((got.unknownPending !== null) !== wantUnknown) {
                        throw new Error(`unknownPending=${got.unknownPending} 与 pending=${pending} 不符`);
                      }
                    } catch (cause) {
                      thrown += 1;
                      if (thrown <= 3) console.log("   抛了:", String(cause));
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
  check(thrown === 0, `穷尽组合都不抛（${total} 组）`, `抛了 ${thrown} 次`);
  summary.order = SCENE_ORDER.length;
  summary.overlays = OVERLAY_ORDER.length;
  summary.pending = Object.keys(PENDING_SCENE).length;
  summary.exhaustive = total;
  // 覆盖：这张表能真的产出**大多数**场景（没产出的那些要有理由）。
  const unreachable = [...allScenes].filter((id) => !seen.has(id));
  check(
    unreachable.every((id) => [SCENE.pickupChange, SCENE.pickupAdd, SCENE.blessingCard].includes(id)),
    "穷尽扫描只漏了覆盖层与需要 pending=7 的那一屏",
    JSON.stringify(unreachable)
  );

  // 未知相位：兜底到地图，但必须**报出来**。
  const unknown = resolve({ pending: 12 });
  check(
    unknown.base === SCENE.map && unknown.unknownPending === 12,
    "未知相位 12：兜底地图 + unknownPending=12",
    `base=${unknown.base} unknown=${unknown.unknownPending}`
  );

  // ── 5. 覆盖层可以同时存在，且 base 不受影响 ────────────────────────────────
  const both = resolve({ pending: 4, pickupPicks: 1, pickupAdd: 1 });
  check(
    both.base === SCENE.reward && both.overlays.length === 2,
    "两个欠账同时存在时 base 仍是奖励屏",
    JSON.stringify(both)
  );

  // ── 6. `opensFight`（SC-03 的判据之一）───────────────────────────────────
  check(observe.opensFight(1, 0) === true, "combat 会开战");
  check(observe.opensFight(2, 0) === true, "elite 会开战");
  check(observe.opensFight(7, 0) === true, "boss 会开战");
  check(observe.opensFight(5, 2) === true, "`?` 掷出怪物会开战");
  check(observe.opensFight(5, 1) === false, "`?` 掷出事件不会开战");
  check(observe.opensFight(0, 0) === false, "Unassigned 不会开战");
  check(observe.opensFight(3, 0) === false, "篝火不会开战");

  // ── 7. 地图解码（合成地图，不需要 wasm）──────────────────────────────────
  // 三个节点：0(0,0) → 1(1,1)；0 → 2(1,2)；2 可达。
  const fields = {
    0: { 0: 0, 1: 0, 2: 1, 3: 2, 4: 1, 5: 2, 6: -1, 7: 0 },
    1: { 0: 1, 1: 1, 2: 3, 3: 0, 4: -1, 5: -1, 6: -1, 7: 0 },
    2: { 0: 1, 1: 2, 2: 4, 3: 0, 4: -1, 5: -1, 6: -1, 7: 1 },
  };
  const map = observe.buildMap(3, 2, (index, field) => fields[index]?.[field] ?? -2147483648);
  check(map.nodes.length === 3, "地图 3 个节点", String(map.nodes.length));
  check(JSON.stringify(map.nodes[0].edges) === "[1,2]", "节点 0 的两条出边是全局下标 1,2");
  check(map.byIndex.get(2).reachable === true, "节点 2 可达");
  check(map.byIndex.get(1).reachable === false, "节点 1 不可达");
  const layout0 = map.layout.get(0);
  const layout2 = map.layout.get(2);
  check(layout0.y === 0 && layout2.y === 1, "布局：第 0 行 y=0，第 1 行 y=1", `${layout0.y}/${layout2.y}`);
  check(layout0.x === 0 && layout2.x === 1, "布局：列归一化到 0..1", `${layout0.x}/${layout2.x}`);

  // 出边超过 3 条要**响亮失败**（不是静默截断）。
  let threw = false;
  try {
    observe.buildMap(1, 2, (_index, field) => (field === 3 ? 4 : 0));
  } catch {
    threw = true;
  }
  check(threw, "out_degree > 3 响亮失败（RangeError）");

  // ── 8. 运行层观察向量解码 ────────────────────────────────────────────────
  const obs = new Int32Array(19);
  obs[0] = 3; // floor
  obs[1] = 17; // node
  obs[2] = 42; // health
  obs[3] = 80; // max
  obs[4] = 133; // gold
  obs[5] = 12; // deck
  obs[6] = 2; // relics
  obs[7] = 1; // potions
  obs[8] = 70; // map len
  for (let i = 0; i < 7; i += 1) obs[9 + i] = 100 + i;
  obs[16] = 2; // reachable
  obs[17] = 1; // removed
  obs[18] = 2; // unknown room = monster
  const run = observe.decodeRun(obs);
  check(
    run.floor === 3 && run.node === 17 && run.health === 42 && run.healthMax === 80,
    "观察向量：层/节点/HP 解码正确",
    JSON.stringify({ floor: run.floor, node: run.node, health: run.health })
  );
  check(run.gold === 133 && run.deckSize === 12 && run.mapLen === 70, "观察向量：金币/牌组/地图长度");
  check(JSON.stringify(run.rng) === JSON.stringify([100, 101, 102, 103, 104, 105, 106]), "七条 RNG 流按序解出");
  check(run.unknownRoom === 2, "unknownRoom 解出怪物");
  let shortThrew = false;
  try {
    observe.decodeRun(new Int32Array(10));
  } catch {
    shortThrew = true;
  }
  check(shortThrew, "观察向量太短响亮失败（不静默补 0）");

  // ── 8b. 终局类场景的**身份与能力**（第十五轮 Review §4 的负控）────────────
  //
  // 以前 `EndScene` 自己把 `data-scene` 算成 `over ? SC-12b : SC-12a`，于是 `SC-02b`
  // **报成 SC-12a**；"继续"按钮也只在 `SC-12a` 时给 ⇒ 一旦 `SC-02b` 可达就是"没有下一步"。
  // 那条路径在当前内容下不可达，所以闸门 34/36 的 `domScene() == scene.base` 从未执行到它。
  // 现在身份/能力由纯函数给，这里逐条钉住。
  const over = scene.endSceneFor(scene.SCENE.over);
  const actCleared = scene.endSceneFor(scene.SCENE.actCleared);
  const actEnd = scene.endSceneFor(scene.SCENE.actEnd);
  check(over !== null && over.sceneId === "SC-12b" && over.canContinue === false, "SC-12b：身份 SC-12b、没有继续", JSON.stringify(over));
  check(actCleared !== null && actCleared.sceneId === "SC-12a" && actCleared.canContinue === true, "SC-12a：身份 SC-12a、能继续", JSON.stringify(actCleared));
  check(actEnd !== null && actEnd.sceneId === "SC-02b", "SC-02b：**报自己的 id**（不再冒充 SC-12a）", JSON.stringify(actEnd));
  check(actEnd !== null && actEnd.canContinue === true, "SC-02b：能继续（内核动作是 end_act）", JSON.stringify(actEnd));
  check(
    scene.endSceneFor(scene.SCENE.map) === null && scene.endSceneFor(scene.SCENE.combat) === null,
    "非终局类返回 null（组件不会误用它）"
  );

  // ── 9. 标签/实现状态的自洽 ────────────────────────────────────────────────
  check(
    [...allScenes].every((id) => sceneLabel(id) !== id && sceneLabel(id).length > 0),
    "每个场景都有中文名（不是回退到 id）"
  );
  check(isImplemented(SCENE.map) && isImplemented(SCENE.reward) && isImplemented(SCENE.combat), "P3 的三屏都标成已实现");
  // P4 之后：商店/篝火/宝箱/事件/选牌都已有界面（`UnsupportedScene` 只剩兜底用途）。
  check(
    isImplemented(SCENE.shop) &&
      isImplemented(SCENE.rest) &&
      isImplemented(SCENE.chest) &&
      isImplemented(SCENE.event) &&
      isImplemented(SCENE.eventCard) &&
      isImplemented(SCENE.eventOffer) &&
      isImplemented(SCENE.blessingCard),
    "P4 的七屏也标成已实现"
  );
} finally {
  await rm(out, { recursive: true, force: true });
}

console.log("");
if (bad > 0) {
  console.error(`${GATE} FAIL: ${bad} 条`);
  process.exit(1);
}
console.log(
  `UI_SCENE PASS order=${summary.order}+${summary.overlays} pending=${summary.pending} ` +
    `exhaustive=${summary.exhaustive} rows=${summary.rows}`
);
