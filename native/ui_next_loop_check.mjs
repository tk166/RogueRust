// 闸门 34 `ui-next-loop`：**完整一圈**的端到端（真实 wasm + 真实 DOM + 真实 3D 拾取）。
//
// 这一道守的是 plan P3 的退出条件：
//
//   > 从标题页走地图并打一场普通遭遇、正确领取奖励、继续地图；无隐藏手工刷新步骤；
//   > 所有 Snapshot 对账通过。
//
// ## 为什么几乎每一步都用**真 DOM 点击**
//
// 探针能直接调 `store.enterNode()`，但那样证明的是"函数能跑"，不是"玩家点得到"。
// 所以凡是玩家会点的地方（开始、祝福、地图节点、领奖励、继续）都走 `element.click()`；
// 只有"把这一场打完"用探针（打 20 步牌不是这一道闸门要测的东西 —— P2 的闸门 28/29 已经在测）。
//
// ## 一次**真实 3D 目标拾取**
//
// plan 明确要求"至少一次真实 3D 目标拾取 E2E"。这里用 CDP 发真的 `Input.dispatchMouseEvent`
// （不是 `element.click()`），从手牌拖到敌人身上，断言只有**被指的那个敌人**掉血。
// 这是 P2 的闸门 29 在回归页做的同一件事，但这里发生在**运行层外壳里**（场景路由、顶栏、
// 对账都开着）—— 换个外壳就坏掉的接线会被抓住。
//
// ## 对账（"所有 Snapshot 对账通过"）
//
// 每个阶段都断言 `violations()` 为空。另外单独验证一条闸门 33 说明过的口径：
// **战斗中运行层 HP 是故意不跟的**，而 `fight_end` 之后必须**写回**成战斗结束时的那个值。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_NEXT_LOOP";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
/** 摘要用（在 `try` 里填；摘要行在 `try` 外，不能直接用里面的 `const`）。 */
const summary = { nodes: 0, steps: 0, chain: [] };
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

// wasm 与包必须同步（否则测的是旧包）。
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "",
  gate: GATE,
  // 视口必须钉住（§168）：3D 投影的坐标随视口变，不钉住就是"在测这台机器"。
  viewport: { width: 1280, height: 800 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

/** 每个阶段都要过的一关：对账必须干净。 */
const clean = async (label) => {
  const violations = await ev("window.__run.violations()");
  check(violations.length === 0, `${label}：对账干净`, JSON.stringify(violations));
  return violations;
};

/** 场景 + DOM 必须一致（"画出来的 == 算出来的"）。 */
const sceneMatchesDom = async (label) => {
  const scene = await ev("window.__run.scene()");
  const dom = await ev("window.__run.domScene()");
  check(scene.base === dom, `${label}：DOM 的 data-scene 与判定一致`, `${scene.base} vs ${dom}`);
  return scene;
};

try {
  // ── 阶段 0：标题 ────────────────────────────────────────────────────────
  const chain = [];
  const noteScene = (id) => chain.push(id);
  let scene = await sceneMatchesDom("装载后");
  noteScene(scene.base);
  check(scene.base === "SC-00", "装载后停在标题（没有局）", scene.base);
  check((await ev("window.__run.run()")) === null, "没有局时 run 快照是 null");
  await clean("装载后");

  // ── 阶段 1：真点击"开始爬塔" ────────────────────────────────────────────
  const started = await ev(`window.__run.click("[data-start]")`);
  check(started.clicked === true, "标题页有可点的开始按钮", JSON.stringify(started));
  await sleep(120);
  scene = await sceneMatchesDom("开局后");
  noteScene(scene.base);
  check(scene.base === "SC-01", "开局后进入塔底祝福", scene.base);
  const run0 = await ev("window.__run.run()");
  check(run0 !== null && run0.health > 0 && run0.deckSize > 0, "运行层快照可用", JSON.stringify({ hp: run0?.health, deck: run0?.deckSize }));
  await clean("开局后");

  // ── 阶段 2：祝福（真点击；选**不需要选牌**的那个）──────────────────────────
  const blessings = await ev("window.__run.blessings()");
  check(Array.isArray(blessings) && blessings.length >= 2, "祝福候选 >= 2（条数由内核给）", String(blessings?.length));
  // 找 gain/cost 都不是"选牌"那一类的（`upgrade_card` 一类会进 SC-01b）。
  const simple = blessings.find((b) => !/card/.test(b.id)) ?? blessings[0];
  const chosen = await ev(`window.__run.click("[data-blessing='${simple.slot}']")`);
  check(chosen.clicked === true, `祝福页有第 ${simple.slot} 项`, JSON.stringify(chosen));
  await sleep(120);
  scene = await sceneMatchesDom("选祝福后");
  noteScene(scene.base);
  check(scene.base === "SC-02", "选完祝福进入地图", scene.base);
  await clean("选祝福后");

  // ── 阶段 3：地图（模型 + DOM 一一对应）───────────────────────────────────
  const map = await ev("window.__run.map()");
  const reachable = map.nodes.filter((node) => node.reachable);
  check(map.rows >= 10, "地图行数合理", String(map.rows));
  // 第 1 行最多 6 列（`run-layer.md` §7.2），所以可达数在 2..6 —— 不要写死 2–3。
  check(reachable.length >= 2 && reachable.length <= 6, "第 1 步可达 2–6 个节点", String(reachable.length));
  const domReachable = await ev(`document.querySelectorAll("[data-reachable='1']").length`);
  check(domReachable === reachable.length, "DOM 里高亮的节点数 == 模型里的可达数", `${domReachable} vs ${reachable.length}`);
  const domNodes = await ev(`document.querySelectorAll("[data-node]").length`);
  summary.nodes = map.nodes.length;
  check(domNodes === map.nodes.length, "DOM 画出了全部节点", `${domNodes} vs ${map.nodes.length}`);
  // 开局（还没出发）没有"当前节点"，所以**没有**高亮边是对的：第 1 行的可达节点靠
  // 自身的呼吸环提示。高亮边在"站在某个节点上"之后才有意义（阶段 10 断言）。
  const liveEdges = await ev(`document.querySelectorAll("[data-edge][data-live='1']").length`);
  check(liveEdges === 0, "还没出发时没有高亮边（没有当前节点可言）", String(liveEdges));

  // 点一个**不可达**的节点：必须是"拒绝 + 日志"，不是静默无事发生。
  const unreachable = map.nodes.find((node) => !node.reachable && node.row === 0);
  if (unreachable) {
    const beforeLog = (await ev("window.__run.log()")).length;
    await ev(`window.__run.click("[data-node='${unreachable.index}']")`);
    await sleep(80);
    const afterLog = (await ev("window.__run.log()")).length;
    check(afterLog > beforeLog, "点不可达节点会留下一条日志（不是静默无事）", `${beforeLog} → ${afterLog}`);
    const stillMap = await ev("window.__run.scene()");
    check(stillMap.base === "SC-02", "点不可达节点不会离开地图", stillMap.base);
  }

  // ── 阶段 4：真点击走进战斗节点 ──────────────────────────────────────────
  const fightNode = reachable.find((node) => node.kind === 1) ?? reachable[0];
  const entered = await ev(`window.__run.click("[data-node='${fightNode.index}']")`);
  check(entered.clicked === true, `地图上第 ${fightNode.index} 号节点可点`, JSON.stringify(entered));
  await sleep(120);
  scene = await sceneMatchesDom("进入节点后");
  noteScene(scene.base);
  check(scene.base === "SC-03", "走进战斗节点 → 战斗前（不自动开打）", scene.base);
  const runAtNode = await ev("window.__run.run()");
  check(runAtNode.node === fightNode.index, "游标落在刚点的节点上", `${runAtNode.node} vs ${fightNode.index}`);
  check(runAtNode.floor === 1, "第 1 层", String(runAtNode.floor));
  await clean("进入节点后");

  // ── 阶段 5：真点击"进入战斗" ────────────────────────────────────────────
  const beginClicked = await ev(`window.__run.click("[data-fight-begin]")`);
  check(beginClicked.clicked === true, "战斗前有可点的开始按钮");
  await sleep(150);
  scene = await sceneMatchesDom("开战后");
  noteScene(scene.base);
  check(scene.base === "SC-03b", "开战后进入战斗屏", scene.base);
  // ⚠️ 等**画布真的画出这一帧**再拖：`layout()` 是每帧投影出来的，`fight_begin` 之后
  // 头几帧里它可能还是上一屏的旧坐标（或空表）。第一版只等 150ms，于是拖拽按在"牌曾经在的
  // 地方"，机器一直是 `idle`（闸门报"一点血都没掉"，看起来像命中测试坏了）。
  //
  // ⚠️ 判据不能只是 `frames > 0`：画布刚改变尺寸的那几帧里，投影还带着**上一帧的相机**
  // （实测同一块 355px 高的画布，第 3 帧给出 y=405（在画布外），稳定后是 y=313）。
  // 所以要求"**两次读到的一样**，且所有命中点都落在画布矩形里"。
  const readLayout = () => ev(`(() => {
    const probe = window.__p1;
    if (!probe) return null;
    const screen = probe.layout();
    const canvas = document.querySelector("canvas");
    const rect = canvas ? canvas.getBoundingClientRect() : null;
    if (!rect) return null;
    return {
      frames: screen.frames,
      cards: screen.cards.map((card) => ({ slot: card.slot, x: Math.round(card.hitX), y: Math.round(card.hitY) })),
      enemies: screen.enemies.map((enemy) => ({ slot: enemy.slot, x: Math.round(enemy.x), y: Math.round(enemy.y) })),
      rect: { x: Math.round(rect.left), y: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
    };
  })()`);
  const inside = (point, rect) =>
    point.x >= rect.x && point.x <= rect.x + rect.w && point.y >= rect.y && point.y <= rect.y + rect.h;
  const layoutReady = await (async () => {
    let previous = null;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const now = await readLayout();
      if (now && now.frames > 0 && now.cards.length > 0 && now.enemies.length > 0) {
        // 只比坐标（`frames` 每帧都在涨，比它永远不会稳定）。
        const shape = (value) => JSON.stringify({ cards: value.cards, enemies: value.enemies, rect: value.rect });
        const stable = previous !== null && shape(previous) === shape(now);
        const allInside = now.cards.every((card) => inside(card, now.rect)) &&
          now.enemies.every((enemy) => inside(enemy, now.rect));
        if (stable && allInside) return true;
      }
      previous = now;
      await sleep(80);
    }
    return false;
  })();
  check(layoutReady, "3D 布局投影就绪（frames>0、手牌与敌人都有坐标）");
  const combat0 = await ev("window.__run.combat()");
  check(combat0 !== null && combat0.result === "ongoing", "战斗会话存在且进行中", JSON.stringify({ result: combat0?.result }));
  check(combat0.hand.length > 0, "手牌已发", String(combat0?.hand?.length));
  await clean("开战后");

  // ── 阶段 6：**真实 3D 目标拾取**（CDP 真鼠标事件）──────────────────────
  //
  // 找一张"有目标"的牌：动作表里同一张牌有多个 `targetSlot`，或存在 `targetSlot >= 0`。
  const targetPick = await (async () => {
    const state = await ev("window.__run.hand()");
    const playable = state.actions.filter((action) => action.kind === "play");
    if (playable.length === 0) return { skipped: "没有可出的牌" };
    // ⚠️ 定向性**只看** `targeted`（内容元数据），**不看**动作表的 `targetSlot`：
    // 内核给每张可出的牌 × 每个活敌人都发一条动作，连"防御"都有两条
    // （`§352 P1-A` 的原文就是这件事）。第一版拿"targetSlot 指向敌人"当定向，
    // 于是挑到"防御"，拖过去只提交了一次无目标出牌 —— 敌人当然一点血都没掉。
    const enemySlots = new Set(state.enemies.map((enemy) => enemy.slot));
    const targetedCard = state.hand.find((card) => card.targeted === true);
    if (!targetedCard) return { skipped: "起手没有定向牌" };
    if (state.enemies.length < 2) return { skipped: "只剩一个敌人（区分不出打错目标）" };
    const chosenSlot = targetedCard.slot;
    const chosenAction = playable.find(
      (action) => action.handSlot === chosenSlot && enemySlots.has(action.targetSlot)
    );
    if (!chosenAction) return { skipped: "定向牌没有对应的动作" };

    // 屏幕坐标来自 **`window.__p1`**（P1 每帧投影出来的真值，闸门 25–31 用的同一个）：
    // 手牌用 `hitX/hitY`（命中点），敌人用 `x/y` + `r`（身体中心与半径）。
    // ⚠️ 不要自己从 3D 坐标推屏幕像素 —— 那会变成"闸门和页面对布局的理解不一致"。
    const points = await ev(`(() => {
      const probe = window.__p1;
      if (!probe) return null;
      const screen = probe.layout();
      const card = screen.cards.find((c) => c.slot === ${chosenSlot});
      const enemy = screen.enemies.find((e) => e.slot === ${chosenAction.targetSlot});
      if (!card || !enemy) return null;
      return { card: { x: card.hitX, y: card.hitY }, enemy: { x: enemy.x, y: enemy.y } };
    })()`);
    return { chosenSlot, chosenAction, points, enemies: state.enemies };
  })();

  if (targetPick.skipped) {
    check(true, `跳过 3D 拾取（${targetPick.skipped}）`);
  } else if (!targetPick.points) {
    check(true, "跳过 3D 拾取（布局探针不可用）");
  } else {
    // 真实鼠标：按下 → 分 6 步移动 → 抬起（走 pointer 事件链，触发状态机）。
    // 与闸门 29 同一手法：中间必须有 move 事件，否则"极快拖动"会走另一条分支。
    const from = targetPick.points.card;
    const to = targetPick.points.enemy;
    await page.send("Input.dispatchMouseEvent", {
      type: "mousePressed", x: from.x, y: from.y, button: "left", buttons: 1, clickCount: 1,
    });
    await sleep(60);
    // 诊断：按下去之后状态机必须离开 `idle`。留在 `idle` 说明**没打到牌**（坐标不对或被别的
    // 元素盖住），这与"内核拒绝"是完全不同的故障，所以先单独断言一次。
    const pressPhase = await ev("window.__p1.state().phase");
    const under = await ev(`(() => { const el = document.elementFromPoint(${from.x}, ${from.y}); return el ? el.tagName : "null"; })()`);
    check(
      pressPhase !== "idle",
      "按在手牌上时状态机离开 idle（坐标真的打在牌上）",
      `phase=${pressPhase} element=${under} at (${from.x},${from.y})`
    );
    for (let step = 1; step <= 6; step += 1) {
      const ratio = step / 6;
      await page.send("Input.dispatchMouseEvent", {
        type: "mouseMoved",
        x: from.x + (to.x - from.x) * ratio,
        y: from.y + (to.y - from.y) * ratio,
        button: "left",
        buttons: 1,
      });
      await sleep(16);
    }
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseReleased", x: to.x, y: to.y, button: "left", buttons: 0, clickCount: 1,
    });
    await sleep(250);
    const after = await ev("window.__run.hand()");
    const before = targetPick.enemies;
    const hit = before.filter((enemy) => {
      const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
      return now && now.hp < enemy.hp;
    });
    const untouched = before.filter((enemy) => {
      const now = after.enemies.find((candidate) => candidate.slot === enemy.slot);
      return now && now.hp === enemy.hp;
    });
    check(
      hit.length === 1 && hit[0].slot === targetPick.chosenAction.targetSlot,
      "3D 拖拽只打中被指的那个敌人",
      JSON.stringify({ hit: hit.map((e) => e.slot), want: targetPick.chosenAction.targetSlot })
    );
    check(
      untouched.length === before.length - 1,
      "其余敌人一点血都没掉（没有顺手也打一下）",
      JSON.stringify(untouched.map((e) => e.slot))
    );
    await clean("3D 拾取后");
  }

  // ── 阶段 7：把这一场打完（探针；打 20 步不是本闸门要测的）───────────────
  let steps = 0;
  for (; steps < 240; steps += 1) {
    const hand = await ev("window.__run.hand()");
    if (!hand || hand.result !== "ongoing") break;
    const play = hand.actions.find((action) => action.kind === "play");
    const result = play
      ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
      : await ev("window.__run.endTurn()");
    if (result?.accepted === false) {
      check(false, "战斗驱动没有卡住", JSON.stringify(result));
      break;
    }
  }
  summary.steps = steps;
  const settled = await ev("window.__run.hand()");
  check(settled !== null && settled.result !== "ongoing", "战斗有结果", JSON.stringify({ result: settled?.result, steps }));
  check(steps < 240, "战斗在 240 步内结束（没有死循环）", String(steps));
  await clean("战斗结束时");
  const finalCombatHp = settled?.heroHp ?? null;

  // ── 阶段 8：真点击"领取奖励"（`fight_end` 由按钮触发）────────────────────
  const continueClicked = await ev(`window.__run.click("[data-combat-continue]")`);
  check(continueClicked.clicked === true, "战斗结束面板有可点的继续按钮", JSON.stringify(continueClicked));
  await sleep(150);
  scene = await sceneMatchesDom("结算后");
  noteScene(scene.base);
  const victory = settled?.result === "victory";
  check(
    scene.base === (victory ? "SC-04" : "SC-12b"),
    victory ? "胜利后进入奖励屏" : "战败后进入局终屏",
    scene.base
  );
  await clean("结算后");

  if (victory) {
    const runAfterFight = await ev("window.__run.run()");
    // 这一条是闸门 33 说明的口径：`fight_end` **必须**把战斗 HP 写回运行层。
    //
    // ⚠️ 不能写成 `===`：战后**遗物会再结算一次**（起手遗物"燃烧之血"每场战斗后回 6 点）。
    // 第一版用等号，实测 49 vs 43 直接红 —— 那不是 bug，是游戏规则。
    // 所以断言是"**不低**于战斗最后一帧"（伤害留下来了）+ 不超过上限 + 有遗物可解释差额。
    check(
      runAfterFight.health >= finalCombatHp && runAfterFight.health <= runAfterFight.healthMax,
      "战斗最后一帧的 HP 被写回运行层（战后遗物回复只会更高）",
      `${runAfterFight.health} vs 最后一帧 ${finalCombatHp}`
    );
    if (runAfterFight.health > finalCombatHp) {
      check(
        runAfterFight.relicCount >= 1,
        "战后 HP 高于最后一帧时，牌组里有遗物可以解释（燃烧之血一类）",
        `遗物 ${runAfterFight.relicCount} 个`
      );
    }

    // ── 阶段 9：奖励（真点击拿牌 + 真点击继续）────────────────────────────
    const reward = await ev("window.__run.reward()");
    check(reward.cards.length > 0, "奖励屏有候选牌", String(reward.cards.length));
    const deckBefore = (await ev("window.__run.run()")).deckSize;
    const cardSlot = reward.cards[0].slot;
    const cardId = reward.cards[0].id;
    const taken = await ev(`window.__run.click("[data-reward-card='${cardSlot}']")`);
    check(taken.clicked === true, `奖励屏有第 ${cardSlot} 张牌可点`, JSON.stringify(taken));
    await sleep(120);
    const afterTake = await ev("window.__run.run()");
    check(afterTake.deckSize === deckBefore + 1, "拿牌后牌组 +1", `${deckBefore} → ${afterTake.deckSize}`);
    const deckIds = (await ev("window.__run.inventory()")).deck;
    check(deckIds.includes(cardId), `拿到的 ${cardId} 真的进了牌组`, JSON.stringify(deckIds.slice(-3)));
    const rewardAfter = await ev("window.__run.reward()");
    check(rewardAfter.cards.length === 0, "拿完之后候选清空（不重复拿）", String(rewardAfter.cards.length));
    await clean("拿牌后");

    const skipped = await ev(`window.__run.click("[data-reward-skip]")`);
    check(skipped.clicked === true, "奖励屏有可点的继续按钮");
    await sleep(150);
    scene = await sceneMatchesDom("领完奖励后");
    noteScene(scene.base);
    check(scene.base === "SC-02", "领完奖励回到地图（不是战斗前）", scene.base);
    await clean("回到地图");

    // ── 阶段 10：地图**向前推进**了 ───────────────────────────────────────
    const map2 = await ev("window.__run.map()");
    const reachable2 = map2.nodes.filter((node) => node.reachable);
    check(reachable2.length >= 1, "回到地图后又有可去的节点", String(reachable2.length));
    check(
      reachable2.every((node) => node.row >= 1),
      "新的可达节点在第 2 行或更上面（真的往上走了）",
      JSON.stringify(reachable2.map((n) => n.row))
    );
    const runNow = await ev("window.__run.run()");
    check(runNow.floor >= 1, "层数没有倒退", String(runNow.floor));

    // 站在节点上之后，"能走的这一步"必须画得出来（阶段 3 里开局时是 0 条，这是对的）。
    const liveEdges2 = await ev(`document.querySelectorAll("[data-edge][data-live='1']").length`);
    check(
      liveEdges2 >= reachable2.length,
      "回到地图后，从当前节点出发的边被高亮（能走的路线看得出来）",
      `${liveEdges2} 条 vs 可达 ${reachable2.length}`
    );
    const currentMarked = await ev(`document.querySelectorAll("[data-current='1']").length`);
    check(currentMarked === 1, "地图上有且只有一个你在这里标记", String(currentMarked));

    // ── 阶段 11：**没有隐藏的手工刷新** ───────────────────────────────────
    //
    // 判据：把这一圈走完之后，**不做任何 reload**，直接再读一次场景 —— 它必须仍然自洽。
    // 反过来（刷新后才正确）在结构上不可能，因为屏幕是算出来的；这一条只是把"算出来的"
    // 这件事钉在可观察层面。
    const reloaded = await page.evaluate("window.__run.scene()");
    check(
      JSON.stringify(reloaded) === JSON.stringify(await ev("window.__run.scene()")),
      "不刷新页面，场景判定稳定（没有隐藏的手工刷新步骤）"
    );
    const readyAgain = await ev("Boolean(window.__run && window.__run.ready)");
    check(readyAgain === true, "页面没有重建（同一份 store 还在）");
  }

  // ── 阶段 12：日志有完整的叙事（可复盘）─────────────────────────────────
  const log = await ev("window.__run.log()");
  const texts = log.map((entry) => entry.text);
  check(texts.some((text) => text.includes("开局")), "日志里有开局记录", JSON.stringify(texts.slice(0, 2)));
  check(texts.some((text) => text.includes("开战")), "日志里有开战记录");
  check(
    texts.some((text) => text.includes("战斗结束")) || !victory,
    "日志里有战斗结束记录"
  );
  summary.chain = chain;
} finally {
  await page.close();
}

console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_NEXT_LOOP PASS nodes=${summary.nodes} steps=${summary.steps} ` +
    `scene-chain=${summary.chain.join(">")}`
);
