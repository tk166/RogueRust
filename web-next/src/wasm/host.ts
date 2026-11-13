// `WasmHost`：**唯一**碰 `instance.exports` 的地方。
//
// 组件不许直接调导出（plan P2 的退出条件之一）。所以这里把 ABI 收成几个方法：
// 装载与校验、读文本、读观察、读动作表、走一步。上层只看见 `CombatSnapshot` 之类的值对象。
//
// ## 装载校验：失配就**拒绝**，不进入"半可用"状态
//
// 校验四件事（`docs/ui-abi-audit.md` §2）：
// 1. **导出存在**（本文件真的会调的那些）；
// 2. **向量长度由模块自己说**：`rd_env_observe_len()` / `rd_run_observe_len()` 必须等于 ABI 的值
//    —— 不许写死 148/19，也不许"差不多就行"；
// 3. **哨兵语义**：没有局/没有战斗会话时的几个 `-1`/`-3`（这几条都曾经搞错过）；
// 4. **指纹**：wasm 的 sha256 + 内容指纹，记下来供诊断与"是不是同一份构建"。

import {
  decodeAction,
  decodeCombat,
  type Beat,
  type ChoiceKind,
  type ChoiceOption,
  type ChoiceSource,
  type CombatAction,
  type CombatSnapshot,
  type PendingChoice,
} from "./snapshot";

/** ABI 声明的长度。**只用于比对**模块自己报的数（不是写死给解码器用）。 */
export const ABI_RUN_OBSERVE_LEN = 19;
export const ABI_COMBAT_OBSERVE_LEN = 148;

/**
 * 本文件真的会调用的**函数**导出。少一个就没法工作，所以算"必须存在"。
 *
 * ⚠️ `memory` 不在这张表里：它是 `WebAssembly.Memory` **对象**，按"必须是函数"检查会
 * 对每一份 wasm 都报缺 `memory`。单独检查（见 `validate`）。
 */
const REQUIRED_EXPORTS = [
  "rd_content_fingerprint",
  "rd_run_observe_len",
  "rd_run_observe",
  "rd_run_exists",
  "rd_run_seed",
  "rd_run_act",
  "rd_run_ascension",
  "rd_run_pending",
  "rd_run_in_fight",
  "rd_run_over",
  "rd_run_start",
  "rd_run_choose_start",
  "rd_run_begin_node",
  "rd_run_fight_begin",
  "rd_run_fight_end",
  "rd_env_observe_len",
  "rd_env_observe_buf",
  "rd_env_action_count",
  "rd_env_action_kind",
  "rd_env_action_arg",
  "rd_env_step",
  "rd_env_active_slot",
  "rd_env_enemy_overflow",
  "rd_env_choice_pending",
  "rd_env_card_name_len",
  "rd_env_card_name_into",
  "rd_env_card_text_len",
  "rd_env_card_text_into",
  "rd_env_enemy_name_len",
  "rd_env_enemy_name_into",
  "rd_env_scratch_buf",
  "rd_run_grant_potion",
  "rd_run_reward_card_count",
  "rd_run_reward_card_id_len",
  "rd_run_reward_card_id_into",
  "rd_run_reward_card_title_len",
  "rd_run_reward_card_title_into",
  "rd_run_take_card",
  "rd_run_skip_reward",
  "rd_run_reward_gold",
  "rd_run_potion_count",
  "rd_run_potion_id_len",
  "rd_run_potion_id_into",
  "rd_env_use_potion",
  "rd_env_choice_pending",
  "rd_env_choice_source",
  "rd_env_choice_kind",
  "rd_env_choice_min",
  "rd_env_choice_max",
  "rd_env_choice_count",
  "rd_env_choice_copies",
  "rd_env_choice_pick",
  "rd_env_choice_selected",
  "rd_env_choice_clear",
  "rd_env_choice_confirm",
  "rd_env_pile_len",
  "rd_env_pile_card_id_len",
  "rd_env_pile_card_id_into",
  "rd_env_pile_card_title_len",
  "rd_env_pile_card_title_into",
  "rd_env_beat_count",
  "rd_env_beat_field",
  "rd_env_beat_def_len",
  "rd_env_beat_def_into",
  "rd_env_beats_dropped",
] as const;

/** `rd_env_step` 的返回码（`env-abi.md` §5）。 */
export const STEP_ACCEPTED = 0;
export const STEP_REJECTED = -1;
export const STEP_FINISHED = -2;
export const STEP_BROKEN = -3;

export interface WasmDiagnostics {
  readonly ok: boolean;
  readonly problems: readonly string[];
  readonly sha256: string;
  readonly contentFingerprint: string;
  readonly runObserveLen: number;
  readonly combatObserveLen: number;
  readonly exports: number;
}

export class WasmMismatch extends Error {
  readonly diagnostics: WasmDiagnostics;
  constructor(diagnostics: WasmDiagnostics) {
    super(
      "wasm 与 UI 期望的 ABI 不一致：\n  " + diagnostics.problems.join("\n  ")
    );
    this.name = "WasmMismatch";
    this.diagnostics = diagnostics;
  }
}

type Exports = Record<string, unknown> & {
  memory: WebAssembly.Memory;
};

const SCRATCH_CAPACITY = 1024;

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // TS 5.9 的 `Uint8Array` 泛型允许 `SharedArrayBuffer`，而 `digest` 只收 `ArrayBuffer`
  // ⇒ 显式取出 buffer（这里的 bytes 来自 `arrayBuffer()`，一定不是共享内存）。
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export class WasmHost {
  private readonly ex: Exports;
  private readonly decoder = new TextDecoder();
  readonly diagnostics: WasmDiagnostics;

  private constructor(ex: Exports, diagnostics: WasmDiagnostics) {
    this.ex = ex;
    this.diagnostics = diagnostics;
  }

  /**
   * 装载并校验。**校验失败抛 `WasmMismatch`**（带一份可显示的诊断清单）。
   *
   * ⚠️ `manifestUrl`（默认同目录 `wasm.json`）里的 sha256 会与**实际取到的字节**比对：
   * 上一版只把 sha 记进诊断、从不比对（第十四轮 Review P2-A），于是"换了 wasm 但忘了更新
   * manifest"和"dev 载入了旧副本"都不会被发现。
   */
  static async load(
    url: string,
    options: { manifestUrl?: string; fetchImpl?: typeof fetch } = {}
  ): Promise<WasmHost> {
    const fetchImpl = options.fetchImpl ?? fetch;
    const manifestUrl = options.manifestUrl ?? new URL("wasm.json", new URL(url, location.href)).href;
    const response = await fetchImpl(url);
    if (!response.ok) {
      throw new Error(`取 wasm 失败：${url} → HTTP ${response.status}`);
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    const sha256 = await sha256Hex(bytes);

    // ── 单一构建产物：**运行时**比对，而不是只把 sha 记下来 ──────────────────
    const manifestResponse = await fetchImpl(manifestUrl);
    if (!manifestResponse.ok) {
      throw new Error(
        `取 wasm 清单失败：${manifestUrl} → HTTP ${manifestResponse.status}。` +
          "先在 web-next 里跑 `npm run wasm`（把 web/rd_wasm.wasm 同步过来并记 sha256）。"
      );
    }
    const manifest = (await manifestResponse.json()) as { sha256?: string; source?: string };
    if (!manifest.sha256) {
      throw new Error(`wasm 清单缺少 sha256：${manifestUrl}`);
    }
    if (manifest.sha256 !== sha256) {
      throw new Error(
        "wasm 与清单不一致（不是同一份构建产物）：" +
          "\n  清单 " + manifest.sha256.slice(0, 12) + "…（来自 " + (manifest.source ?? manifestUrl) + "）" +
          "\n  实际 " + sha256.slice(0, 12) + "…" +
          "\n  跑 npm run wasm 重新同步，或确认部署没有混用旧副本。"
      );
    }
    const { instance } = await WebAssembly.instantiate(bytes, {});
    const ex = instance.exports as Exports;
    const diagnostics = validate(ex, sha256);
    if (!diagnostics.ok) throw new WasmMismatch(diagnostics);
    return new WasmHost(ex, diagnostics);
  }

  // ── 文本（`_len` / `_into` 一对：先问长度，再写进模块自己的 scratch）──────────
  /**
   * 读一段文本。
   *
   * ⚠️ 参数用**闭包**而不是 `(lenFn, intoFn, arg)`：`_into` 的参数顺序**每个函数都不一样**
   * （`rd_env_card_name_into(index, ptr)` vs `rd_run_boss_id_into(ptr)`），写死一种顺序必然
   * 有一半调反 —— 症状是 `_into` 返回 -1（把槽位当成了指针）。闭包让顺序在调用点显式写出来。
   */
  private readText(getLength: () => number, writeInto: (ptr: number) => number): string {
    const len = getLength();
    if (len <= 0) return "";
    if (len > SCRATCH_CAPACITY) {
      throw new RangeError(`文本 ${len} 字节，超过 1 KiB scratch`);
    }
    const ptr = Number((this.ex.rd_env_scratch_buf as () => number)());
    const written = writeInto(ptr);
    if (written !== len) {
      throw new Error(`_into 写了 ${written} 字节，_len 说 ${len}`);
    }
    return this.decoder.decode(new Uint8Array(this.ex.memory.buffer, ptr, len));
  }

  /** 手牌槽位的**显示名**（presentation only；ABI 冻结的那一半是 `def_slot`）。 */
  cardName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_card_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_card_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  /** 手牌槽位的规则文本。 */
  cardText(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_card_text_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_card_text_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  /** 敌人墙位槽的显示名。 */
  enemyName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_enemy_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_enemy_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  // ── 观察 ──────────────────────────────────────────────────────────────────
  /**
   * 战斗观察向量（**复制**出来）。
   *
   * ⚠️ 必须 `slice()`：`rd_env_observe_buf()` 给的是 `Int32Array` 的地址，`memory.grow` 之后
   * 原来的 View 会失效（`ui-abi-audit.md` §4 的老坑）。
   */
  combatObservation(): Int32Array {
    const len = (this.ex.rd_env_observe_len as () => number)();
    const ptr = Number((this.ex.rd_env_observe_buf as () => number)());
    return new Int32Array(this.ex.memory.buffer, ptr, len).slice();
  }

  runObservation(): Int32Array {
    const len = (this.ex.rd_run_observe_len as () => number)();
    const out = new Int32Array(len);
    const observe = this.ex.rd_run_observe as (index: number) => number;
    for (let index = 0; index < len; index += 1) out[index] = observe(index);
    return out;
  }

  // ── 动作表 ────────────────────────────────────────────────────────────────
  actions(): CombatAction[] {
    const count = (this.ex.rd_env_action_count as () => number)();
    const kind = this.ex.rd_env_action_kind as (index: number) => number;
    const arg = this.ex.rd_env_action_arg as (index: number, which: number) => number;
    const out: CombatAction[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(decodeAction(index, kind(index), arg(index, 0), arg(index, 1)));
    }
    return out;
  }

  /** 一步战斗。返回 `rd_env_step` 的原始返回码（0 接受 / -1 拒绝 / -2 已结束 / -3 坏了）。 */
  step(actionIndex: number): number {
    return (this.ex.rd_env_step as (index: number) => number)(actionIndex);
  }

  // ── 运行层 ────────────────────────────────────────────────────────────────
  run(): {
    exists: boolean;
    seed: number;
    act: number;
    ascension: number;
    pending: number;
    inFight: boolean;
    over: number;
    activeSlot: number;
    choicePending: boolean;
  } {
    const call = (name: string) => (this.ex[name] as () => number)();
    return {
      exists: call("rd_run_exists") === 1,
      seed: call("rd_run_seed"),
      act: call("rd_run_act"),
      ascension: call("rd_run_ascension"),
      pending: call("rd_run_pending"),
      inFight: call("rd_run_in_fight") === 1,
      over: call("rd_run_over"),
      activeSlot: call("rd_env_active_slot"),
      choicePending: call("rd_env_choice_pending") === 1,
    };
  }

  /** 走路需要的运行层字段（比 `run()` 多几个"只有遍历才用"的）。 */
  runRaw(): {
    pending: number;
    nodeKind: number;
    nodeResolved: number;
    over: number;
    eventFight: number;
  } {
    const call = (name: string) => (this.ex[name] as () => number)();
    return {
      pending: call("rd_run_pending"),
      nodeKind: call("rd_run_node_kind"),
      nodeResolved: call("rd_run_node_resolved"),
      over: call("rd_run_over"),
      eventFight: call("rd_run_event_fight"),
    };
  }

  runStep(index: number): number {
    return (this.ex.rd_run_step as (index: number) => number)(index);
  }

  /**
   * 按 `pending` 做**最小结算**（照 `native/ui_abi_dump.mjs` 的 `settleHere`）。
   *
   * `pending` 九档：1 篝火 / 2 商店 / 3 宝箱 / 4 奖励 / 5 事件 / 6 起始祝福 /
   * 7 祝福选牌 / 8 事件选牌 / 9 事件候选。**每一档都要有人处理**，否则走路会卡在那一屏
   * （P2 第一版就卡在 7）。
   *
   * 返回是否结算成功；`pending === 0`（没有待决屏）返回 false —— 那是"该 begin_node/走一步"，
   * 不是"结算"。
   */
  settlePendingRun(): boolean {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    switch (this.runRaw().pending) {
      case 1:
        return call("rd_run_rest") === 0;
      case 2:
        return call("rd_run_leave") === 0;
      case 3:
        call("rd_run_open_chest");
        return call("rd_run_leave") === 0;
      case 4:
        return call("rd_run_skip_reward") === 0;
      case 5:
        return call("rd_run_choose", 0) === 0;
      case 6:
        this.chooseStart(0);
        return true;
      case 7:
        return call("rd_run_pick_blessing_card", 0) === 0;
      case 8:
        return call("rd_run_pick_event_card", 0) === 0;
      case 9:
        return call("rd_run_event_offer_take", 0) === 0;
      default:
        return false;
    }
  }

  startRun(seed: number, ascension: number): void {
    (this.ex.rd_run_start as (seed: number, ascension: number) => void)(seed, ascension);
  }

  chooseStart(index: number): void {
    (this.ex.rd_run_choose_start as (index: number) => void)(index);
  }

  beginNode(): number {
    return (this.ex.rd_run_begin_node as () => number)();
  }

  fightBegin(): number {
    return (this.ex.rd_run_fight_begin as () => number)();
  }

  fightEnd(): number {
    return (this.ex.rd_run_fight_end as () => number)();
  }

  // ── 运行层：地图 / 观察 / 牌组 / 遗物 / 遭遇名 / 动作表（P3 的场景层）──────────
  //
  // 这一组**只做搬运**：把 i32 读出来，不解释语义。语义在 `run/observe.ts`（纯函数、可单测），
  // 场景判定在 `run/scene.ts`（纯函数、可单测）。理由与 P2 的 `snapshot.ts` 一样：
  // 解码是最容易搞错的地方，而它不该需要 wasm 才能测。

  /** 地图节点数（`-1` = 没有局）。 */
  mapLen(): number {
    return (this.ex.rd_run_map_len as () => number)();
  }

  mapRows(): number {
    return (this.ex.rd_run_map_rows as () => number)();
  }

  /**
   * `rd_run_map_node(index, field)`：0 row / 1 col / 2 kind / 3 out_degree /
   * 4..6 出边（**全局下标**）/ 7 reachable。
   *
   * ⚠️ 出边是**全局**下标（`env-abi.md` §11.2 专门解释过为什么不给行内下标）——
   * 这里原样返回，绝不在 UI 里自己加行偏移。
   */
  mapNode(index: number, field: number): number {
    return (this.ex.rd_run_map_node as (index: number, field: number) => number)(index, field);
  }

  /**
   * 走路动作表：`rd_run_action_count()` 是**可达节点个数**，第 `i` 条的 `arg0` 是目标节点
   * 的全局下标。
   *
   * ⚠️ 所以"进入节点 G"必须先在这里找到 `target === G` 的那一条 —— 直接把 G 当
   * `rd_run_step` 的入参是错的（G 是全局下标，`step` 收的是可达表里的**位置**）。
   */
  runActions(): { index: number; kind: number; target: number }[] {
    const count = Number((this.ex.rd_run_action_count as () => number)());
    const out: { index: number; kind: number; target: number }[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push({
        index,
        kind: (this.ex.rd_run_action as (index: number) => number)(index),
        target: (this.ex.rd_run_action_arg as (index: number, which: number) => number)(index, 0),
      });
    }
    return out;
  }

  /** 牌组里的定义 id（`strike` / `bash+` …）。 */
  deckIds(): string[] {
    const count = (this.ex.rd_run_deck_count as () => number)();
    const out: string[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(
        this.readText(
          () => (this.ex.rd_run_deck_id_len as (index: number) => number)(index),
          (ptr) =>
            (this.ex.rd_run_deck_id_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  /**
   * 遗物 id 列表。
   *
   * ⚠️ **没有** `rd_run_relic_count`（内核只导出 `relic_id_len(index)`）⇒ 读到 `-1` 为止。
   * 上限 64 只是防死循环的护栏；真正的条数是运行层观察向量的第 6 格，对账会拿它比。
   */
  relicIds(): string[] {
    const out: string[] = [];
    for (let index = 0; index < 64; index += 1) {
      const len = (this.ex.rd_run_relic_id_len as (index: number) => number)(index);
      if (len < 0) break;
      out.push(
        this.readText(
          () => len,
          (ptr) =>
            (this.ex.rd_run_relic_id_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  /** 当前遭遇的 id（`cultist` / `jaw_worm` …）；没有时是空串。 */
  encounterId(): string {
    const len = (this.ex.rd_run_encounter_id_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) =>
        (this.ex.rd_run_encounter_id_into as (ptr: number) => number)(ptr)
    );
  }

  /** 开局祝福的候选（§346：条数由内核给，**不许**写死 `for slot in 0..2`）。 */
  startOffers(): { slot: number; id: string; gain: number; gainAmount: number; cost: number; costAmount: number }[] {
    const call = (name: string) => (this.ex[name] as () => number)();
    const count = call("rd_run_start_offer_count");
    const out: { slot: number; id: string; gain: number; gainAmount: number; cost: number; costAmount: number }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => (this.ex.rd_run_start_offer_len as (slot: number) => number)(slot),
          (ptr) => (this.ex.rd_run_start_offer_into as (slot: number, ptr: number) => number)(slot, ptr)
        ),
        gain: (this.ex.rd_run_start_gain as (slot: number) => number)(slot),
        gainAmount: (this.ex.rd_run_start_gain_amount as (slot: number) => number)(slot),
        cost: (this.ex.rd_run_start_cost as (slot: number) => number)(slot),
        costAmount: (this.ex.rd_run_start_cost_amount as (slot: number) => number)(slot),
      });
    }
    return out;
  }

  /** 祝福还差什么：0 没有 / 1 删牌 / 2 升级 / 3 变形 / -1 没有局。 */
  blessingNeeds(): number {
    return (this.ex.rd_run_blessing_needs as () => number)();
  }

  /** 遗物欠账：还要改几张牌（`SC-11a`）。 */
  pickupPicks(): number {
    return (this.ex.rd_run_pickup_picks as () => number)();
  }

  /** 遗物欠账欠的是哪一种编辑：`0` 不欠 / `1` 移除 / `2` 升级 / `3` 改造 / `4` 改造并升级。 */
  pickupChange(): number {
    return (this.ex.rd_run_pickup_change as () => number)();
  }

  /** 遗物欠账：还要加几张牌（`SC-11b`）。 */
  pickupAdd(): number {
    return (this.ex.rd_run_pickup_add as () => number)();
  }

  bossBeaten(): boolean {
    return (this.ex.rd_run_boss_beaten as () => number)() === 1;
  }

  /**
   * 局终原因：`RunEnd` 的判别值（`0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了）。
   *
   * ⚠️ 是**数字**不是字符串（`rd_run_over_why` 返回判别值）。数值是 `RunEnd` 的判别值，
   * 不要重排 —— 页面按它选文案（`run/scene.ts` 的 `overReasonLabel`）。
   */
  overWhy(): number {
    return (this.ex.rd_run_over_why as () => number)();
  }

  /** 奖励屏上的药水 id（没有就是空串）。 */
  rewardPotionId(): string {
    const len = (this.ex.rd_run_reward_potion_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_reward_potion_into as (ptr: number) => number)(ptr)
    );
  }

  rewardRelicId(): string {
    const len = (this.ex.rd_run_reward_relic_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_reward_relic_into as (ptr: number) => number)(ptr)
    );
  }

  takePotion(): number {
    return (this.ex.rd_run_take_potion as () => number)();
  }

  takeRelic(): number {
    return (this.ex.rd_run_take_relic as () => number)();
  }

  /**
   * 宣告"这一幕的地图走完了"（`§344` 缺口 G2）。
   *
   * 三条前提（内核判，不是页面判）：没有待决问句 / 脚下节点已结算 / 可达为空。
   * 返回 `0` 接受、`-2` 拒绝（原因在错误缓冲）、`-1` 没有局。
   */
  endAct(): number {
    return (this.ex.rd_run_end_act as () => number)();
  }

  /** 离开当前待决屏（商店/宝箱/篝火都认）。 */
  leave(): number {
    return (this.ex.rd_run_leave as () => number)();
  }

  rest(): number {
    return (this.ex.rd_run_rest as () => number)();
  }

  openChest(): number {
    return (this.ex.rd_run_open_chest as () => number)();
  }

  /** 牌组第 `index` 张的**显示名**（`rd_run_deck_title_*`）。 */
  deckTitles(): string[] {
    const count = (this.ex.rd_run_deck_count as () => number)();
    const out: string[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(
        this.readText(
          () => (this.ex.rd_run_deck_title_len as (index: number) => number)(index),
          (ptr) =>
            (this.ex.rd_run_deck_title_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  // ── 商店（`pending == 2`）────────────────────────────────────────────────
  //
  // 四类货架各有一族 `_count` / `_id_len` / `_id_into` / `_price`。**价格由内核给**
  // （它已经算上会员卡/涨价/§332 的定价规则），页面绝不算价 —— 页面算价必然与内核漂。
  private shelf(
    prefix: string
  ): { slot: number; id: string; price: number }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call(`rd_run_${prefix}_count`);
    const out: { slot: number; id: string; price: number }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => call(`rd_run_${prefix}_id_len`, slot),
          (ptr) => call(`rd_run_${prefix}_id_into`, slot, ptr)
        ),
        price: call(`rd_run_${prefix}_price`, slot),
      });
    }
    return out;
  }

  shopCards(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_card");
  }

  shopRelics(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_relic");
  }

  shopPotions(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_potion");
  }

  /** 无色货架（§332）。 */
  shopColorless(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_colorless");
  }

  /** 现在删一张牌要多少钱（`inv:§8.2`：75，之后每次 +25）。 */
  removePrice(): number {
    return (this.ex.rd_run_remove_price as () => number)();
  }

  /** 这家店的删卡服务还能不能用：`1` 能 / `0` 这家店删过了 / `-1` 没有局（§343）。 */
  removalAvailable(): number {
    return (this.ex.rd_run_removal_available as () => number)();
  }

  buyCard(slot: number): number {
    return (this.ex.rd_run_buy_card as (slot: number) => number)(slot);
  }

  buyRelic(slot: number): number {
    return (this.ex.rd_run_buy_relic as (slot: number) => number)(slot);
  }

  buyPotion(slot: number): number {
    return (this.ex.rd_run_buy_potion as (slot: number) => number)(slot);
  }

  buyColorless(slot: number): number {
    return (this.ex.rd_run_buy_colorless as (slot: number) => number)(slot);
  }

  /** 花钱删牌组第 `index` 张。返回花掉的钱。 */
  removeCard(index: number): number {
    return (this.ex.rd_run_remove_card as (index: number) => number)(index);
  }

  // ── 篝火（`pending == 1`）────────────────────────────────────────────────
  /**
   * 篝火选项的**位掩码**（§259）：`Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 | Dig 32`。
   *
   * ⚠️ 位序是**硬约定**，页面按它读。内核为什么用一个位掩码而不是六个 `is_*` 导出：
   * 一次渲染要全部六个，六个导出是六次往返，而"漏了一个"只表现为那个按钮不出现（静默）。
   */
  campfireOptions(): number {
    return (this.ex.rd_run_campfire_options as () => number)();
  }

  /** 休息能回多少血（已算上 `regal_pillow` +15 与 `eternal_feather` 每 5 张牌 +3）。 */
  restHeal(): number {
    return (this.ex.rd_run_rest_heal as () => number)();
  }

  /** `Girya` 已经举过几次（1..=3）。 */
  giryaLifts(): number {
    return (this.ex.rd_run_girya_lifts as () => number)();
  }

  smith(index: number): number {
    return (this.ex.rd_run_smith as (index: number) => number)(index);
  }

  /** `Peace Pipe`：删掉牌组第 `index` 张。 */
  toke(index: number): number {
    return (this.ex.rd_run_toke as (index: number) => number)(index);
  }

  /** `Shovel`：抽一件遗物（抽到哪件从 `relicIds()` 的增量看）。 */
  dig(): number {
    return (this.ex.rd_run_dig as () => number)();
  }

  lift(): number {
    return (this.ex.rd_run_lift as () => number)();
  }

  /** 拿红钥匙。 */
  recall(): number {
    return (this.ex.rd_run_recall as () => number)();
  }

  // ── 事件（`pending == 5` / `8` / `9`）────────────────────────────────────
  eventId(): string {
    const len = (this.ex.rd_run_event_id_len as () => number)();
    if (len <= 0) return "";
    return this.readText(() => len, (ptr) => (this.ex.rd_run_event_id_into as (ptr: number) => number)(ptr));
  }

  eventText(): string {
    const len = (this.ex.rd_run_event_text_len as () => number)();
    if (len <= 0) return "";
    return this.readText(() => len, (ptr) => (this.ex.rd_run_event_text_into as (ptr: number) => number)(ptr));
  }

  /** 这个事件还差什么：0 没有 / 1 删牌 / 2 升级 / 3 变形（与 `pickup_change` 同一套编码）。 */
  eventNeeds(): number {
    return (this.ex.rd_run_event_needs as () => number)();
  }

  /**
   * 事件按钮。**条数由内容决定**（§278：`golden_idol` 第二段是三选一），
   * **可用性由内核决定**（§279：与 `rd_run_choose` 判的是同一个函数）。
   */
  eventOptions(): {
    slot: number;
    label: string;
    available: boolean;
    effects: { kind: number; amount: number }[];
  }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_event_option_count");
    const out: {
      slot: number;
      label: string;
      available: boolean;
      effects: { kind: number; amount: number }[];
    }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      const effects: { kind: number; amount: number }[] = [];
      const effectCount = call("rd_run_event_effect_count", slot);
      for (let index = 0; index < effectCount; index += 1) {
        effects.push({
          kind: call("rd_run_event_effect_at", slot, index),
          amount: call("rd_run_event_amount_at", slot, index),
        });
      }
      out.push({
        slot,
        label: this.readText(
          () => call("rd_run_event_label_len", slot),
          (ptr) => call("rd_run_event_label_into", slot, ptr)
        ),
        available: call("rd_run_event_option_available", slot) === 1,
        effects,
      });
    }
    return out;
  }

  choose(slot: number): number {
    return (this.ex.rd_run_choose as (slot: number) => number)(slot);
  }

  /** 事件摊开的候选（§320：`The Library` 的 20 选 1、`Sensory Stone`）。 */
  eventOffers(): { slot: number; id: string; title: string }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_event_offer_len");
    const out: { slot: number; id: string; title: string }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => call("rd_run_event_offer_id_len", slot),
          (ptr) => call("rd_run_event_offer_id_into", slot, ptr)
        ),
        title: this.readText(
          () => call("rd_run_event_offer_title_len", slot),
          (ptr) => call("rd_run_event_offer_title_into", slot, ptr)
        ),
      });
    }
    return out;
  }

  eventOfferTake(slot: number): number {
    return (this.ex.rd_run_event_offer_take as (slot: number) => number)(slot);
  }

  /** 事件问句的牌组下标答案（`Pending::EventCard`）。 */
  pickEventCard(index: number): number {
    return (this.ex.rd_run_pick_event_card as (index: number) => number)(index);
  }

  pickBlessingCard(index: number): number {
    return (this.ex.rd_run_pick_blessing_card as (index: number) => number)(index);
  }

  // ── 遗物欠账（`SC-11a`/`SC-11b`，**不走 pending**）──────────────────────
  /** 欠的加牌候选（`orrery` / `tiny_house`）。 */
  pickupOffers(): { slot: number; title: string }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_pickup_offer_count");
    const out: { slot: number; title: string }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        title: this.readText(
          () => call("rd_run_pickup_offer_title_len", slot),
          (ptr) => call("rd_run_pickup_offer_title_into", slot, ptr)
        ),
      });
    }
    return out;
  }

  /** 兑现一次"改牌"欠账（牌组下标）。 */
  pickupCard(index: number): number {
    return (this.ex.rd_run_pickup_card as (index: number) => number)(index);
  }

  pickupAddCard(slot: number): number {
    return (this.ex.rd_run_pickup_add_card as (slot: number) => number)(slot);
  }

  pickupAddSkip(): number {
    return (this.ex.rd_run_pickup_add_skip as () => number)();
  }

  pickupAddMaxHp(): number {
    return (this.ex.rd_run_pickup_add_max_hp as () => number)();
  }

  // ── 药水（腰带）───────────────────────────────────────────────────────────
  /** 药水 `slot` 的用法：`1` 要敌人目标 / `2` 作用于英雄或本局 / `3` 打所有敌人 / `0` 未知。 */
  potionEffect(slot: number): number {
    return (this.ex.rd_run_potion_effect as (slot: number) => number)(slot);
  }

  /** `0` = 战斗外也能用（run-only），`1` = 必须战斗内，`-1` = 没有这个槽。 */
  potionNeedsFight(slot: number): number {
    return (this.ex.rd_run_potion_needs_fight as (slot: number) => number)(slot);
  }

  dropPotion(index: number): number {
    return (this.ex.rd_run_drop_potion as (index: number) => number)(index);
  }

  // ── 战斗中的牌堆浏览（`rd_env_pile_*`）──────────────────────────────────
  /** `zone`：0 抽牌堆 / 1 弃牌堆 / 2 消耗堆。 */
  pileLen(zone: number): number {
    return (this.ex.rd_env_pile_len as (zone: number) => number)(zone);
  }

  pileCard(zone: number, index: number): { id: string; title: string } {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    return {
      id: this.readText(
        () => call("rd_env_pile_card_id_len", zone, index),
        (ptr) => call("rd_env_pile_card_id_into", zone, index, ptr)
      ),
      title: this.readText(
        () => call("rd_env_pile_card_title_len", zone, index),
        (ptr) => call("rd_env_pile_card_title_into", zone, index, ptr)
      ),
    };
  }

  // ── 存档 / 回档（`rd_run_archive_*` / `rd_run_restore_from`）───────────────
  //
  // 档案是**内核**写的文本：`MAGIC-base64-校验和`。所以版本/内容指纹/损坏都由内核判，
  // 页面只负责搬运 —— 页面自己写序列化必然与内核漂（而且回档失败会变成"半新半旧"）。

  /** 档案缓冲容量（`MAX_ARCHIVE`）。超过它内核会拒绝，所以先问再写。 */
  archiveCapacity(): number {
    return (this.ex.rd_run_archive_capacity as () => number)();
  }

  /**
   * 让内核把当前这局写成档案（写进它自己的缓冲），返回长度；`<0` = 拒绝（原因见 `lastError`）。
   *
   * ⚠️ 战斗**不能存档**（`CombatState` 不进档案），这条判断在内核里。
   */
  archiveFill(): number {
    return (this.ex.rd_run_archive_fill as () => number)();
  }

  /** 读回档案文本（`archiveFill` 之后调用）。 */
  readArchive(len: number): string {
    const ptr = Number((this.ex.rd_run_archive_buf as () => number)());
    const bytes = new Uint8Array(this.ex.memory.buffer, ptr, len).slice();
    return this.decoder.decode(bytes);
  }

  /**
   * 从档案文本回档。返回 `0` 成功 / `-1` 没有局 / `-2` 拒绝 / `-3` 坏文本。
   *
   * **全有或全无**：内核先装到本地 `RunState`，最后一步才赋值，所以坏档案不会把当前这局
   * 改成半新半旧。这里把文本写进**内核自己的档案缓冲**再调它，不需要猜 `__heap_base`。
   */
  restoreFrom(text: string): number {
    const bytes = new TextEncoder().encode(text);
    const capacity = this.archiveCapacity();
    if (bytes.length > capacity) return -3;
    const ptr = Number((this.ex.rd_run_archive_buf as () => number)());
    new Uint8Array(this.ex.memory.buffer, ptr, bytes.length).set(bytes);
    return (this.ex.rd_run_restore_from as (ptr: number, len: number) => number)(ptr, bytes.length);
  }

  /** 最近一次拒绝的原因（`rd_run_last_error_*`）。 */
  lastError(): string {
    const len = (this.ex.rd_run_last_error_len as () => number)();
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_last_error_into as (ptr: number) => number)(ptr)
    );
  }

  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */
  kindName(kind: number): string {
    const len = (this.ex.rd_run_kind_name_len as (kind: number) => number)(kind);
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) => (this.ex.rd_run_kind_name_into as (kind: number, ptr: number) => number)(kind, ptr)
    );
  }

  // ── 药水（夹具用：`?debug` 下造"会问句"的局面）──────────────────────────────
  /**
   * 把一段 ASCII 写进模块的 scratch（`rd_env_scratch_buf`）。
   *
   * 存在的理由：`rd_run_grant_potion(ptr, len)` 收的是**指针 + 长度**（不是 `_len/_into` 那一对），
   * 所以调用方得自己把 id 写进它的内存。写 scratch 是唯一不需要猜 `__heap_base` 的办法。
   */
  private writeScratch(text: string): number {
    const bytes = new TextEncoder().encode(text);
    const ptr = Number((this.ex.rd_env_scratch_buf as () => number)());
    if (bytes.length > SCRATCH_CAPACITY) {
      throw new RangeError(`文本 ${bytes.length} 字节，超过 1 KiB scratch`);
    }
    new Uint8Array(this.ex.memory.buffer, ptr, bytes.length).set(bytes);
    return bytes.length;
  }

  /** 给玩家一瓶药水（调试钩子，与旧页面 `?debug` 的 `givePotion` 同一纪律）。 */
  grantPotion(id: string): number {
    const len = this.writeScratch(id);
    const ptr = Number((this.ex.rd_env_scratch_buf as () => number)());
    return (this.ex.rd_run_grant_potion as (ptr: number, len: number) => number)(ptr, len);
  }

  potionCount(): number {
    return (this.ex.rd_run_potion_count as () => number)();
  }

  potionId(index: number): string {
    return this.readText(
      () => (this.ex.rd_run_potion_id_len as (index: number) => number)(index),
      (ptr) => (this.ex.rd_run_potion_id_into as (index: number, ptr: number) => number)(index, ptr)
    );
  }

  /** 喝一瓶药水。`target` 是目标墙位槽（不需要目标的药水传 `-1`）。 */
  usePotion(slot: number, target: number): number {
    return (this.ex.rd_env_use_potion as (slot: number, target: number) => number)(slot, target);
  }

  // ── 战斗奖励屏（`rd_run_reward_*`）—— X 费夹具靠它把牌塞进牌组 ────────────────
  /**
   * 奖励屏上的候选卡（`rd_run_reward_card_*`）。
   *
   * 为什么要它：X 费牌**不在起手牌里**，药水三选一也**不给**（X 费牌被排除在随机候选外，
   * 扫过 28 组）。唯一确定性入口是"打赢一场 → 奖励里挑一张"，所以先得能列出奖励候选。
   */
  rewardCards(): { slot: number; id: string; title: string }[] {
    const call = (name: string) => (this.ex[name] as () => number)();
    const count = call("rd_run_reward_card_count");
    const out: { slot: number; id: string; title: string }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => (this.ex.rd_run_reward_card_id_len as (slot: number) => number)(slot),
          (ptr) => (this.ex.rd_run_reward_card_id_into as (slot: number, ptr: number) => number)(slot, ptr)
        ),
        title: this.readText(
          () => (this.ex.rd_run_reward_card_title_len as (slot: number) => number)(slot),
          (ptr) =>
            (this.ex.rd_run_reward_card_title_into as (slot: number, ptr: number) => number)(slot, ptr)
        ),
      });
    }
    return out;
  }

  rewardGold(): number {
    return (this.ex.rd_run_reward_gold as () => number)();
  }

  /** 拿奖励屏上第 `slot` 张牌（进牌组）。`0` = 成功。 */
  takeCard(slot: number): number {
    return (this.ex.rd_run_take_card as (slot: number) => number)(slot);
  }

  skipReward(): number {
    return (this.ex.rd_run_skip_reward as () => number)();
  }

  // ── 待决选牌（`rd_env_choice_*`）──────────────────────────────────────────
  /**
   * 读当前问句。没有问句返回 `null`。
   *
   * ⚠️ 选项来自 `rd_env_pile_*` 的 **zone 3**（"问句的来源牌区"）：`source === 2`（三选一）时
   * 那三条是**候选定义**、没有牌堆；`source === 1` 时是一个真牌堆。所以"有没有牌堆"必须看
   * `source`，不能拿 `pile_len(3) === 0` 去猜（§161.5 的教训：两个词表各认一半就会漂）。
   */
  choice(): PendingChoice | null {
    const call = (name: string) => (this.ex[name] as () => number)();
    if (call("rd_env_choice_pending") !== 1) return null;
    const count = call("rd_env_choice_count");
    const options: ChoiceOption[] = [];
    const selected = this.ex.rd_env_choice_selected as (index: number) => number;
    for (let index = 0; index < count; index += 1) {
      options.push({
        index,
        id: this.readText(
          () => (this.ex.rd_env_pile_card_id_len as (zone: number, i: number) => number)(3, index),
          (ptr) =>
            (this.ex.rd_env_pile_card_id_into as (zone: number, i: number, ptr: number) => number)(
              3,
              index,
              ptr
            )
        ),
        title: this.readText(
          () => (this.ex.rd_env_pile_card_title_len as (zone: number, i: number) => number)(3, index),
          (ptr) =>
            (this.ex.rd_env_pile_card_title_into as (zone: number, i: number, ptr: number) => number)(
              3,
              index,
              ptr
            )
        ),
        selected: selected(index) === 1,
      });
    }
    return {
      source: call("rd_env_choice_source") as ChoiceSource,
      kind: call("rd_env_choice_kind") as ChoiceKind,
      min: call("rd_env_choice_min"),
      max: call("rd_env_choice_max"),
      copies: call("rd_env_choice_copies"),
      options,
    };
  }

  /** 勾/取消勾一个选项。`0` 成功，`-1` 没有这个选项。 */
  choicePick(index: number, on: boolean): number {
    return (this.ex.rd_env_choice_pick as (index: number, on: number) => number)(index, on ? 1 : 0);
  }

  choiceClear(): number {
    return (this.ex.rd_env_choice_clear as () => number)();
  }

  /** 回答问句：`0` 接受、`-1` 没有问句、`-2` 被拒（数量不对）。 */
  choiceConfirm(): number {
    return (this.ex.rd_env_choice_confirm as () => number)();
  }

  // ── 演出 beat ─────────────────────────────────────────────────────────────
  /** 本步的演出日志（`rd_env_beat_*`）。`beats_dropped > 0` 表示内核丢了 beat。 */
  beats(): { beats: Beat[]; dropped: number } {
    const call = (name: string) => (this.ex[name] as () => number)();
    const count = call("rd_env_beat_count");
    const field = this.ex.rd_env_beat_field as (index: number, which: number) => number;
    const beats: Beat[] = [];
    for (let index = 0; index < count; index += 1) {
      const hasDef = field(index, 7) === 1;
      beats.push({
        kind: field(index, 0),
        actor: field(index, 1),
        target: field(index, 2),
        flags: field(index, 3),
        a: field(index, 4),
        b: field(index, 5),
        c: field(index, 6),
        def: hasDef
          ? this.readText(
              () => (this.ex.rd_env_beat_def_len as (index: number) => number)(index),
              (ptr) => (this.ex.rd_env_beat_def_into as (index: number, ptr: number) => number)(index, ptr)
            )
          : "",
      });
    }
    return { beats, dropped: call("rd_env_beats_dropped") };
  }

  // ── 组合：读一份完整快照 ──────────────────────────────────────────────────
  /**
   * 有没有战斗会话。
   *
   * ⚠️ 判据是 `rd_env_active_slot() !== -3`（"查询不创建会话"的哨兵），**不是** `rd_env_done()`
   * —— 后者在没有会话时返回 1（"结束了"），反过来说不出"有没有战斗"。
   */
  /**
   * 现在**真的有**一场战斗吗。
   *
   * ⚠️ 曾经写成 `rd_env_active_slot() !== -3` —— **那是错的**：内核的 `ensure_session()` 会
   * **懒建**一个会话（`lib.rs` 的 `rd_env_active_slot` 注释专门警告过查询不该创建状态），
   * 于是装载之后（还没开打）`active_slot` 返回 `-1`，判定成在战斗，解码出一条
   * **幽灵战斗**（2 个敌人、5 张手牌）。P2 从没发现，因为它总是先 `fight_begin` 再读。
   *
   * 判据只能看运行层：`rd_run_in_fight() == 1`（与场景表 SC-03b 用的是**同一个事实**）。
   */
  hasCombatSession(): boolean {
    return (this.ex.rd_run_in_fight as () => number)() === 1;
  }

  /**
   * 读一份完整战斗快照。
   *
   * ⚠️ 没有会话时**必须拒绝**：那时整条向量是 **0**（不是 -1），"空槽 = -1"的假设不成立，
   * 硬解码会数出 6 个 `alive=0` 的幽灵敌人（闸门 28 第一版就是这么炸的）。
   */
  snapshot(): CombatSnapshot {
    if (!this.hasCombatSession()) {
      throw new Error("没有战斗会话（rd_env_active_slot() = -3）：先 fight_begin");
    }
    // ⚠️ 敌人超过 6 个时，观察向量**装不下**（槽位是固定的 6 格，挪不动）。
    // 内核会把这件事**报出来**（`rd_env_enemy_overflow() = 1`），而不是悄悄丢掉。
    // 解码器只比对"header 的敌人数 == 扫出来的槽位数"，两者都会是 6 ⇒ **发现不了溢出**，
    // 所以必须在这里先问（第十四轮 Review P2-D）。
    if (this.enemyOverflow()) {
      throw new Error(
        "这一场战斗的敌人超过观察向量的 6 个槽位：界面无法完整显示，拒绝进入半可信状态。" +
          "（`rd_env_enemy_overflow() = 1`；扩容需要改 ABI 布局）"
      );
    }
    return decodeCombat(this.combatObservation(), this.actions());
  }

  /** `1` = 敌人超过 6 个（向量装不下）；`0` = 没有；`-1` = 没有会话。 */
  enemyOverflow(): boolean {
    return (this.ex.rd_env_enemy_overflow as () => number)() === 1;
  }
}

/** 装载校验。返回的诊断**总是**有内容（`ok` 为假时 `problems` 非空）。 */
export function validate(ex: Exports, sha256: string): WasmDiagnostics {
  const problems: string[] = [];

  const missing = REQUIRED_EXPORTS.filter((name) => typeof ex[name] !== "function");
  if (missing.length) problems.push(`缺少函数导出：${missing.join(", ")}`);
  // `memory` 是对象：没有它就读不到观察向量（页面唯一的读法）。
  const memory = ex.memory as WebAssembly.Memory | undefined;
  if (!memory || !(memory.buffer instanceof ArrayBuffer)) {
    problems.push("缺少导出：memory（或者它不是 WebAssembly.Memory）");
  }

  const num = (name: string) => (ex[name] as (() => number) | undefined)?.() ?? Number.NaN;
  const runLen = num("rd_run_observe_len");
  const combatLen = num("rd_env_observe_len");
  const fingerprint = num("rd_content_fingerprint");

  if (runLen !== ABI_RUN_OBSERVE_LEN) {
    problems.push(`rd_run_observe_len() = ${runLen}，ABI 是 ${ABI_RUN_OBSERVE_LEN}`);
  }
  if (combatLen !== ABI_COMBAT_OBSERVE_LEN) {
    problems.push(`rd_env_observe_len() = ${combatLen}，ABI 是 ${ABI_COMBAT_OBSERVE_LEN}`);
  }

  // 哨兵语义：这三条都是"曾经搞错过"的（§344 / §348 / §349）
  if (problems.length === 0) {
    if (num("rd_run_exists") !== 0) problems.push("没有局时 rd_run_exists() 必须是 0");
    if (num("rd_run_seed") !== -2147483648) problems.push("没有局时 rd_run_seed() 必须是 i32::MIN");
    if (num("rd_run_over") !== -1) problems.push("没有局时 rd_run_over() 必须是 -1");
    if (num("rd_env_active_slot") !== -3) {
      problems.push("没有战斗会话时 rd_env_active_slot() 必须是 -3（查询不许创建会话）");
    }
    // 越界读必须给 i32::MIN（不是 0）
    const observe = ex.rd_run_observe as ((index: number) => number) | undefined;
    if (observe && observe(runLen) !== -2147483648) {
      problems.push("rd_run_observe(len) 必须是 i32::MIN，不是 0");
    }
  }

  return {
    ok: problems.length === 0,
    problems,
    sha256,
    contentFingerprint: `0x${(fingerprint >>> 0).toString(16).padStart(8, "0")}`,
    runObserveLen: runLen,
    combatObserveLen: combatLen,
    exports: Object.keys(ex).filter((key) => typeof ex[key] === "function").length,
  };
}
