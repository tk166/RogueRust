// `run.html` 的探针：闸门 34 读**语义**，不读 DOM 内部结构。
//
// 与 P2 的 `probe.ts` 同一纪律：探针只暴露"玩家能看到的决定"和"权威动作的结果"，
// 不暴露组件内部状态。所以闸门可以换布局、换渲染方式，而断言不用改。
//
// ⚠️ 探针里**没有** `setScene` / `forceReward` 这类"造局面"的钩子：P3 的退出条件正是
// "没有隐藏的手工刷新步骤"，一个能直接改场景的钩子会让闸门绕过整个路由。

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
