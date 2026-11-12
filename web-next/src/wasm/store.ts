// `GameStore` + `ActionDispatcher`：**唯一**发起权威动作的地方。
//
// 三条纪律（plan P2 + 前几轮的教训）：
// 1. 组件不碰 `instance.exports` —— 它们只读 `GameStore.snapshot()` 与 `subscribe()`。
// 2. **拒绝不产生成功演出**：`dispatch()` 返回结果，调用方只在 `accepted` 时播放反馈。
// 3. **拒绝 = 可观察向量逐字节不变**：`dispatch()` 前后各读一次 148 格观察向量并比对，
//    不一致就把 `unchanged` 标成 false —— 这不是"信任内核"，是**当场证明**。
//    ⚠️ 但它**只覆盖观察向量**：随机数、内部实例、`PendingChoice` 细节等未导出字段都不在里面。
//    "整个结构体相等"只有 Rust 侧的 full-hash 测试能证明（已有 `hash_full`），不要用 UI 代替
//    （第十四轮 Review P1-D）。

import type { WasmHost } from "./host";
import { STEP_ACCEPTED, STEP_BROKEN, STEP_FINISHED, STEP_REJECTED } from "./host";
import type { Beat, CombatAction, CombatSnapshot, PendingChoice } from "./snapshot";

export interface DispatchResult {
  readonly accepted: boolean;
  readonly code: number;
  /**
   * `accepted === false` 时，**可观察向量**是否逐字节不变。
   *
   * ⚠️ 只覆盖 148 格观察向量，不覆盖随机数 / 内部实例 / 未导出字段。
   */
  readonly unchanged: boolean;
  readonly reason: "accepted" | "rejected" | "finished" | "broken";
  readonly action: CombatAction | null;
  readonly before: CombatSnapshot;
  readonly after: CombatSnapshot;
  /** 这一步的演出日志（`rd_env_beat_*`）；`dropped > 0` 表示内核丢了 beat。 */
  readonly beats: readonly Beat[];
  readonly beatsDropped: number;
}

type Listener = () => void;

export class GameStore {
  private host: WasmHost;
  /**
   * 当前战斗快照；`null` = **没有战斗会话**（装载后、`fight_begin` 之前，或战斗结束后）。
   *
   * 这不是错误状态：plan 的 SC-03 / SC-03b 就靠"有没有战斗"区分。所以构造时允许为 `null`，
   * 只是 `dispatch` 在没有快照时拒绝（不许"半可用"）。
   */
  private current: CombatSnapshot | null;
  private readonly listeners = new Set<Listener>();
  /** 已经发生过多少次**被接受**的动作（回放/调试用）。 */
  private acceptedCount = 0;
  /**
   * **动作表版本号**：任何可能改变动作表编号的操作都 +1（接受的动作、选牌确认、刷新）。
   *
   * 为什么需要它：`actionIndex` 是**数字位置**，不是身份。玩家按住某张牌的瞬间冻结了
   * `actionIndex = 3`；松手前若另一条路径（多指同时点"结束回合"、选牌确认）改了状态，
   * 新的动作表里 `index = 3` 可能是**另一张牌 / 另一个敌人**，照旧执行就会"出另一张牌"
   * （第十四轮 Review P1-B）。手势提交前必须比对版本号。
   */
  private stateEpoch = 0;
  /**
   * **最近一次被接受的动作产生的 beat**（+ 一个自增序号）。
   *
   * 为什么放在这里而不是让界面自己记：beat 是 `dispatch` 的返回值，而 `dispatch` 有**两条**
   * 调用路径（界面的拖拽提交、探针/驱动的 `dispatchCombat`）。放在界面上会让"探针打出来的
   * 战斗没有演出"——第一版就是这样（`__p1.beats()` 一直是空的）。
   * 放在这里，谁 dispatch 谁就有 beat，消费方只看 `beatSeq` 变没变。
   */
  private lastBeats: { beats: readonly Beat[]; dropped: number; seq: number } = {
    beats: [],
    dropped: 0,
    seq: 0,
  };

  constructor(host: WasmHost) {
    this.host = host;
    this.current = host.hasCombatSession() ? host.snapshot() : null;
  }

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): CombatSnapshot | null => this.current;

  /** 重新读一次（进战斗、结算奖励之后调用）。没有会话时把快照清成 `null`。 */
  refresh(): CombatSnapshot | null {
    this.current = this.host.hasCombatSession() ? this.host.snapshot() : null;
    // 动作表可能整体换了一份 ⇒ 版本号前进，进行中的手势必须作废。
    this.stateEpoch += 1;
    for (const listener of this.listeners) listener();
    return this.current;
  }

  get acceptedActions(): number {
    return this.acceptedCount;
  }

  /** 最近一次被接受的动作的 beat（见 `lastBeats` 的注释）。 */
  get beats(): { beats: readonly Beat[]; dropped: number; seq: number } {
    return this.lastBeats;
  }

  /** 动作表版本号（见 `stateEpoch` 的注释）。 */
  get epoch(): number {
    return this.stateEpoch;
  }

  /** 当前可用的动作表（来自内核，不是 UI 自己推的）。没有会话时为空表。 */
  actions(): readonly CombatAction[] {
    return this.current?.actions ?? [];
  }

  /**
   * 发起一个动作。**先证明拒绝不改状态**，再更新快照。
   *
   * 用 `action.index` 而不是"第几个可用动作"：动作表下标就是内核的 `rd_env_step` 入参，
   * 自己再映射一层只会引入"UI 的第 3 条 ≠ 内核的第 3 条"。
   */
  dispatch(action: CombatAction): DispatchResult {
    const before = this.current;
    if (!before) throw new Error("没有战斗会话：先 fight_begin");
    const beforeVector = this.host.combatObservation();
    const code = this.host.step(action.index);
    const afterVector = this.host.combatObservation();
    const unchanged =
      beforeVector.length === afterVector.length &&
      beforeVector.every((value, index) => value === afterVector[index]);

    const reason: DispatchResult["reason"] =
      code === STEP_ACCEPTED
        ? "accepted"
        : code === STEP_REJECTED
          ? "rejected"
          : code === STEP_FINISHED
            ? "finished"
            : "broken";

    if (code === STEP_ACCEPTED) {
      this.acceptedCount += 1;
      this.stateEpoch += 1;
    }
    // 无论接受与否都重读：接受后必须与内核一致；被拒绝时重读也等于再确认一次"没变"。
    this.current = this.host.snapshot();
    // beat 是"这一步发生了什么"的权威叙述；接受时才有内容。
    const { beats, dropped } = code === STEP_ACCEPTED ? this.host.beats() : { beats: [], dropped: 0 };
    if (code === STEP_ACCEPTED) {
      this.lastBeats = { beats, dropped, seq: this.lastBeats.seq + 1 };
    }
    for (const listener of this.listeners) listener();

    return {
      accepted: code === STEP_ACCEPTED,
      code,
      unchanged,
      reason,
      action,
      before,
      after: this.current,
      beats,
      beatsDropped: dropped,
    };
  }

  /** 按 (手牌槽位, 目标槽位) 找内核给的那条动作；找不到返回 `null`（**不要**自己合成）。 */
  findPlay(handSlot: number, targetSlot: number): CombatAction | null {
    const candidates = this.actions().filter(
      (action) => action.kind === "play" && action.handSlot === handSlot
    );
    if (candidates.length === 0) return null;
    // 有目标的牌：必须精确匹配；无目标牌（`targetSlot === -1`）只认 `-1` 那条。
    const exact = candidates.find((action) => action.targetSlot === targetSlot);
    if (exact) return exact;
    // 内核为每张可出的牌 × 每个活敌人都发一条；无目标牌在 `targetSlot === -1` 上有那条。
    // 绝不"因为只剩一个敌人就用它"——那是旧 `actionFor` 的错误，§352 已经改掉了。
    return null;
  }

  findEndTurn(): CombatAction | null {
    return this.actions().find((action) => action.kind === "endTurn") ?? null;
  }

  // ── 待决选牌：**只有** store 能回答问句（组件不碰导出）────────────────────
  /** 当前问句；没有就 `null`。 */
  choice(): PendingChoice | null {
    return this.host.choice();
  }

  /** 勾/取消勾。返回内核的返回码（`-1` = 没有这个选项）。 */
  pickChoice(index: number, on: boolean): number {
    return this.host.choicePick(index, on);
  }

  clearChoice(): number {
    return this.host.choiceClear();
  }

  /**
   * 回答问句。
   *
   * ⚠️ `-2` 是"数量不对被拒"（不是"没有问句"）：界面要能显示原因并让玩家继续勾。
   * 拒绝时**不**刷新快照 —— 问句还在，选中的牌也还在。
   */
  confirmChoice(): { code: number; accepted: boolean; unchanged: boolean } {
    const before = this.host.combatObservation();
    const code = this.host.choiceConfirm();
    const after = this.host.combatObservation();
    const unchanged =
      before.length === after.length && before.every((value, index) => value === after[index]);
    if (code === 0) {
      this.current = this.host.hasCombatSession() ? this.host.snapshot() : null;
      this.stateEpoch += 1;
      for (const listener of this.listeners) listener();
    }
    return { code, accepted: code === 0, unchanged };
  }

  /** 诊断用：`STEP_BROKEN` 表示内核驱动坏了（不是"玩家操作非法"）。 */
  static isBroken(result: DispatchResult): boolean {
    return result.code === STEP_BROKEN;
  }

  /**
   * **契约级错误**：内核拒绝了这一步，却把观察向量改了。
   *
   * 这不是"玩家操作非法"，是 ABI 违约 —— 界面必须**响亮失败**（冻结操作 + 显示诊断），
   * 不能显示"状态未改变"那种安慰话（第十四轮 Review P1-D）。
   */
  static isContractViolation(result: DispatchResult): boolean {
    return !result.accepted && !result.unchanged;
  }
}
