// `CombatView`：**渲染层唯一认识的数据形状**。
//
// 为什么需要这一层：`Stage` / `TextOverlay` 不该知道数据是 Mock 还是真 wasm。它们只认识
// "有几张牌、每张叫什么、敌人剩多少血"。两个生产者（`viewFromMock` / `viewFromWasm`）把它填出来：
//
//   MockScene  ──┐
//                ├──> CombatView ──> Stage / TextOverlay / HUD
//   wasm 快照  ──┘
//
// ⚠️ 字段名刻意与 P1 的 `MockScene` 保持一致（`hand` / `enemies` / `hero` / `turn`），这样
// 换数据源不用改渲染代码 —— 少改一行就少一个"顺手改坏"的机会。
//
// ⚠️ **渲染层不许自己推规则**：每张牌能丢到哪儿（`optionsFor`）必须来自生产者：
// wasm 那边是内核的动作表，mock 那边是演示逻辑。P1 的教训（§352）就是"UI 自己猜落点"。

import type { DropOption } from "../input/pointerMachine";
import { liveEnemySlots, type MockScene } from "../mock/scene";
import type { CombatSnapshot } from "../wasm/snapshot";

export type CardKind = "attack" | "skill" | "power";

export interface ViewCard {
  readonly id: string;
  readonly name: string;
  readonly cost: number | "X";
  readonly kind: CardKind;
  readonly targeted: boolean;
  readonly rules: string;
  /** 费用够不够（wasm 的动作表已经过滤过"能不能出"，这里只用于灰化显示）。 */
  readonly playable: boolean;
}

export interface ViewEnemy {
  readonly slot: number;
  readonly id: string;
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly alive: boolean;
  /** 一行意图文本（"攻击 9" / "未知"）。wasm 给 kind+damage，这里只做展示。 */
  readonly intent: string;
}

export interface ViewHero {
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly energy: number;
  readonly maxEnergy: number;
}

export type ViewResult = "ongoing" | "victory" | "defeat" | "draw" | "aborted";

export interface CombatView {
  readonly mode: "mock" | "wasm";
  readonly hero: ViewHero;
  readonly enemies: readonly ViewEnemy[];
  readonly hand: readonly ViewCard[];
  readonly turn: number;
  readonly round: number;
  readonly result: ViewResult;
  /** 这张牌此刻允许的落点。**唯一来源**：wasm 是内核动作表，mock 是演示逻辑。 */
  optionsFor(handSlot: number): DropOption[];
  /** 结束回合的落点（`null` = 现在不能结束回合）。 */
  endTurnOption(): DropOption | null;
}

/** 意图种类（`env-abi.md` 的 `ActionIntent` 顺序）。`-1` = 未产生。 */
const INTENT_NAMES = ["未知", "攻击", "格挡", "增益", "减益", "特殊"];

function intentText(kind: number, damage: number): string {
  if (kind < 0) return "未知";
  const label = INTENT_NAMES[kind] ?? "未知";
  if (kind === 1 && damage >= 0) return `${label} ${damage}`;
  return label;
}

/**
 * 卡牌"种类"（决定牌面颜色）。
 *
 * ⚠️ **这是展示层的猜测，不是内核事实**：观察向量与动作表都没有"这张牌是攻击/技能/能力"，
 * ABI 冻结的只有 `def_slot`。这里按规则文本里有没有 `damage` 猜，猜错只影响配色。
 * 要变成事实，得让内核在观察向量里加一格（那是 ABI 变更，P3 再说）。
 */
function guessKind(rules: string): CardKind {
  return /damage|damage\./i.test(rules) ? "attack" : "skill";
}

export interface WasmNames {
  cardName(slot: number): string;
  cardText(slot: number): string;
  enemyName(slot: number): string;
}

/**
 * 从**真实内核快照**建视图。
 *
 * `optionsFor` 直接读内核动作表：一张牌有哪些落点、每条动作的 `actionIndex` 是什么，
 * 全部由 `rd_env_action_*` 说了算。UI 不再自己算"能不能打这个敌人"。
 */
export function viewFromWasm(snapshot: CombatSnapshot, names: WasmNames): CombatView {
  const hand: ViewCard[] = snapshot.hand.map((card) => {
    const rules = names.cardText(card.slot);
    const actions = snapshot.actions.filter(
      (action) => action.kind === "play" && action.handSlot === card.slot
    );
    return {
      id: `hand-${card.slot}-${card.defSlot}`,
      name: names.cardName(card.slot),
      cost: card.cost,
      kind: guessKind(rules),
      // "需要目标"由内核决定：存在 `targetSlot >= 0` 的动作就是定向牌。
      targeted: actions.some((action) => action.targetSlot >= 0),
      rules,
      playable: actions.length > 0,
    };
  });

  return {
    mode: "wasm",
    hero: {
      name: "铁甲战士",
      hp: snapshot.hero.hp,
      hpMax: snapshot.hero.hpMax,
      block: snapshot.hero.block,
      energy: snapshot.hero.energy,
      maxEnergy: snapshot.hero.energyMax,
    },
    enemies: snapshot.enemies.map((enemy) => ({
      slot: enemy.slot,
      id: `enemy-${enemy.slot}`,
      name: names.enemyName(enemy.slot),
      hp: enemy.hp,
      hpMax: enemy.hpMax,
      block: enemy.block,
      alive: enemy.alive,
      intent: intentText(enemy.intentKind, enemy.intentDamage),
    })),
    hand,
    turn: snapshot.turn,
    round: snapshot.round,
    result: snapshot.result,
    optionsFor(handSlot: number): DropOption[] {
      return snapshot.actions
        .filter((action) => action.kind === "play" && action.handSlot === handSlot)
        .map((action) => ({
          slot: action.targetSlot,
          actionIndex: action.index,
          label:
            action.targetSlot >= 0
              ? `${names.cardName(handSlot)} → 敌人 ${action.targetSlot}`
              : `打出 ${names.cardName(handSlot)}`,
        }));
    },
    endTurnOption(): DropOption | null {
      const action = snapshot.actions.find((candidate) => candidate.kind === "endTurn");
      return action ? { slot: -1, actionIndex: action.index, label: "结束回合" } : null;
    },
  };
}

/**
 * 从 **Mock 局面**建视图（P1 的那条路径，`?mock` 下仍在用）。
 *
 * 保留它的理由：P1 的 94 条浏览器断言全部建立在"确定的 10 张牌 / 2 个敌人"上，
 * 换成真 wasm 之后那些断言的**含义**会变（牌是随机的、敌人血会变）。所以两条路并存：
 * `?mock` 走确定局面（P1 的渲染/手势回归），默认走真 wasm（P2 的数据源回归）。
 */
export function viewFromMock(scene: MockScene): CombatView {
  return {
    mode: "mock",
    hero: {
      name: scene.hero.name,
      hp: scene.hero.hp,
      hpMax: scene.hero.maxHp,
      block: scene.hero.block,
      energy: scene.hero.energy,
      maxEnergy: scene.hero.maxEnergy,
    },
    enemies: scene.enemies.map((enemy) => ({
      slot: enemy.slot,
      id: enemy.id,
      name: enemy.name,
      hp: enemy.hp,
      hpMax: enemy.maxHp,
      block: 0,
      alive: enemy.hp > 0,
      intent: enemy.intent,
    })),
    hand: scene.hand.map((card) => ({
      // ⚠️ id 保持原样：P1 的闸门按 `strike` 这样的 id 断言。重复 id 不影响 React key
      // （`Stage` 用的是 `card.id + index`）。
      id: card.id,
      name: card.name,
      cost: card.cost,
      kind: card.kind,
      targeted: card.targeted,
      rules: card.rules,
      playable: true,
    })),
    turn: scene.turn,
    round: 1,
    result: "ongoing",
    optionsFor(handSlot: number): DropOption[] {
      const card = scene.hand[handSlot];
      if (!card) return [];
      if (!card.targeted) {
        return [{ slot: -1, actionIndex: handSlot * 10, label: `打出 ${card.name}` }];
      }
      return liveEnemySlots(scene).map((slot) => ({
        slot,
        actionIndex: handSlot * 10 + slot + 1,
        label: `${card.name} → 敌人 ${slot}`,
      }));
    },
    endTurnOption: () => null,
  };
}
