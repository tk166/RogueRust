// P1 的 Mock 局面：**不含 wasm**。
//
// 为什么是 Mock：P1 的退出条件写的是"Mock 模式演示可用"，P2 才把真实内核接进来。所以这里
// 只有"局面长什么样"和"每张牌能丢到哪儿"，没有任何 `rd_env_*` 调用。
//
// ⚠️ 但**卡名与规则文本取自真实内容**（`sts/content/cards.json` 的中文字段），不是现编的
// 占位串 —— 因为 P1 要回答的问题之一是"中文在 390×844 上读得出来吗"，用编的短字符串会把
// 字形数量与最长行都测小。

export type CardKind = "attack" | "skill" | "power";

export interface MockCard {
  readonly id: string;
  readonly name: string;
  readonly cost: number;
  readonly kind: CardKind;
  /** 是否需要指定敌人。`false` = 技能/能力牌，丢在哪儿都算数。 */
  readonly targeted: boolean;
  /** 卡面规则文本（真实内容里的 `desc`）。 */
  readonly rules: string;
}

export interface MockEnemy {
  readonly slot: number;
  readonly id: string;
  readonly name: string;
  hp: number;
  readonly maxHp: number;
  /** 被指向时的标签（"造成 6 点伤害" 之类），P1 只用于高亮提示。 */
  readonly intent: string;
}

export interface MockHero {
  readonly name: string;
  hp: number;
  readonly maxHp: number;
  block: number;
  energy: number;
  readonly maxEnergy: number;
}

/**
 * 10 张手牌。名字与文本来自 `sts/content/cards.json`（12 张的那份中文内容），
 * 顺序刻意混排：前四张是**有目标**的攻击牌，中间夹**无目标**技能/能力牌，
 * 这样"单敌 / 多敌 / 无目标"三种拖拽路径在同一屏里都能被点到。
 */
export const HAND: readonly MockCard[] = [
  { id: "strike", name: "打击", cost: 1, kind: "attack", targeted: true, rules: "造成 6 点伤害。" },
  { id: "defend", name: "防御", cost: 1, kind: "skill", targeted: false, rules: "获得 5 点格挡。" },
  { id: "bash", name: "痛击", cost: 2, kind: "attack", targeted: true, rules: "造成 8 点伤害。施加 2 层易伤。" },
  { id: "iron_wave", name: "铁斩", cost: 1, kind: "attack", targeted: true, rules: "获得 5 点格挡。造成 5 点伤害。" },
  { id: "inflame", name: "燃心", cost: 1, kind: "power", targeted: false, rules: "获得 2 点力量。" },
  { id: "cleave", name: "顺劈", cost: 1, kind: "attack", targeted: false, rules: "对所有敌人造成 8 点伤害。" },
  { id: "twin_strike", name: "双重打击", cost: 1, kind: "attack", targeted: true, rules: "造成 5 点伤害，两次。" },
  { id: "shrug_it_off", name: "耸肩", cost: 1, kind: "skill", targeted: false, rules: "获得 8 点格挡。抽 1 张牌。" },
  { id: "pommel_strike", name: "柄击", cost: 1, kind: "attack", targeted: true, rules: "造成 9 点伤害。抽 1 张牌。" },
  { id: "metallicize", name: "金属化", cost: 1, kind: "power", targeted: false, rules: "在你的回合结束时，获得 3 点格挡。" },
];

export interface MockScene {
  hero: MockHero;
  enemies: MockEnemy[];
  hand: readonly MockCard[];
  turn: number;
}

export function initialScene(): MockScene {
  return {
    hero: { name: "铁甲战士", hp: 72, maxHp: 80, block: 0, energy: 3, maxEnergy: 3 },
    enemies: [
      { slot: 0, id: "acid_slime_m", name: "酸液史莱姆", hp: 32, maxHp: 32, intent: "攻击 10" },
      { slot: 1, id: "jaw_worm", name: "颚虫", hp: 44, maxHp: 44, intent: "攻击 11" },
    ],
    hand: HAND,
    turn: 1,
  };
}

/** 活着的敌人槽位（P1 只用来算合法落点；死亡剔除的逻辑在 P2 由内核给）。 */
export function liveEnemySlots(scene: MockScene): number[] {
  return scene.enemies.filter((enemy) => enemy.hp > 0).map((enemy) => enemy.slot);
}
