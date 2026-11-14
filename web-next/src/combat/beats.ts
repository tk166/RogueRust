// **Beat 演出的纯导演**（plan P5 的第一条）：`Beat[]` → 一串"要播的飘字/特效"。
//
// ## 三条硬纪律
//
// 1. **演出绝不改变状态**：这一层只读 beat、只产出"屏幕上要飘什么"。局面的唯一权威仍然是
//    内核的观察向量 —— 所以"播放动画的最终状态与内核完全一致"是**结构上成立**的，不是靠
//    小心翼翼同步。闸门 37 断言这一点（导演是纯函数、输入不被改）。
// 2. **未知种类不中断**：内核加了新 kind 而 UI 没跟上时，降级成一条中性飘字并**计数** ——
//    静默跳过会让"少了 13 号"这种事重演（`BEAT_DESTROYED` 曾经就是这么被吞掉的）。
// 3. **`dropped > 0` 要能看见**：内核因为容量丢了 beat，页面必须说出来（"这一下动画不全"），
//    而不是安静地少播几下。
//
// ## 为什么导演是纯函数
//
// 动画最容易写成一团 `setTimeout` + 全局状态，然后"关掉动画"就变成另一条代码路径。
// 这里把"什么时候播到第几条"做成 `(state, dtMs) -> state` 的纯函数：闸门 37 不需要浏览器
// 就能把 skip / 快进 / 降级 / 上限全部测掉。
//
// ## §399：因果信息不再丢
//
// 内核的 Beat 带 `def`（卡/状态**定义 id**）、`actor`、`target`、`flags`、`a/b/c`。
// 第一版只留下了 `{kind, at, text, tone, duration}`，于是"Strike 的斩击"与"Bash 的重击"
// 在数据上一模一样（审阅 §6）。现在 `BeatEffect` 原样带 `def` / `actor` / `target` / `flags`，
// 外加 `presentation/cues.ts` 翻出来的 `origin` / `effectKey` / `phase` / 冻结锚点。
//
// 文案仍是 `describe()` 的中文；`effectKey` 只决定**视觉配方**（颜色/形状/时长/震屏）。

import { translateAll, type CueContext, type PresentationCue } from "../presentation/cues.js";
import { recipeFor } from "../presentation/registry.js";

/** 演出基调（决定颜色与动画方向）。 */
export type BeatTone =
  | "damage"
  | "dot"
  | "block"
  | "heal"
  | "buff"
  | "debuff"
  | "down"
  | "card"
  | "turn"
  | "summon"
  | "neutral";

/** 一条"要播的"演出。`at` 是**墙位槽**（`-1` 英雄 / `0..5` 敌人 / `-2` 不在场上）。 */
export interface BeatEffect {
  readonly id: number;
  readonly kind: number;
  readonly at: number;
  readonly text: string;
  readonly tone: BeatTone;
  /** 播多久（毫秒）。`0` = 立即结束（只留一行日志式提示）。 */
  readonly duration: number;
  /**
   * §399：内核给的**定义 id**（`strike` / `standard.poison` / 空串）。
   *
   * ⚠️ 以前这里没有它 —— 于是"哪张卡打的""哪个状态变的"在演出层不可知。
   */
  readonly def: string;
  /** §399：来源（卡 / 状态 / 敌人招式 / 系统）。无法证明时是 `system`，**不猜**。 */
  readonly origin: PresentationCue["origin"];
  /** §399：稳定 key（`damage.dot` / `card.strike`），`presentation/registry.ts` 用它查配方。 */
  readonly effectKey: string;
  /** §399：演出阶段（`cast` / `hit` / `resolve`）。将来给 3D 分轨用。 */
  readonly phase: PresentationCue["phase"];
  /**
   * §399：**冻结的锚点**（Cue 创建那一刻的槽位与外观 id）。
   *
   * 播放时若该槽位的外观已经变了（Boss 分裂 / 召唤 / 死亡后槽位重用），就退回这里，
   * 而不是把旧事件的飘字画在**新**对象头顶（审阅 §6 的陷阱 1）。
   */
  readonly anchorSlot: number;
  readonly appearanceId: string;
}

export interface DirectorOptions {
  /** 关掉动画：队列立刻清空（plan 的退出条件"关闭动画也能完整游戏"）。 */
  readonly reducedMotion: boolean;
  /** 单条演出时长上限（毫秒）。 */
  readonly maxDuration?: number;
}

export interface DirectorState {
  readonly playing: BeatEffect | null;
  readonly elapsed: number;
  readonly queue: readonly BeatEffect[];
  /** 内核因为容量丢掉的 beat 数（`rd_env_beats_dropped`）。 */
  readonly dropped: number;
  /** UI 不认识的 kind（降级成中性飘字）。 */
  readonly unknownKinds: readonly number[];
  readonly reducedMotion: boolean;
}

const DEFAULT_DURATION = 520;
const MAX_DURATION = 900;

/** kind → (基调, 文字, 时长倍率)。**编号是 ABI**（`BEAT_*`），不要重排。 */
function describe(kind: number, a: number, b: number, def: string, flags: number): {
  tone: BeatTone;
  text: string;
  duration: number;
} | null {
  const dot = (flags & 1) === 1;
  switch (kind) {
    case 1: // damage
      return {
        tone: dot ? "dot" : "damage",
        // `b` 是被格挡的量：有就一起说，玩家才知道"为什么只掉这么点"。
        text: b > 0 ? `-${a}（格挡 ${b}）` : `-${a}`,
        duration: DEFAULT_DURATION,
      };
    case 2: // block
      return { tone: "block", text: `格挡 +${a}`, duration: DEFAULT_DURATION };
    case 3: // heal
      return { tone: "heal", text: `+${a}`, duration: DEFAULT_DURATION };
    case 4: // status changed
      return {
        tone: a >= 0 ? "buff" : "debuff",
        text: `${def || "状态"} ${a >= 0 ? "+" : ""}${a}`,
        duration: DEFAULT_DURATION,
      };
    case 5: // status removed
      return { tone: "neutral", text: `${def || "状态"} 消失`, duration: 420 };
    case 6: // status prevented
      return { tone: "block", text: `${def || "状态"} 被挡下`, duration: 420 };
    case 7: // downed
      return { tone: "down", text: "倒下", duration: 640 };
    case 8: // escaped
      return { tone: "neutral", text: "逃走", duration: 520 };
    case 9: // card played
      return { tone: "card", text: def ? `打出 ${def}` : "出牌", duration: 420 };
    case 10: // turn started
      return { tone: "turn", text: "回合开始", duration: 380 };
    case 11: // turn ended
      return { tone: "turn", text: "回合结束", duration: 380 };
    case 12: // summoned
      return { tone: "summon", text: b > 0 ? `召唤（${b} 血）` : "召唤", duration: 640 };
    case 13: // destroyed
      return { tone: "down", text: "被移出战斗", duration: 640 };
    default:
      // ⚠️ 未知 kind：**不抛、不静默**，给一条中性飘字并让调用方计数。
      return null;
  }
}

/**
 * `Beat[]` → 演出队列。纯函数：不改输入、不抛异常。
 *
 * `dropped` 会原样带进状态（`DirectorState.dropped`），界面据此显示"动画不全"。
 */
export function planBeats(
  beats: readonly {
    kind: number;
    actor: number;
    target: number;
    flags: number;
    a: number;
    b: number;
    c: number;
    def: string;
  }[],
  dropped: number,
  options: DirectorOptions,
  /** §399：槽位 → 当前外观 id（冻结锚点用）。缺省时退化成"没有身份"。 */
  context: CueContext = { appearanceOf: () => "" },
  startId = 0
): { effects: BeatEffect[]; unknownKinds: number[]; dropped: number } {
  const effects: BeatEffect[] = [];
  const unknownKinds: number[] = [];
  const cap = Math.min(options.maxDuration ?? MAX_DURATION, MAX_DURATION);
  let id = startId;

  // §399：先翻成语义 Cue（`def`/`actor`/`flags` 都在里面），再查视觉配方。
  // ⚠️ `appearanceOf` 只有 `planBeats` 的调用方能给（它知道槽位当前是谁）。
  const cues = translateAll(beats, context, id);

  for (let index = 0; index < beats.length; index += 1) {
    const beat = beats[index];
    const cue = cues[index];
    const shape = describe(beat.kind, beat.a, beat.b, beat.def, beat.flags);
    const { recipe } = recipeFor(cue.effectKey);
    if (shape === null) {
      unknownKinds.push(beat.kind);
      effects.push({
        id: id++,
        kind: beat.kind,
        at: cue.anchorSlot,
        text: `?${beat.kind}`,
        tone: "neutral",
        duration: 360,
        def: beat.def,
        origin: cue.origin,
        effectKey: cue.effectKey,
        phase: cue.phase,
        anchorSlot: cue.anchorSlot,
        appearanceId: cue.appearanceId,
      });
      continue;
    }
    effects.push({
      id: id++,
      kind: beat.kind,
      // 锚点由 Cue 决定（出牌/回合挂行动者，其余挂被作用的人）—— 与 `planBeats` 原来的规则一致。
      at: cue.anchorSlot,
      text: shape.text,
      tone: shape.tone,
      // 配方给时长，`describe` 也有一份：**取小的那个**（两者都是"至少播多久"的估计）。
      duration: Math.min(recipe.duration, shape.duration, cap),
      def: beat.def,
      origin: cue.origin,
      effectKey: cue.effectKey,
      phase: cue.phase,
      anchorSlot: cue.anchorSlot,
      appearanceId: cue.appearanceId,
    });
  }

  return { effects, unknownKinds, dropped };
}

export function createDirector(options: DirectorOptions): DirectorState {
  return {
    playing: null,
    elapsed: 0,
    queue: [],
    dropped: 0,
    unknownKinds: [],
    reducedMotion: options.reducedMotion,
  };
}

/** 把新一批演出接在队尾（已经有一批在播时**不打断**）。 */
export function enqueue(state: DirectorState, planned: {
  effects: BeatEffect[];
  unknownKinds: number[];
  dropped: number;
}): DirectorState {
  const unknownKinds = Array.from(new Set([...state.unknownKinds, ...planned.unknownKinds]));
  const merged: DirectorState = {
    ...state,
    queue: [...state.queue, ...planned.effects],
    dropped: state.dropped + planned.dropped,
    unknownKinds,
  };
  // 关掉动画：一条都不播，直接空队列（但 `dropped`/`unknownKinds` 仍然记账）。
  if (state.reducedMotion) return { ...merged, queue: [], playing: null, elapsed: 0 };
  return startNext(merged);
}

/** 开始播下一条（内部用；队列空 ⇒ `playing = null`）。 */
function startNext(state: DirectorState): DirectorState {
  if (state.playing) return state;
  const [head, ...rest] = state.queue;
  if (!head) return { ...state, playing: null, elapsed: 0 };
  if (head.duration <= 0) return startNext({ ...state, queue: rest });
  return { ...state, playing: head, elapsed: 0, queue: rest };
}

/**
 * 推进 `dtMs`。返回新状态（**纯函数**）。
 *
 * 一条播完就换下一条；`dtMs` 大于剩余时长时把余量**结转**给下一条（否则慢帧率下动画会拖长）。
 */
export function advance(state: DirectorState, dtMs: number): DirectorState {
  if (state.reducedMotion) {
    if (state.playing === null && state.queue.length === 0) return state;
    return { ...state, playing: null, queue: [], elapsed: 0 };
  }
  let carry = Math.max(0, dtMs);
  let current: DirectorState = state;

  while (true) {
    const playing = current.playing;
    if (!playing) {
      const next = startNext(current);
      if (next.playing === null) return next;
      current = next;
      continue;
    }
    const remaining = playing.duration - current.elapsed;
    if (carry < remaining) {
      return { ...current, elapsed: current.elapsed + carry };
    }
    carry -= remaining;
    const after = startNext({ ...current, playing: null, elapsed: 0 });
    current = after;
    if (current.playing === null && current.queue.length === 0) return current;
    if (carry <= 0) return current;
  }
}

/** 跳过全部（玩家点一下/按 Esc，或"快进"）。**不清 `dropped`/`unknownKinds`**。 */
export function skipAll(state: DirectorState): DirectorState {
  return { ...state, playing: null, queue: [], elapsed: 0 };
}

/** 还有没有东西在播（界面用它决定要不要显示"跳过"）。 */
export function isBusy(state: DirectorState): boolean {
  return state.playing !== null || state.queue.length > 0;
}

/** 诊断串（闸门与设置面板都读它）。 */
export function describeDirector(state: DirectorState): string {
  return (
    `playing=${state.playing ? state.playing.text : "-"} queue=${state.queue.length} ` +
    `dropped=${state.dropped} unknown=${state.unknownKinds.join(",") || "-"}`
  );
}
