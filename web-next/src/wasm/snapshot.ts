// 战斗观察向量的**纯解码器**：`Int32Array` → `CombatSnapshot`。
//
// 为什么单独一个文件、且不碰 wasm：解码是最容易搞错的地方（148 格、六种哨兵语义），
// 而它**不需要 wasm 就能测** —— 闸门 27 用合成向量把边界（空槽 `-1`、X 费 `-2`、保留位）全覆盖。
//
// ## 布局的唯一权威
//
// `kernel/rd-wasm/src/lib.rs` 里的 `OFF_*` 常量（`OBS_LEN = OFF_RESERVED + 8 = 148`）。
// 这里的下标**照抄**那份布局；`rd_env_observe_len()` 由模块自己报，长度对不上时 host 会拒绝
// 装载（不许写死 148 —— 见 `docs/ui-abi-audit.md` §2.3）。
//
// ⚠️ 这份下标表与 Rust 侧是"同一个词表两处认识"。护栏是 `host.ts` 的装载校验（长度 + 哨兵）
// 加闸门 28 的**真实战斗**断言（手牌数/能量/敌人血与内核一致）。改布局时两处一起改。

/** 头部 12 格。 */
const H_ROUND = 0;
const H_TURN = 1;
const H_PHASE = 2;
const H_RESULT = 3;
const H_HERO_HP = 4;
const H_HERO_HP_MAX = 5;
const H_HERO_BLOCK = 6;
// 7 = `ward`：这一版内容不产生它（恒 `-1`），故意不解码，所以这里不留常量。
const H_ENERGY = 8;
const H_ENERGY_MAX = 9;
const H_HAND_COUNT = 10;
const H_ENEMY_COUNT = 11;

const OFF_HERO_STATUS = 12;
const MAX_ENEMY_SLOTS = 6;
const OFF_ENEMY = OFF_HERO_STATUS + 5;
const OFF_ENEMY_STATUS = OFF_ENEMY + MAX_ENEMY_SLOTS * 8;
const MAX_HAND_SLOTS = 10;
const OFF_HAND = OFF_ENEMY_STATUS + MAX_ENEMY_SLOTS * 5;
const OFF_PILES = OFF_HAND + MAX_HAND_SLOTS * 4;
/** 牌堆五格：抽牌堆、手牌、弃牌堆、消耗堆、队列。**这些是计数，0 有意义**。 */
const PILE_KEYS = ["draw", "hand", "discard", "exhaust", "queue"] as const;

/** 手牌费用格里的"这不是数字费"：页面画成 `X`。 */
export const X_COST_DISPLAY = -2;

/** 五条状态轴，**ABI 顺序**（不是字母序）。 */
export const STATUS_AXES = ["strength", "vulnerable", "weak", "dexterity", "frail"] as const;
export type StatusAxis = (typeof STATUS_AXES)[number];
export type Statuses = Readonly<Record<StatusAxis, number>>;

export type TurnPhase = "waiting" | "inProgress";
export type CombatResult = "ongoing" | "victory" | "defeat" | "draw" | "aborted";
export type ActionKind = "play" | "endTurn";

export interface HandCard {
  /** 手牌槽位（0..9）。动作表的 `arg0` 就是它。 */
  readonly slot: number;
  /** 数字费用；X 费牌是 `"X"`（ABI 给 `-2`）。 */
  readonly cost: number | "X";
  /** 内容镜像里的定义槽位（`def_slot`）。ABI 冻结的那一半。 */
  readonly defSlot: number;
  readonly upgraded: boolean;
}

export interface EnemyView {
  readonly slot: number;
  readonly alive: boolean;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  /** `-1` = 这一格没有意图（ABI 的"未产生"）。 */
  readonly intentKind: number;
  readonly intentDamage: number;
  readonly statuses: Statuses;
}

export interface CombatAction {
  readonly index: number;
  readonly kind: ActionKind;
  /** `play` 时是手牌槽位；`endTurn` 时是 `-1`。 */
  readonly handSlot: number;
  /** `play` 时的目标敌人槽位；`-1` = 无目标（不是"敌人 0"）。 */
  readonly targetSlot: number;
}

export interface CombatSnapshot {
  readonly round: number;
  readonly turn: number;
  readonly phase: TurnPhase;
  readonly result: CombatResult;
  readonly hero: {
    readonly hp: number;
    readonly hpMax: number;
    readonly block: number;
    readonly energy: number;
    readonly energyMax: number;
    readonly statuses: Statuses;
  };
  readonly enemies: readonly EnemyView[];
  readonly hand: readonly HandCard[];
  readonly handCount: number;
  readonly piles: Readonly<Record<(typeof PILE_KEYS)[number], number>>;
  readonly actions: readonly CombatAction[];
}

const emptyStatuses = (): Record<StatusAxis, number> => ({
  strength: 0,
  vulnerable: 0,
  weak: 0,
  dexterity: 0,
  frail: 0,
});

function readStatuses(obs: ArrayLike<number>, base: number): Statuses {
  const out = emptyStatuses();
  STATUS_AXES.forEach((axis, index) => {
    out[axis] = obs[base + index];
  });
  return out;
}

function phaseOf(code: number): TurnPhase {
  if (code === 0) return "waiting";
  if (code === 1) return "inProgress";
  throw new RangeError(`unknown turn phase ${code}`);
}

function resultOf(code: number): CombatResult {
  switch (code) {
    case 0:
      return "ongoing";
    case 1:
      return "victory";
    case 2:
      return "defeat";
    case 3:
      return "draw";
    case 4:
      return "aborted";
    default:
      throw new RangeError(`unknown combat result ${code}`);
  }
}

/**
 * 解码 148 格战斗向量。`actions` 来自动作表（另一个导出），因为向量里没有它。
 *
 * ⚠️ **空槽是 `-1`，不是 0**：敌人槽 `alive === -1` 表示这一格根本没有敌人；手牌槽
 * `occupied` 也是 `1/-1`。把它们当 0 会渲染出"血量 0 的敌人"和"费用 0 的牌"。
 */
export function decodeCombat(
  obs: ArrayLike<number>,
  actions: readonly CombatAction[]
): CombatSnapshot {
  if (obs.length < OFF_PILES + PILE_KEYS.length) {
    throw new RangeError(`observation too short: ${obs.length}`);
  }

  const enemies: EnemyView[] = [];
  for (let slot = 0; slot < MAX_ENEMY_SLOTS; slot += 1) {
    const base = OFF_ENEMY + slot * 8;
    const alive = obs[base];
    if (alive < 0) continue; // 空槽：整格都是 -1
    enemies.push({
      slot,
      alive: alive === 1,
      hp: obs[base + 1],
      hpMax: obs[base + 2],
      block: obs[base + 3],
      intentKind: obs[base + 5],
      intentDamage: obs[base + 6],
      statuses: readStatuses(obs, OFF_ENEMY_STATUS + slot * 5),
    });
  }

  // 向量自报的敌人数量必须与"扫槽位、跳过 -1"的结果一致 —— 不一致说明布局或哨兵语义漂了，
  // 与其渲染出"少一个敌人"，不如当场炸。
  const declaredEnemies = obs[H_ENEMY_COUNT];
  if (declaredEnemies !== enemies.length) {
    throw new RangeError(
      `header says ${declaredEnemies} enemies, layout says ${enemies.length}`
    );
  }

  const handCount = obs[H_HAND_COUNT];
  const hand: HandCard[] = [];
  for (let slot = 0; slot < Math.min(handCount, MAX_HAND_SLOTS); slot += 1) {
    const base = OFF_HAND + slot * 4;
    if (obs[base] !== 1) continue;
    const rawCost = obs[base + 1];
    hand.push({
      slot,
      cost: rawCost === X_COST_DISPLAY ? "X" : rawCost,
      defSlot: obs[base + 2],
      upgraded: obs[base + 3] === 1,
    });
  }

  const piles = Object.fromEntries(PILE_KEYS.map((key, index) => [key, obs[OFF_PILES + index]])) as Record<
    (typeof PILE_KEYS)[number],
    number
  >;

  return {
    round: obs[H_ROUND],
    turn: obs[H_TURN],
    phase: phaseOf(obs[H_PHASE]),
    result: resultOf(obs[H_RESULT]),
    hero: {
      hp: obs[H_HERO_HP],
      hpMax: obs[H_HERO_HP_MAX],
      block: obs[H_HERO_BLOCK],
      // `ward`（H_HERO_WARD）这一版内容不产生，恒 `-1`，故意不暴露。
      energy: obs[H_ENERGY],
      energyMax: obs[H_ENERGY_MAX],
      statuses: readStatuses(obs, OFF_HERO_STATUS),
    },
    enemies,
    hand,
    handCount,
    piles,
    actions,
  };
}

/** 动作表的一行（`rd_env_action_kind` / `_arg(i,0)` / `_arg(i,1)`）。 */
export function decodeAction(index: number, kind: number, arg0: number, arg1: number): CombatAction {
  if (kind === 0) return { index, kind: "play", handSlot: arg0, targetSlot: arg1 };
  if (kind === 1) return { index, kind: "endTurn", handSlot: -1, targetSlot: -1 };
  throw new RangeError(`unknown action kind ${kind}`);
}
