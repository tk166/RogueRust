// 指针状态机（P1 的核心，纯函数、无 DOM、无 three）。
//
// 为什么单独一个文件：`pressed / dragging / targeting / commit / rebound` 这五个状态必须
// **鼠标与触摸共用一份**。旧页面 `web/ui_render.js` 把它们散在事件回调里，于是"桌面能拖、
// 触摸不行"这种偏差只能靠人试出来（§151 的老问题）。
//
// 这里的 `reduce(state, event)` 是**唯一的**状态迁移入口：任何输入源（mouse / touch / pen /
// 未来的手柄）都只是把它自己的事件归一化成 `PointerEvent` 再喂进来。
//
// ⚠️ **一处与旧页面的有意分歧**（第十二轮 Review §P1 UX 决策）：
// 旧 `actionFor()` 在"该牌只有一条合法动作"时，拖到**任何位置**都算数 —— 于是"不需要目标的牌"
// 与"需要目标、但只剩一个敌人"在拖拽层被合并了。3D 里这是**误触直接出牌**。
// 本文件的选择：**有目标的牌必须落在合法目标上**；落在空白处一律 rebound，不管场上剩几个敌人。
// 理由：① 3D 里敌人是可拖上去的实体，"丢在空白处"读作"放回去"；② 规则不依赖"场上还有几个
// 敌人"这种隐藏状态（正是 Review 指出的那类惊喜）。差异本身有测试（`no-target` vs `one-target`）。

/** 一张牌对当前局面而言，可以被丢到哪些槽位。 */
export interface DropOption {
  /** 目标槽位；`-1` 表示"不需要目标"（例如技能牌、能力牌）。 */
  readonly slot: number;
  /** 内核动作序号。P1 是 Mock，P2 换成真实 `rd_env_action_*`。 */
  readonly actionIndex: number;
  readonly label: string;
}

export type Phase = "idle" | "pressed" | "dragging" | "targeting";

export interface State {
  readonly phase: Phase;
  /** 正在操作的卡牌槽位；`-1` 表示没有。 */
  readonly handSlot: number;
  /** 指针当前悬停的目标槽位；`-1` 表示空白处。 */
  readonly hoverSlot: number;
  /** 本张牌允许的落点（进入 dragging 时快照，避免拖拽中途局面变化导致"合法"漂移）。 */
  readonly options: readonly DropOption[];
  /** 上一次提交/回弹的结果，供 UI 播放一次动画。 */
  readonly lastResult: Result | null;
}

export type Result =
  | { readonly kind: "commit"; readonly handSlot: number; readonly actionIndex: number; readonly targetSlot: number }
  | { readonly kind: "rebound"; readonly handSlot: number; readonly why: "no-target" | "illegal-target" | "outside-hand" };

export type Event =
  /** 在卡牌 `handSlot` 上按下，`options` 是该牌此刻的合法落点表。 */
  | { readonly type: "down"; readonly handSlot: number; readonly options: readonly DropOption[] }
  | { readonly type: "move"; readonly hoverSlot: number; readonly distance: number }
  | { readonly type: "up"; readonly hoverSlot: number; readonly distance: number }
  | { readonly type: "cancel" };

/** 超过这个像素距离才算"开始拖"，否则按下-抬起 = 点按（走 `tap` 语义）。 */
export const DRAG_THRESHOLD_PX = 8;

export const INITIAL: State = {
  phase: "idle",
  handSlot: -1,
  hoverSlot: -1,
  options: [],
  lastResult: null,
};

/**
 * 是否"有目标"：`options` 里存在 `slot >= 0` 的条目。
 * 注意 `options.length === 1 && slot === -1` 是**无目标牌**（技能/能力），不是"只剩一个敌人"。
 */
export function needsTarget(options: readonly DropOption[]): boolean {
  return options.some((option) => option.slot >= 0);
}

/** 这张牌能不能丢到 `slot` 上。 */
export function isLegalDrop(options: readonly DropOption[], slot: number): boolean {
  return options.some((option) => option.slot === slot);
}

/** 决策：抬起时到底提交还是回弹。**纯函数**，因此可以被单测穷举。 */
export function decide(options: readonly DropOption[], hoverSlot: number): Result["kind"] | "none" {
  const targeted = needsTarget(options);
  if (!targeted) {
    // 无目标牌：丢在哪儿都算数（含空白处）。这是旧页面也有的行为，保留。
    return options.length === 0 ? "none" : "commit";
  }
  // 有目标牌：**必须**落在合法目标上，空白处一律回弹（与旧 `actionFor` 的分歧点）。
  return isLegalDrop(options, hoverSlot) ? "commit" : "rebound";
}

export function reduce(state: State, event: Event): State {
  switch (event.type) {
    case "down": {
      // 按下新牌时丢弃上一条结果，否则 UI 会重播上一张牌的动画。
      return {
        phase: "pressed",
        handSlot: event.handSlot,
        hoverSlot: -1,
        options: event.options,
        lastResult: null,
      };
    }
    case "move": {
      if (state.phase === "pressed") {
        if (event.distance < DRAG_THRESHOLD_PX) return state;
        return { ...state, phase: needsTarget(state.options) ? "targeting" : "dragging", hoverSlot: event.hoverSlot };
      }
      if (state.phase === "dragging" || state.phase === "targeting") {
        if (event.hoverSlot === state.hoverSlot) return state;
        return { ...state, hoverSlot: event.hoverSlot };
      }
      return state;
    }
    case "up": {
      if (state.phase === "idle") return state;
      // 按下-抬起且没超过阈值 = 点按：对无目标牌直接出，对有目标牌进入 targeting 等第二次点选。
      if (state.phase === "pressed") {
        if (!needsTarget(state.options)) {
          const verdict = decide(state.options, -1);
          return finish(state, verdict === "commit" ? "commit" : "rebound", -1, "no-target");
        }
        return { ...state, phase: "targeting", hoverSlot: event.hoverSlot };
      }
      const verdict = decide(state.options, event.hoverSlot);
      if (verdict === "commit") return finish(state, "commit", event.hoverSlot, null);
      return finish(state, "rebound", event.hoverSlot, needsTarget(state.options) ? "illegal-target" : "no-target");
    }
    case "cancel":
      return state.phase === "idle"
        ? state
        : { ...INITIAL, lastResult: { kind: "rebound", handSlot: state.handSlot, why: "illegal-target" } };
  }
}

function finish(
  state: State,
  kind: "commit" | "rebound",
  targetSlot: number,
  why: "no-target" | "illegal-target" | "outside-hand" | null
): State {
  const chosen = state.options.find((option) => option.slot === targetSlot);
  const lastResult: Result =
    kind === "commit" && chosen
      ? { kind: "commit", handSlot: state.handSlot, actionIndex: chosen.actionIndex, targetSlot }
      : { kind: "rebound", handSlot: state.handSlot, why: why ?? "illegal-target" };
  return { ...INITIAL, lastResult };
}
