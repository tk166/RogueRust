// **表现层的第一层：`Beat` → `PresentationCue`**（纯函数，闸门可脱离浏览器穷尽断言）。
//
// ## 为什么需要这一层（审阅 §6 的核心）
//
// 现在 `beats.ts::planBeats` 把内核的 Beat 压成 `{id, kind, at, text, tone, duration}`：
// `def`（卡/状态的**定义 id**）、`actor`、`target`、`flags` 全丢了。于是"Strike 的斩击"与
// "Bash 的重击"在数据上**一模一样**，只能靠文案/数值去猜 —— 而猜出来的东西迟早错。
//
// 这一层只做一件事：**把内核已经给出的因果信息翻译成语义 Cue**，不猜。
//
// ```text
// Beat{kind, actor, target, flags, a, b, c, def}   ← 内核权威（规则事实）
//        │
//        ▼  translate()  ← 纯函数、可诊断、缺信息就降级
// Cue{eventId, origin, kind, actorSlot, targetSlot, value, effectKey, phase}
//        │
//        ▼  registry.ts::recipeFor(effectKey)   ← 数据驱动（内容 → 视觉配方）
// 视觉配方{tone, color, shape, duration, ...}
// ```
//
// ## 三条纪律
//
// 1. **`origin` 不许凭空生成**：只有能从 `def` + `kind` + `flags` **证明**的来源才写进去，
//    否则 `{kind:"system"}`。宁可"来源未知"也不要一个猜错的卡名（§382 的教训）。
// 2. **不读局面**：这一层不收 `CombatState`，只收 Beat 与一点点上下文（谁是英雄、槽位映射）。
//    所以它不会因为"当前血量变了"而改变历史演出的含义。
// 3. **`effectKey` 是稳定字符串**（`damage.dot` / `card.strike` / `relic.trigger`…），
//    `registry.ts` 只认它 —— 加一种卡/状态不需要改这一层。

/** Beat 的 kind 编号是 ABI（`BEAT_*`，见 `wasm/snapshot.ts`）。 */
export const CUE_KIND = {
  damage: 1,
  block: 2,
  heal: 3,
  statusChanged: 4,
  statusRemoved: 5,
  statusPrevented: 6,
  downed: 7,
  escaped: 8,
  cardPlayed: 9,
  turnStarted: 10,
  turnEnded: 11,
  summoned: 12,
  destroyed: 13,
} as const;

/**
 * 这条演出的**来源**。
 *
 * `system` 是**诚实的缺省**：`def` 为空、或它既不是卡也不是状态时，我们不知道是谁触发的
 * （遗物触发、持续伤害、回合事件…）。不猜。
 */
export type CueOrigin =
  | { readonly kind: "card"; readonly defId: string }
  | { readonly kind: "status"; readonly defId: string }
  | { readonly kind: "enemyMove"; readonly defId: string }
  | { readonly kind: "system" };

/** 演出阶段（未来给 3D 动画分轨用；现在只用于"cast 先于 hit"的排序语义）。 */
export type CuePhase = "cast" | "hit" | "resolve";

export interface PresentationCue {
  /** 与 Beat 一一对应（同一批 beat 里递增）。 */
  readonly eventId: number;
  readonly kind: number;
  readonly origin: CueOrigin;
  /** 表现挂在谁身上（墙位槽：`-1` 英雄 / `0..5` 敌人 / `-2` 不在场上）。 */
  readonly actorSlot: number;
  readonly targetSlot: number;
  readonly value: number;
  /** 稳定 key：`registry.ts` 用它查视觉配方。 */
  readonly effectKey: string;
  readonly phase: CuePhase;
  /**
   * **冻结的表现锚点**：Cue 创建那一刻的槽位身份。
   *
   * ⚠️ 为什么需要（审阅 §6 的陷阱 1）：`BeatLayer` 播放时用**当前** `layout.enemies.find(slot)`
   * 取位置。Boss 分裂 / 召唤 / 死亡之后槽位会被**重用**，于是队列里较早的 Beat 会被画在
   * **新**对象头顶（"你打的是史莱姆，飘字飘在刚分裂出来的小史莱姆身上"）。
   * 把槽位当时的 `appearanceId` 冻在这里，播放时对不上就退回这个锚点。
   */
  readonly anchorSlot: number;
  readonly appearanceId: string;
}

/** 翻译时需要的上下文（只有"谁是谁"，没有任何局面数值）。 */
export interface CueContext {
  /** 槽位 → 外观 id（`cultist` / `acid_slime_l#000001`）。用于冻结锚点。 */
  readonly appearanceOf: (slot: number) => string;
}

/** 内核 Beat 的最小形状（与 `wasm/snapshot.ts::Beat` 一致）。 */
export interface BeatLike {
  readonly kind: number;
  readonly actor: number;
  readonly target: number;
  readonly flags: number;
  readonly a: number;
  readonly b: number;
  readonly c: number;
  readonly def: string;
}

/**
 * `def` → 来源。
 *
 * 判据只有两条，都是**内容里看得见**的事实：
 * * `standard.` 前缀 = 状态定义（内容里状态 id 一律带命名空间）；
 * * 其余非空 = 卡定义 id（`strike` / `bash+`）。
 *
 * ⚠️ 不按"这个 kind 一般是谁触发的"猜：`damage` 可能来自卡、毒、荆棘、遗物。
 * 说不清就是 `system`。
 */
function originOf(kind: number, def: string): CueOrigin {
  if (def.length === 0) return { kind: "system" };
  if (def.startsWith("standard.")) {
    // 状态**变化**的 Beat 里的 `def` 是状态定义；而"出牌"的 def 是卡。
    return kind === CUE_KIND.statusChanged || kind === CUE_KIND.statusRemoved ||
      kind === CUE_KIND.statusPrevented
      ? { kind: "status", defId: def }
      : { kind: "system" };
  }
  return kind === CUE_KIND.cardPlayed ? { kind: "card", defId: def } : { kind: "system" };
}

/** `effectKey`：稳定、可穷尽、可被 `registry.ts` 查表。 */
function effectKeyOf(kind: number, origin: CueOrigin, flags: number): string {
  const dot = (flags & 1) === 1;
  switch (kind) {
    case CUE_KIND.damage:
      // 持续伤害与直接伤害**必须分开**：前者没有"被谁打"的动作，表现也不同。
      return dot ? "damage.dot" : "damage.direct";
    case CUE_KIND.block:
      return "block.gain";
    case CUE_KIND.heal:
      return "heal.gain";
    case CUE_KIND.statusChanged:
      return origin.kind === "status" ? "status.change" : "status.change.unknown";
    case CUE_KIND.statusRemoved:
      return "status.remove";
    case CUE_KIND.statusPrevented:
      return "status.prevented";
    case CUE_KIND.downed:
      return "enemy.downed";
    case CUE_KIND.escaped:
      return "enemy.escaped";
    case CUE_KIND.cardPlayed:
      // ⚠️ 这里就是审阅要的那一条：**同一张卡有自己的 key**（`card.strike` / `card.bash`）。
      // 于是"斩击 vs 重击"在数据上可分，不需要看数值反推。
      return origin.kind === "card" ? `card.${origin.defId.replace(/\+$/, "")}` : "card.play";
    case CUE_KIND.turnStarted:
      return "turn.start";
    case CUE_KIND.turnEnded:
      return "turn.end";
    case CUE_KIND.summoned:
      return "enemy.summon";
    case CUE_KIND.destroyed:
      return "enemy.destroyed";
    default:
      return `unknown.${kind}`;
  }
}

/** 阶段：出牌是 cast，伤害/格挡是 hit，倒下/回合是 resolve。 */
function phaseOf(kind: number): CuePhase {
  if (kind === CUE_KIND.cardPlayed) return "cast";
  if (kind === CUE_KIND.downed || kind === CUE_KIND.turnStarted || kind === CUE_KIND.turnEnded) {
    return "resolve";
  }
  return "hit";
}

/**
 * 翻译一条 Beat。
 *
 * **不抛异常、不返回 null**：未知 kind 也要产出一条 Cue（`unknown.<kind>`），由 registry 的
 * 兜底配方画成中性飘字并**计数** —— 静默丢掉一条演出比画一个 `?` 更糟（§P5 的纪律）。
 */
export function translate(beat: BeatLike, eventId: number, context: CueContext): PresentationCue {
  const origin = originOf(beat.kind, beat.def);
  // 谁"动"：伤害/格挡/状态飘在被作用的人头上；出牌/回合飘在行动者身上（与 `planBeats` 一致）。
  const onActor =
    beat.kind === CUE_KIND.cardPlayed ||
    beat.kind === CUE_KIND.turnStarted ||
    beat.kind === CUE_KIND.turnEnded;
  const anchorSlot = onActor ? beat.actor : beat.target;
  return {
    eventId,
    kind: beat.kind,
    origin,
    actorSlot: beat.actor,
    targetSlot: beat.target,
    value: beat.a,
    effectKey: effectKeyOf(beat.kind, origin, beat.flags),
    phase: phaseOf(beat.kind),
    anchorSlot,
    appearanceId: context.appearanceOf(anchorSlot),
  };
}

/** 一批 Beat → 一批 Cue（顺序不变；`eventId` 由 `startId` 起递增）。 */
export function translateAll(
  beats: readonly BeatLike[],
  context: CueContext,
  startId = 0
): PresentationCue[] {
  return beats.map((beat, index) => translate(beat, startId + index, context));
}
