// P2 的适配器探针：一个**只做接线**的页面，不画 3D。
//
// 为什么单独一页而不是塞进主页面：闸门 28 要证明的是"ABI 接线正确"（装载校验、观察解码、
// 动作表、走一步、拒绝不改状态、胜负结算）。把它和渲染混在一起，红了就分不清是 ABI 错了
// 还是渲染错了。主页面在 P2 的第二步才换成真实数据源。

import { WasmHost, WasmMismatch, STEP_ACCEPTED } from "./wasm/host";
import { GameStore } from "./wasm/store";

interface P2Probe {
  ready: true;
  load: (url?: string) => Promise<unknown>;
  diagnostics: () => unknown;
  startFight: (seed: number) => unknown;
  snapshot: () => unknown;
  actions: () => unknown;
  dispatch: (handSlot: number, targetSlot: number) => unknown;
  endTurn: () => unknown;
  stepRaw: (index: number) => unknown;
  names: () => unknown;
  potions: () => unknown;
  usePotion: (slot: number, target: number) => unknown;
  choice: () => unknown;
  choicePick: (index: number, on: boolean) => unknown;
  choiceClear: () => unknown;
  choiceConfirm: () => unknown;
  beats: () => unknown;
  run: () => unknown;
  findPlay: (handSlot: number, targetSlot: number) => unknown;
}

const state: {
  host: WasmHost | null;
  store: GameStore | null;
  error: string | null;
} = { host: null, store: null, error: null };

/** 摘要：只把闸门要断言的东西拿出来，避免整份快照过桥（148 格 × 多次很啰嗦）。 */
function summarise() {
  const store = state.store;
  if (!store) return null;
  const snapshot = store.getSnapshot();
  if (!snapshot) return null;
  return {
    round: snapshot.round,
    turn: snapshot.turn,
    phase: snapshot.phase,
    result: snapshot.result,
    hero: snapshot.hero,
    handCount: snapshot.handCount,
    hand: snapshot.hand,
    enemies: snapshot.enemies,
    piles: snapshot.piles,
    actionCount: snapshot.actions.length,
    actions: snapshot.actions.slice(0, 40),
    accepted: store.acceptedActions,
  };
}

function requireStore(): GameStore {
  if (!state.store) throw new Error("先 load()");
  return state.store;
}

function describeResult(result: ReturnType<GameStore["dispatch"]>) {
  return {
    accepted: result.accepted,
    code: result.code,
    unchanged: result.unchanged,
    reason: result.reason,
    action: result.action,
    heroHp: result.after.hero.hp,
    heroEnergy: result.after.hero.energy,
    handCount: result.after.handCount,
    result: result.after.result,
  };
}

const probe: P2Probe = {
  ready: true,

  async load(url = "./rd_wasm.wasm") {
    try {
      state.host = await WasmHost.load(url);
      state.store = new GameStore(state.host);
      state.error = null;
      return { ok: true, diagnostics: state.host.diagnostics };
    } catch (error) {
      state.error = error instanceof Error ? error.message : String(error);
      return {
        ok: false,
        error: state.error,
        diagnostics: error instanceof WasmMismatch ? error.diagnostics : null,
      };
    }
  },

  diagnostics: () => state.host?.diagnostics ?? null,

  /**
   * 从"没有局"一路走到**第一回合的战斗**：开局 → 选祝福 → 走到战斗节点 → `fight_begin`。
   *
   * 每一步的返回码都返回出去，闸门据此断言"真的到了战斗"，而不是"看起来像战斗"。
   */
  /**
   * 从"没有局"走到**站在未结算的战斗节点上**，再 `fight_begin`。
   *
   * 移植自 `native/ui_abi_dump.mjs` 的 `walkToFightNode` + `settleHere`（那条路径是 P0 用
   * 真实 wasm 跑出来的，不是猜的）。关键顺序：**每跳顶部先看 `pending`**，站在未结算节点上
   * 才 `begin_node` —— 反过来就会"落到商店那格立刻 leave 掉"或卡在选牌屏。
   */
  startFight(seed: number, potionId?: string) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const trail: unknown[] = [];
    host.startRun(seed, 0);
    trail.push({ step: "start", run: host.run() });
    // 夹具：先把药水塞进背包，进战斗后再喝 —— 这样能造出**真实**的问句局面
    // （Elixir / Liquid Memories 一类会问"要消耗/取回哪几张"）。
    if (potionId) {
      trail.push({ step: "grantPotion", id: potionId, code: host.grantPotion(potionId) });
    }

    const fightNodeKinds = new Set([1, 2, 7]); // monster / elite / boss
    const isFightNode = () => {
      const raw = host.runRaw();
      if (fightNodeKinds.has(raw.nodeKind)) return true;
      // 事件引来的伏击（`?` 房）：kind 5 且 observe(18) === 2
      return raw.nodeKind === 5 && raw.eventFight > 0;
    };

    for (let hop = 0; hop < 40; hop += 1) {
      const raw = host.runRaw();
      if (raw.over === 1) break;
      if (raw.pending === 0) {
        if (raw.nodeKind >= 0 && raw.nodeResolved === 0) {
          if (isFightNode()) break; // 站到战斗节点上了
          host.beginNode();
          trail.push({ step: "beginNode", run: host.run() });
          continue;
        }
        // 没有未结算节点：走一步（选第一个可用动作）
        if (host.runStep(0) !== 0) break;
        continue;
      }
      // 非战斗的 pending：用最小动作 settle 掉（实现搬到了 host，导出不外泄）
      const settled = host.settlePendingRun();
      trail.push({ step: "settle", pending: raw.pending, settled });
      if (!settled) break;
    }

    const fightCode = host.fightBegin();
    trail.push({ step: "fightBegin", code: fightCode, run: host.run() });
    if (fightCode === 0) state.store = new GameStore(host);
    return { trail, fightCode, snapshot: state.store ? summarise() : null };
  },

  snapshot: () => summarise(),
  actions: () => requireStore().actions(),
  run: () => state.host?.run() ?? null,

  findPlay: (handSlot, targetSlot) => requireStore().findPlay(handSlot, targetSlot),

  dispatch(handSlot: number, targetSlot: number) {
    const store = requireStore();
    const action = store.findPlay(handSlot, targetSlot);
    if (!action) {
      return { accepted: false, code: null, unchanged: true, reason: "no-such-action" };
    }
    return describeResult(store.dispatch(action));
  },

  endTurn() {
    const store = requireStore();
    const action = store.findEndTurn();
    if (!action) return { accepted: false, code: null, unchanged: true, reason: "no-end-turn" };
    return describeResult(store.dispatch(action));
  },

  /** 直接按动作表下标走一步（用来制造"非法动作"以验证拒绝不变性）。 */
  stepRaw(index: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const before = host.combatObservation();
    const code = host.step(index);
    const after = host.combatObservation();
    const unchanged =
      before.length === after.length && before.every((value, i) => value === after[i]);
    state.store?.refresh();
    return { code, unchanged, accepted: code === STEP_ACCEPTED };
  },

  potions() {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const count = host.potionCount();
    const out: { index: number; id: string }[] = [];
    for (let index = 0; index < count; index += 1) out.push({ index, id: host.potionId(index) });
    return out;
  },

  usePotion(slot: number, target: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const before = host.combatObservation();
    const code = host.usePotion(slot, target);
    const after = host.combatObservation();
    const unchanged =
      before.length === after.length && before.every((value, i) => value === after[i]);
    state.store?.refresh();
    return { code, unchanged, choice: host.choice(), snapshot: summarise() };
  },

  choice: () => state.host?.choice() ?? null,

  choicePick(index: number, on: boolean) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const code = host.choicePick(index, on);
    return { code, choice: host.choice() };
  },

  choiceClear() {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    return { code: host.choiceClear(), choice: host.choice() };
  },

  choiceConfirm() {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const before = host.combatObservation();
    const code = host.choiceConfirm();
    const after = host.combatObservation();
    const unchanged =
      before.length === after.length && before.every((value, i) => value === after[i]);
    state.store?.refresh();
    return { code, unchanged, choice: host.choice(), snapshot: summarise() };
  },

  beats() {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    return host.beats();
  },

  names() {
    const host = state.host;
    const store = state.store;
    if (!host || !store) throw new Error("先 load()");
    const snapshot = store.getSnapshot();
    if (!snapshot) throw new Error("没有战斗会话");
    return {
      hand: snapshot.hand.map((card) => ({
        slot: card.slot,
        defSlot: card.defSlot,
        name: host.cardName(card.slot),
        text: host.cardText(card.slot),
      })),
      enemies: snapshot.enemies.map((enemy) => ({
        slot: enemy.slot,
        name: host.enemyName(enemy.slot),
      })),
    };
  },
};

(window as unknown as { __p2: P2Probe }).__p2 = probe;
