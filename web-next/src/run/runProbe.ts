// `run.html` 的探针：闸门 34 读**语义**，不读 DOM 内部结构。
//
// 与 P2 的 `probe.ts` 同一纪律：探针只暴露"玩家能看到的决定"和"权威动作的结果"，
// 不暴露组件内部状态。所以闸门可以换布局、换渲染方式，而断言不用改。
//
// ⚠️ 探针里**没有** `setScene` / `forceReward` 这类"造局面"的钩子：P3 的退出条件正是
// "没有隐藏的手工刷新步骤"，一个能直接改场景的钩子会让闸门绕过整个路由。

import { dprCapFor } from "../stage/perf.js";
import cardMeta from "../view/cardMeta.js";
import type { RunStore } from "./RunStore";
import { sceneLabel } from "./scene.js";

export interface RunProbe {
  ready: true;
  /** 场景判定结果（**这是**路由的唯一真相）。 */
  scene(): {
    base: string;
    label: string;
    overlays: string[];
    unknownPending: number | null;
    pending: number;
  };
  /** 运行层观察向量解出来的那一份。 */
  run(): unknown;
  /** 地图：节点 + 连线 + 可达 + 布局（模型，不是像素）。 */
  map(): unknown;
  /** 顶栏/牌组/遗物/药水。 */
  inventory(): unknown;
  /** 奖励屏当前内容。 */
  reward(): unknown;
  /** 祝福候选。 */
  blessings(): unknown;
  /** 对账失败项（空 = 一致）。 */
  violations(): string[];
  /** 战斗快照（`null` = 没有战斗会话）。 */
  combat(): unknown;
  /** 事件日志。 */
  log(): unknown;
  /** P4 的屏（商店/篝火/宝箱/事件/欠账/药水）—— 一次读全，闸门不必逐字段拼。 */
  screens(): unknown;
  /** 战斗中的三个牌堆（没有战斗会话时是空表）。 */
  piles(): unknown;
  /**
   * 冻结状态（`null` = 没冻结）。
   *
   * 第十五轮 Review §2：以前"界面已冻结"只是横幅上的一句话，操作层并不拦。现在
   * `RunStore` 的每个动作入口 + `GameStore.dispatchGuard` 都过同一个判据，探针读的就是它。
   */
  frozen(): string | null;
  /** 第几幕（`rd_run_act`，1 起）。 */
  act(): number;
  /** 导出回放脚本（`null` = 内核拒绝）。 */
  exportReplay(): string | null;
  /** 导入回放并逐步对拍。 */
  importReplay(text: string): unknown;
  /** 自动存档：`localStorage` 里那一份的元信息（`null` = 没有/坏）。 */
  autosave(): unknown;
  /** 清掉自动存档（闸门用它验"局终会清"与"坏档被丢"）。 */
  clearAutosave(): unknown;
  /** 幕布状态（`null` = 没有幕布；§2.3 的纯演出）。 */
  curtain(): { act: number; seq: number } | null;
  /** 点一下继续（与点击幕布同一条路）。 */
  dismissCurtain(): unknown;
  /** 夹具（**只在 `?debug`**）：把幕布推到"换到第 act 幕"（只动演出层）。 */
  simulateActChange?(act: number): unknown;
  /** 幕间待选的 Boss 遗物 id（空 = 没有待选）。 */
  bossRelics(): string[];
  /** 取走第 `slot` 件（内核动作）。 */
  takeBossRelic(slot: number): unknown;
  /**
   * 夹具专用（**只在 `?debug` 下存在**）：强制生成一次三选一。
   *
   * 与换幕时走同一个内核入口，只是触发时机由闸门决定（打赢 Boss 没法按需制造）。
   */
  offerBossRelics?(): unknown;
  /**
   * 测试钩子（**只在 `?debug` 下存在**）：注入一条对账违约，把界面推进冻结态。
   *
   * 为什么需要它：闸门 43 要证明"冻结之后所有入口都动不了"，而真实的 ABI 违约没法按需制造。
   * 纪律与 `grantPotion` 一致：只在 debug 页面存在，正式路径没有这个入口。
   */
  injectViolation?(text: string | null): unknown;
  /**
   * P6 的**可复现度量**：视口 / DPR / DPR 上限 / 画布后备像素 / 横向溢出。
   *
   * 放在 `__run` 上（而不是只在战斗屏的 `__p1`）：地图/商店屏也要能量，
   * 而 `__p1` 只有战斗屏挂载时才存在（闸门 39 第一次就是这么炸的）。
   */
  metrics(): unknown;
  /** 待决选牌的问句（`rd_env_choice_*`）；`null` = 没有问句。 */
  choice(): unknown;
  choicePick(index: number, on: boolean): unknown;
  choiceClear(): unknown;
  choiceConfirm(): unknown;
  /** 原始 ABI 事实（诊断用：`activeSlot`/`inFight`/`exists` 三者一起看才能判断会话存在性）。 */
  debug(): unknown;

  // ── 权威动作（与玩家按钮一一对应）────────────────────────────────────────
  start(seed: number, ascension: number): unknown;
  choose(slot: number): unknown;
  enter(index: number): unknown;
  fightBegin(): unknown;
  fightEnd(): unknown;
  takeCard(slot: number): unknown;
  skipReward(): unknown;
  takePotion(): unknown;
  takeRelic(): unknown;
  settleDefault(): unknown;
  endAct(): unknown;

  // ── P4 动作（与玩家按钮一一对应）──────────────────────────────────────────
  buy(kind: string, slot: number): unknown;
  leave(): unknown;
  rest(): unknown;
  smith(index: number): unknown;
  toke(index: number): unknown;
  lift(): unknown;
  dig(): unknown;
  recall(): unknown;
  openChest(): unknown;
  chooseEvent(slot: number): unknown;
  takeEventOffer(slot: number): unknown;
  pickEventCard(index: number): unknown;
  pickBlessingCard(index: number): unknown;
  pickupPickCard(index: number): unknown;
  pickupAddCard(slot: number): unknown;
  pickupSkip(): unknown;
  pickupMaxHp(): unknown;
  usePotion(slot: number, target: number): unknown;
  dropPotion(slot: number): unknown;

  /**
   * 用**真 DOM 点击**走一步（闸门用它证明"玩家点得到"）。
   *
   * `selector` 是 CSS 选择器；找不到就返回 `{ clicked: false }` —— 闸门据此区分
   * "界面没画这个按钮" 与 "点了但内核拒绝"。
   */
  click(selector: string): { clicked: boolean; text: string };
  /** 场景根节点的 `data-scene`（证明画出来的和算出来的一致）。 */
  domScene(): string;
  /** 手牌的可出动作（P3 也要验证 3D 目标拾取在运行层外壳里同样可用）。 */
  hand(): unknown;
  /** 按 (手牌槽位, 目标槽位) 出牌 —— 与 P2 的 `__ui` 探针同一个语义。 */
  play(handSlot: number, targetSlot: number): unknown;
  endTurn(): unknown;
}

declare global {
  interface Window {
    __run?: RunProbe;
  }
}

export function installRunProbe(store: RunStore): void {
  const state = () => store.getState();

  window.__run = {
    ready: true,

    scene() {
      const current = state();
      return {
        base: current.scene.base,
        label: sceneLabel(current.scene.base),
        overlays: [...current.scene.overlays],
        unknownPending: current.scene.unknownPending,
        pending: current.pending,
      };
    },

    run: () => state().run,
    map: () => {
      const current = state();
      if (!current.map) return null;
      return {
        rows: current.map.rows,
        nodes: current.map.nodes.map((node) => ({
          index: node.index,
          row: node.row,
          col: node.col,
          kind: node.kind,
          edges: [...node.edges],
          reachable: node.reachable,
        })),
        layout: Object.fromEntries(current.map.layout),
      };
    },
    inventory: () => ({
      deck: [...state().deck],
      relics: [...state().relics],
      potions: [...state().potions],
    }),
    reward: () => state().reward,
    blessings: () => state().blessings,
    violations: () => [...state().violations],
    combat: () => state().combat,
    log: () => [...state().log],

    screens() {
      const current = state();
      return {
        shop: current.shop,
        rest: current.rest,
        chest: current.chest,
        event: current.event,
        pickup: current.pickup,
        potions: current.potions,
        deck: [...current.deck],
        deckTitles: [...current.deckTitles],
      };
    },

    piles: () => store.piles(),

    frozen: () => store.frozen(),

    act: () => store.getState().act,
    exportReplay: () => store.exportReplay(),
    importReplay(text: string) {
      const outcome = store.importReplay(text);
      return { ...outcome, scene: window.__run!.scene(), run: window.__run!.run() };
    },
    autosave: () => store.resumeInfo(),
    clearAutosave() {
      try {
        window.localStorage.removeItem("rd.autosave");
      } catch {
        /* 忽略 */
      }
      return { autosave: store.resumeInfo() };
    },
    curtain: () => store.getState().curtain,
    dismissCurtain() {
      store.dismissCurtain();
      return { curtain: store.getState().curtain };
    },
    simulateActChange: new URLSearchParams(window.location.search).has("debug")
      ? (act: number) => {
          store.simulateActChange(act);
          return { curtain: store.getState().curtain };
        }
      : undefined,
    bossRelics: () => [...store.getState().bossRelics],
    takeBossRelic(slot: number) {
      const code = store.takeBossRelic(slot);
      return {
        code,
        scene: window.__run!.scene(),
        relics: window.__run!.bossRelics(),
        violations: window.__run!.violations(),
      };
    },
    offerBossRelics: new URLSearchParams(window.location.search).has("debug")
      ? () => {
          const code = store.offerBossRelics();
          return { code, scene: window.__run!.scene(), relics: window.__run!.bossRelics() };
        }
      : undefined,

    // `?debug` 才装（闸门 43 用它注入违约）。
    injectViolation: new URLSearchParams(window.location.search).has("debug")
      ? (text: string | null) => {
          store.injectViolation(text);
          return { frozen: store.frozen(), violations: [...store.getState().violations] };
        }
      : undefined,

    metrics() {
      const canvas = document.querySelector("canvas");
      const rect = canvas?.getBoundingClientRect();
      const width = window.innerWidth;
      const cap = dprCapFor(width);
      return {
        width,
        height: window.innerHeight,
        dpr: window.devicePixelRatio,
        dprCap: cap,
        canvas: canvas && rect
          ? {
              cssWidth: Math.round(rect.width),
              cssHeight: Math.round(rect.height),
              backingWidth: canvas.width,
              backingHeight: canvas.height,
              backingPixels: canvas.width * canvas.height,
            }
          : null,
        overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    },

    choice() {
      const game = store.combat;
      if (!game) return null;
      return game.choice();
    },
    choicePick(index: number, on: boolean) {
      const game = store.combat;
      if (!game) return { code: -1 };
      const code = game.pickChoice(index, on);
      return { code, choice: game.choice() };
    },
    choiceClear() {
      const game = store.combat;
      if (!game) return { code: -1 };
      const code = game.clearChoice();
      return { code, choice: game.choice() };
    },
    choiceConfirm() {
      const game = store.combat;
      if (!game) return { code: -1, accepted: false };
      const outcome = game.confirmChoice();
      store.refresh();
      return { ...outcome, choice: game.choice() };
    },
    debug: () => ({ ...store.hostForCombat.run(), hasCombatSession: store.hostForCombat.hasCombatSession() }),

    start(seed: number, ascension: number) {
      store.startRun(seed, ascension);
      return { scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    choose(slot: number) {
      store.chooseBlessing(slot);
      return { scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    enter(index: number) {
      const outcome = store.enterNode(index);
      return { ...outcome, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    fightBegin() {
      const code = store.fightBegin();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    fightEnd() {
      const code = store.fightEnd();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    takeCard(slot: number) {
      const code = store.takeRewardCard(slot);
      return { code, reward: window.__run!.reward(), violations: window.__run!.violations() };
    },
    skipReward() {
      const code = store.skipReward();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    takePotion() {
      const code = store.takeRewardPotion();
      return { code, reward: window.__run!.reward(), violations: window.__run!.violations() };
    },
    takeRelic() {
      const code = store.takeRewardRelic();
      return { code, reward: window.__run!.reward(), violations: window.__run!.violations() };
    },
    settleDefault() {
      const ok = store.settleDefault();
      return { ok, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },

    endAct() {
      const code = store.endAct();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    buy(kind: string, slot: number) {
      const code = store.buy(kind as "card" | "relic" | "potion" | "colorless", slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    leave() {
      const code = store.leave();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    rest() {
      const code = store.rest();
      return { code, scene: window.__run!.scene(), run: window.__run!.run(), violations: window.__run!.violations() };
    },
    smith(index: number) {
      const code = store.smith(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    toke(index: number) {
      const code = store.toke(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    lift() {
      const code = store.lift();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    dig() {
      const code = store.dig();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    recall() {
      const code = store.recall();
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    openChest() {
      const code = store.openChest();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    chooseEvent(slot: number) {
      const code = store.chooseEvent(slot);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    takeEventOffer(slot: number) {
      const code = store.takeEventOffer(slot);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickEventCard(index: number) {
      const code = store.pickEventCard(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickBlessingCard(index: number) {
      const code = store.pickBlessingCard(index);
      return { code, scene: window.__run!.scene(), violations: window.__run!.violations() };
    },
    pickupPickCard(index: number) {
      const code = store.pickupPickCard(index);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupAddCard(slot: number) {
      const code = store.pickupAddCard(slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupSkip() {
      const code = store.pickupSkip();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    pickupMaxHp() {
      const code = store.pickupMaxHp();
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    usePotion(slot: number, target: number) {
      const code = store.usePotion(slot, target);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },
    dropPotion(slot: number) {
      const code = store.dropPotion(slot);
      return { code, screens: window.__run!.screens(), violations: window.__run!.violations() };
    },

    click(selector: string) {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element) return { clicked: false, text: "" };
      const text = element.textContent ?? "";
      element.click();
      return { clicked: true, text };
    },

    domScene() {
      const root = document.querySelector<HTMLElement>("[data-scene]");
      return root?.dataset.scene ?? "";
    },

    hand() {
      const snapshot = state().combat;
      if (!snapshot) return null;
      return {
        energy: snapshot.hero.energy,
        energyMax: snapshot.hero.energyMax,
        heroHp: snapshot.hero.hp,
        result: snapshot.result,
        // ⚠️ `targeted` 来自**内容元数据**（与 `view/combatView.ts` 同一个来源），
        // **不是**从动作表的 `targetSlot` 反推：内核为每张可出的牌 × 每个活敌人都发一条动作，
        // 连"防御"都有两条（`§352 P1-A` 记过这件事）。闸门要靠这个字段挑一张真的定向牌。
        hand: snapshot.hand.map((card) => {
          const id = store.hostForCombat.cardName(card.slot);
          const meta = (cardMeta as Record<string, { targeting?: string }>)[id.replace(/\++$/, "")];
          return {
            slot: card.slot,
            cost: card.cost,
            id,
            targeted: meta?.targeting === "singleEnemy",
          };
        }),
        enemies: snapshot.enemies.map((enemy) => ({ slot: enemy.slot, hp: enemy.hp })),
        actions: snapshot.actions.map((action) => ({
          index: action.index,
          kind: action.kind,
          handSlot: action.handSlot,
          targetSlot: action.targetSlot,
        })),
      };
    },

    play(handSlot: number, targetSlot: number) {
      const game = store.combat;
      if (!game) return { accepted: false, why: "没有战斗会话" };
      const action = game.findPlay(handSlot, targetSlot);
      if (!action) return { accepted: false, why: "动作表里没有这一条" };
      const outcome = store.dispatchCombat(action);
      return {
        accepted: outcome.accepted,
        code: outcome.code,
        unchanged: outcome.unchanged,
        scene: window.__run!.scene(),
        violations: window.__run!.violations(),
      };
    },

    endTurn() {
      const game = store.combat;
      if (!game) return { accepted: false, why: "没有战斗会话" };
      const action = game.findEndTurn();
      if (!action) return { accepted: false, why: "没有结束回合的动作" };
      const outcome = store.dispatchCombat(action);
      return { accepted: outcome.accepted, code: outcome.code };
    },
  };
}
