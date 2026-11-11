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

import { decodeAction, decodeCombat, type CombatAction, type CombatSnapshot } from "./snapshot";

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
  "rd_env_choice_pending",
  "rd_env_card_name_len",
  "rd_env_card_name_into",
  "rd_env_card_text_len",
  "rd_env_card_text_into",
  "rd_env_enemy_name_len",
  "rd_env_enemy_name_into",
  "rd_env_scratch_buf",
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

  /** 装载并校验。**校验失败抛 `WasmMismatch`**（带一份可显示的诊断清单）。 */
  static async load(url: string, fetchImpl: typeof fetch = fetch): Promise<WasmHost> {
    const response = await fetchImpl(url);
    if (!response.ok) {
      throw new Error(`取 wasm 失败：${url} → HTTP ${response.status}`);
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    const sha256 = await sha256Hex(bytes);
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

  // ── 组合：读一份完整快照 ──────────────────────────────────────────────────
  /**
   * 有没有战斗会话。
   *
   * ⚠️ 判据是 `rd_env_active_slot() !== -3`（"查询不创建会话"的哨兵），**不是** `rd_env_done()`
   * —— 后者在没有会话时返回 1（"结束了"），反过来说不出"有没有战斗"。
   */
  hasCombatSession(): boolean {
    return (this.ex.rd_env_active_slot as () => number)() !== -3;
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
    return decodeCombat(this.combatObservation(), this.actions());
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
