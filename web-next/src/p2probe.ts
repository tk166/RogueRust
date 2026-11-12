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
  rewardCards: () => unknown;
  /** X 费夹具：打赢第一场 → 奖励里挑一张 X 费牌 → 走到下一场战斗，并把 X 费牌抽到手。 */
  xCardFixture: (seed: number) => unknown;
  /** 直接推进到奖励屏（不挑牌），用于扫描"哪个种子的奖励里有 X 费牌"。 */
  scanReward: (seed: number) => unknown;
  run: () => unknown;
  findPlay: (handSlot: number, targetSlot: number) => unknown;
}

/** X 费牌的**基础 id**（内容里 5 张，各带 `+` 变体）。 */
const X_COST_IDS = new Set([
  "whirlwind",
  "skewer",
  "malaise",
  "transmutation",
  "conjure_blade",
]);

/** 把当前战斗打到有结果（上限 200 步，超过就是驱动卡住）。 */
function playOutFight(host: WasmHost): { result: string; turns: number } {
  const store = new GameStore(host);
  let turns = 0;
  for (let step = 0; step < 200; step += 1) {
    const snapshot = store.getSnapshot();
    if (!snapshot) return { result: "no-session", turns };
    if (snapshot.result !== "ongoing") return { result: snapshot.result, turns };
    const action =
      snapshot.actions.find((a) => a.kind === "play" && a.targetSlot >= 0) ??
      snapshot.actions.find((a) => a.kind === "play") ??
      snapshot.actions.find((a) => a.kind === "endTurn");
    if (!action) return { result: "stuck", turns };
    if (action.kind === "endTurn") turns += 1;
    store.dispatch(action);
  }
  return { result: "timeout", turns };
}

/** 从"刚结束一场战斗"走到"站在下一个战斗节点并开打"。返回 `fight_begin` 的返回码。 */
function walkToFight(host: WasmHost): number {
  for (let hop = 0; hop < 60; hop += 1) {
    const raw = host.runRaw();
    if (raw.over === 1) return -1;
    if (raw.pending === 0) {
      if (raw.nodeKind >= 0 && raw.nodeResolved === 0) {
        const isFight = raw.nodeKind === 1 || raw.nodeKind === 2 || raw.nodeKind === 7;
        if (isFight) return host.fightBegin();
        host.beginNode();
        continue;
      }
      if (host.runStep(0) !== 0) return -2;
      continue;
    }
    if (!host.settlePendingRun()) return -3;
  }
  return -4;
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

  async load(url = "./rd_wasm.wasm", manifestUrl?: string) {
    try {
      state.host = await WasmHost.load(url, manifestUrl ? { manifestUrl } : {});
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

  rewardCards: () => state.host?.rewardCards() ?? null,

  /**
   * 扫描：开局 → 走到战斗 → 打赢 → 返回奖励候选。
   *
   * 用于找"哪个种子的奖励里有 X 费牌"（X 费牌不在起手牌、药水也不给）。
   */
  scanReward(seed: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const started = probe.startFight(seed) as { fightCode: number; trail: unknown[] };
    if (started.fightCode !== 0) return { seed, error: "fight_begin 失败", code: started.fightCode };
    const played = playOutFight(host);
    // ⚠️ 打赢之后**还要** `fight_end()` 才会生成奖励屏（`pending 4`）；不调的话
    // `reward_card_count()` 是 0、gold 是 0（第一版就是这么空着的）。
    const endCode = played.result === "victory" ? host.fightEnd() : -1;
    return {
      seed,
      result: played.result,
      endCode,
      pending: host.run().pending,
      offers: host.rewardCards(),
      gold: host.rewardGold(),
    };
  },

  /**
   * X 费夹具：**确定性**地把一张 X 费牌弄进手牌。
   *
   * 为什么不用药水：X 费牌被排除在"随机攻击/技能牌"候选之外（扫过 28 组都没有）。
   * 唯一入口是战斗奖励屏（`rd_run_take_card`）。
   */
  xCardFixture(seed: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const trail: unknown[] = [];

    const started = probe.startFight(seed) as { fightCode: number; trail: unknown[] };
    trail.push({ step: "firstFight", code: started.fightCode });
    if (started.fightCode !== 0) return { ok: false, trail, why: "fight_begin 失败" };

    const first = playOutFight(host);
    trail.push({ step: "playOutFirst", result: first.result, turns: first.turns });
    if (first.result !== "victory") return { ok: false, trail, why: "第一场没打赢" };
    // 打赢后必须 `fight_end()` 才生成奖励屏。
    const endCode = host.fightEnd();
    trail.push({ step: "fightEnd", code: endCode, pending: host.run().pending });

    const offers = host.rewardCards();
    trail.push({ step: "reward", offers: offers.map((card) => card.id) });
    const xCost = offers.find((card) => X_COST_IDS.has(card.id.replace(/\+$/, "")));
    if (!xCost) return { ok: false, trail, why: "奖励里没有 X 费牌" };
    const taken = host.takeCard(xCost.slot);
    trail.push({ step: "takeCard", id: xCost.id, code: taken });
    if (taken !== 0) return { ok: false, trail, why: "拿牌失败" };

    // 拿完牌 → 关掉奖励屏 → 走到下一个战斗节点 → 开打
    host.skipReward();
    const second = walkToFight(host);
    trail.push({ step: "secondFight", code: second });
    if (second !== 0) return { ok: false, trail, why: "第二场 fight_begin 失败" };

    state.store = new GameStore(host);
    // 抽到那张 X 费牌为止（结束回合会重抽；上限 12 回合，超过就是"抽不到"）
    let turns = 0;
    let found: { slot: number; cost: number | "X" } | null = null;
    while (turns < 12) {
      const snapshot = state.store.getSnapshot();
      if (!snapshot) break;
      if (snapshot.result !== "ongoing") break;
      const names = snapshot.hand.map((card) => ({ slot: card.slot, id: host.cardName(card.slot), cost: card.cost }));
      const hit = names.find((card) => X_COST_IDS.has(card.id.replace(/\+$/, "")));
      if (hit) {
        found = { slot: hit.slot, cost: hit.cost };
        break;
      }
      const endTurn = state.store.findEndTurn();
      if (!endTurn) break;
      state.store.dispatch(endTurn);
      turns += 1;
    }
    trail.push({ step: "draw", turns, found });
    return {
      ok: found !== null,
      trail,
      xCard: found,
      energy: state.store.getSnapshot()?.hero.energy ?? null,
      snapshot: summarise(),
    };
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
