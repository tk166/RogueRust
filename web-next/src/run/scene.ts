// **场景判定**：一个纯函数，把"内核事实"翻成"现在该显示哪一屏"。
//
// ## 为什么必须纯、必须**穷尽**
//
// 旧页面（`web/ui_panels.js`）用一个 if 链判场景，靠 `mode` 变量区分"站在战斗节点上"与
// "正在打"——那是**页面自己记的状态**，纯函数判不出来，于是"刷新一下回到地图"这种 bug
// 只能靠人肉试。这里把判据全部换成内核导出（`docs/ui-state-model.md` 的 18 行表）。
//
// 两条**顺序陷阱**（表里专门写了"为什么排在这里"）：
//   * `SC-03b`（正在打）必须排在 `SC-03`（站在战斗节点上）**之前** —— 两者都是
//     `pending == 0`，只有 `in_fight` 不同；反过来就永远看不到战斗屏。
//   * `SC-02b`（幕尽头）必须排在 `SC-02`（地图兜底）**之前** —— 两者都是 `pending == 0`，
//     `SC-02` 是兜底；反过来 `SC-02b` **永远不可达**（八轮 Review 3.1 的第二处）。
//
// 所以规则是**有序表**而不是 if 链：顺序是数据，闸门 33 直接断言顺序（见 `SCENE_ORDER`）。
//
// ## 覆盖层（overlay）
//
// `SC-11a`（遗物欠账·改牌）/`SC-11b`（加牌）是**弹在某一屏之上**的，不是"另一屏"：
// 它们的 `base` 仍然是原来那一屏。`resolveScene` 同时给出 `base` 与 `overlays`，
// 两者共用同一份事实 ⇒ 判据不会漂。

import { NODE_KIND, UNKNOWN_ROOM, type UnknownRoom } from "./observe.js";

export const SCENE = {
  title: "SC-00",
  blessing: "SC-01",
  blessingCard: "SC-01b",
  map: "SC-02",
  actEnd: "SC-02b",
  preCombat: "SC-03",
  combat: "SC-03b",
  reward: "SC-04",
  shop: "SC-05",
  rest: "SC-06",
  chest: "SC-07",
  event: "SC-08",
  eventCard: "SC-09",
  eventOffer: "SC-10",
  pickupChange: "SC-11a",
  pickupAdd: "SC-11b",
  actCleared: "SC-12a",
  over: "SC-12b",
} as const;

export type SceneId = (typeof SCENE)[keyof typeof SCENE];

/** 判定用的**全部**内核事实。任何一项缺失都不许猜 —— 缺就是 `undefined` 传不进来。 */
export interface SceneInput {
  /** `rd_run_exists() == 1`。⚠️ 不要用 seed 哨兵（`i32::MIN` 是合法 seed）。 */
  readonly runExists: boolean;
  /** `rd_run_in_fight() == 1`。 */
  readonly inFight: boolean;
  /**
   * 战斗会话**真的在**（`rd_env_observe_len` 读得到、有快照）。
   *
   * 与 `inFight` 分开是因为两者会短暂不一致（`fight_begin` 之后、会话建好之前），
   * 而"屏上有没有战斗"应该看会话。不一致本身是个诊断项（闸门 34 断言它恒等）。
   */
  readonly hasCombatSession: boolean;
  readonly pending: number;
  readonly over: number;
  readonly bossBeaten: boolean;
  readonly nodeKind: number;
  /**
   * `rd_run_node_resolved() == 1`：这一格**已经结算过**（打完/开完/离开）。
   *
   * ⚠️ 这是 `SC-03` 与 `SC-02` 的分界线，第一版漏了它：领完奖励后 `pending` 回到 0，
   * 而脚下那格的 `kind` 仍然是 `Combat` ⇒ 判成"战斗前"，界面把**已经打完的格子**又画成
   * "进入战斗"，点下去内核拒绝。判据必须是"这一格还在等我"而不是"这一格是战斗"。
   */
  readonly nodeResolved: boolean;
  readonly unknownRoom: UnknownRoom;
  readonly eventFight: number;
  readonly actionCount: number;
  readonly pickupPicks: number;
  readonly pickupAdd: number;
}

export interface SceneResolution {
  /** 底下的那一屏（永远是**非**覆盖层）。 */
  readonly base: SceneId;
  /** 弹在 `base` 之上的覆盖层（0..2 个）。 */
  readonly overlays: readonly SceneId[];
  /**
   * `pending` 不在 0..9 时它的原值。
   *
   * ⚠️ 这不是"未知场景"的兜底通道：`base` 仍然是地图（兜底），但界面必须**响亮**显示
   * "内核给了我没见过的相位 N" —— 静默画地图会让"内核加了新相位而 UI 没跟上"看起来正常。
   */
  readonly unknownPending: number | null;
}

/**
 * 判定顺序（**这是语义，不是实现细节**）。闸门 33 断言它。
 *
 * 覆盖层不在这个表里：它们是 `OVERLAY_ORDER`。
 */
export const SCENE_ORDER: readonly SceneId[] = [
  SCENE.title,
  SCENE.combat,
  SCENE.over,
  SCENE.actCleared,
  SCENE.blessing,
  SCENE.blessingCard,
  SCENE.eventCard,
  SCENE.eventOffer,
  SCENE.reward,
  SCENE.event,
  SCENE.chest,
  SCENE.shop,
  SCENE.rest,
  SCENE.preCombat,
  SCENE.actEnd,
  SCENE.map,
];

export const OVERLAY_ORDER: readonly SceneId[] = [SCENE.pickupChange, SCENE.pickupAdd];

/**
 * `pending` → 场景（`run-layer.md` §4.7 的相位机编号）。
 *
 * ⚠️ 这张表与内核的 `Pending` 枚举是"同一个词表两处认识"。护栏是闸门 33 的**穷尽**断言：
 * 0..9 每一档都必须在表里，且 `pending == 0` 不许有值（0 不是相位，是"没有待决屏"）。
 */
export const PENDING_SCENE: Readonly<Record<number, SceneId>> = {
  1: SCENE.rest,
  2: SCENE.shop,
  3: SCENE.chest,
  4: SCENE.reward,
  5: SCENE.event,
  6: SCENE.blessing,
  7: SCENE.blessingCard,
  8: SCENE.eventCard,
  9: SCENE.eventOffer,
};

/**
 * 判定"现在该显示哪一屏"。**穷尽**：任何输入都返回一个 `base`。
 *
 * 规则按 `SCENE_ORDER` 的顺序逐条试，第一条命中的就是 `base`。
 */
export function resolveScene(input: SceneInput): SceneResolution {
  const overlays: SceneId[] = [];
  if (input.pickupPicks > 0) overlays.push(SCENE.pickupChange);
  if (input.pickupAdd > 0) overlays.push(SCENE.pickupAdd);

  const unknownPending =
    input.pending >= 0 && input.pending <= 9 ? null : input.pending;

  const base = firstMatch(input);
  return { base, overlays, unknownPending };
}

function firstMatch(input: SceneInput): SceneId {
  // 1. 未开局。⚠️ 不用 seed 哨兵（`i32::MIN` 是合法 seed）。
  if (!input.runExists) return SCENE.title;

  // 2. 战斗中。**必须**排在 SC-03 之前：两者都是 pending == 0。
  if (input.inFight && input.hasCombatSession) return SCENE.combat;

  // 3. 局终。
  if (input.over === 1) return SCENE.over;

  // 4. 幕通关（打赢 Boss 但还没 over）。
  if (input.bossBeaten && input.over !== 1) return SCENE.actCleared;

  // 5..13. 有相位：pending 决定一切。
  if (input.pending !== 0) {
    const mapped = PENDING_SCENE[input.pending];
    // 未知相位：**兜底到地图**，但 `unknownPending` 会让界面显示诊断（不静默）。
    return mapped ?? SCENE.map;
  }

  // 14. 站在战斗节点上但还没开打（`?` 房只有掷出"怪物"才算）。
  //     ⚠️ `nodeResolved === false` 是判据的一半：打完的格子 `kind` 仍然是 `Combat`，
  //     少了这一条，领完奖励会回到"战斗前"（点下去被内核拒绝）。
  const fightHere =
    !input.nodeResolved &&
    (input.nodeKind === NODE_KIND.combat ||
    input.nodeKind === NODE_KIND.elite ||
    input.nodeKind === NODE_KIND.boss ||
      (input.nodeKind === NODE_KIND.unknown && input.unknownRoom === UNKNOWN_ROOM.monster) ||
      input.eventFight > 0);
  if (!input.inFight && fightHere) return SCENE.preCombat;

  // 15. 幕尽头（没有可选动作、站在某个节点上）。**必须**排在 SC-02 之前。
  if (!input.inFight && input.actionCount === 0 && input.nodeKind >= 0) return SCENE.actEnd;

  // 16. 地图（兜底）。
  return SCENE.map;
}

/** 这一屏在 P3 里**实现了**吗（没实现的走 `UnsupportedScene`，见 `scenes/UnsupportedScene.tsx`）。 */
export function isImplemented(scene: SceneId): boolean {
  switch (scene) {
    case SCENE.title:
    case SCENE.blessing:
    case SCENE.map:
    case SCENE.preCombat:
    case SCENE.combat:
    case SCENE.reward:
    case SCENE.over:
    case SCENE.actCleared:
    case SCENE.actEnd:
    case SCENE.pickupChange:
    case SCENE.pickupAdd:
      return true;
    default:
      return false;
  }
}

/** 场景的中文名（顶栏面包屑与诊断都用它）。 */
export function sceneLabel(scene: SceneId): string {
  switch (scene) {
    case SCENE.title:
      return "标题";
    case SCENE.blessing:
      return "塔底祝福";
    case SCENE.blessingCard:
      return "祝福选牌";
    case SCENE.map:
      return "地图";
    case SCENE.actEnd:
      return "幕尽头";
    case SCENE.preCombat:
      return "战斗前";
    case SCENE.combat:
      return "战斗中";
    case SCENE.reward:
      return "战斗奖励";
    case SCENE.shop:
      return "商店";
    case SCENE.rest:
      return "篝火";
    case SCENE.chest:
      return "宝箱";
    case SCENE.event:
      return "事件";
    case SCENE.eventCard:
      return "事件选牌";
    case SCENE.eventOffer:
      return "事件候选";
    case SCENE.pickupChange:
      return "遗物·改牌";
    case SCENE.pickupAdd:
      return "遗物·加牌";
    case SCENE.actCleared:
      return "幕通关";
    case SCENE.over:
      return "局终";
    default:
      return String(scene);
  }
}
