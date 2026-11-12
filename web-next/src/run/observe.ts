// 运行层观察向量的**纯解码器**：i32 → `RunSnapshot` / `MapModel`。
//
// 与 `wasm/snapshot.ts` 同一纪律：下标表是"同一个词表两处认识"（`kernel/rd-wasm/src/run.rs`
// 的 `RUN_OBS_*` 与 `NODE_FIELD_*`），护栏是 `host.ts` 的装载校验（`rd_run_observe_len` 自报）
// 加闸门 33 的合成向量夹具 + 闸门 34 的真实对账（HP/gold/牌组数与内核一致）。
//
// ⚠️ 这一层**不认识** wasm：它收的是已经读出来的数字数组。所以闸门 33 不需要浏览器。

/** `env-abi.md` §11.3 的 19 格。 */
const O_FLOOR = 0;
const O_NODE = 1;
const O_HEALTH = 2;
const O_HEALTH_MAX = 3;
const O_GOLD = 4;
const O_DECK_SIZE = 5;
const O_RELIC_COUNT = 6;
const O_POTION_COUNT = 7;
const O_MAP_LEN = 8;
/** 9..15 七条 RNG 流的计数器（`run-layer.md` §3.2），按 stream id 1..=7 升序。 */
const O_RNG_FIRST = 9;
const RNG_STREAMS = 7;
const O_REACHABLE = 16;
const O_REMOVED = 17;
const O_UNKNOWN_ROOM = 18;

/** `env-abi.md` §11.2 的地图节点字段。 */
const N_ROW = 0;
const N_COL = 1;
const N_KIND = 2;
const N_OUT_DEGREE = 3;
const N_EDGE_FIRST = 4;
const N_EDGE_LAST = 6;
const N_REACHABLE = 7;

/**
 * 节点类型（`run-layer.md` §7.2 的判别值，**数字是 ABI**）。
 *
 * ⚠️ `unassigned = 0` 不是"普通战斗"：零初始化的 `RunState` 全是 0，所以它必须是
 * "不该被玩到"的值。UI 见到它要**响亮失败**，不能当空地画。
 */
export const NODE_KIND = {
  unassigned: 0,
  combat: 1,
  elite: 2,
  rest: 3,
  shop: 4,
  unknown: 5,
  treasure: 6,
  boss: 7,
  bossChest: 8,
} as const;

export type NodeKindValue = (typeof NODE_KIND)[keyof typeof NODE_KIND];

/** `?` 房掷出来的东西（`env-abi.md` §11.3 第 18 格，§272）。 */
export const UNKNOWN_ROOM = {
  none: 0,
  event: 1,
  monster: 2,
  merchant: 3,
  treasure: 4,
} as const;

export type UnknownRoom = (typeof UNKNOWN_ROOM)[keyof typeof UNKNOWN_ROOM];

export interface RunSnapshot {
  /** 1..=15 在地图上；`0` = 还没出发。 */
  readonly floor: number;
  /** 当前节点的**全局**下标；`-1` = 还没出发。 */
  readonly node: number;
  readonly health: number;
  readonly healthMax: number;
  readonly gold: number;
  readonly deckSize: number;
  readonly relicCount: number;
  readonly potionCount: number;
  readonly mapLen: number;
  /** 七条 RNG 流的计数器（只用于诊断/复现，UI 不显示）。 */
  readonly rng: readonly number[];
  readonly reachableCount: number;
  readonly removedCards: number;
  readonly unknownRoom: UnknownRoom;
}

/** 解码 19 格运行层向量。长度不足**响亮失败**（不静默补 0）。 */
export function decodeRun(obs: ArrayLike<number>): RunSnapshot {
  if (obs.length < O_UNKNOWN_ROOM + 1) {
    throw new RangeError(`run observation too short: ${obs.length} < ${O_UNKNOWN_ROOM + 1}`);
  }
  const rng: number[] = [];
  for (let index = 0; index < RNG_STREAMS; index += 1) rng.push(obs[O_RNG_FIRST + index]);
  return {
    floor: obs[O_FLOOR],
    node: obs[O_NODE],
    health: obs[O_HEALTH],
    healthMax: obs[O_HEALTH_MAX],
    gold: obs[O_GOLD],
    deckSize: obs[O_DECK_SIZE],
    relicCount: obs[O_RELIC_COUNT],
    potionCount: obs[O_POTION_COUNT],
    mapLen: obs[O_MAP_LEN],
    rng,
    reachableCount: obs[O_REACHABLE],
    removedCards: obs[O_REMOVED],
    unknownRoom: obs[O_UNKNOWN_ROOM] as UnknownRoom,
  };
}

export interface MapNode {
  /** **全局**下标（`rd_run_step` 用不到它，`map_node` 的出边用它）。 */
  readonly index: number;
  readonly row: number;
  readonly col: number;
  readonly kind: number;
  /** 出边的全局下标（0..3 条）。 */
  readonly edges: readonly number[];
  readonly reachable: boolean;
}

export interface MapModel {
  readonly rows: number;
  readonly nodes: readonly MapNode[];
  /** 全局下标 → 节点。 */
  readonly byIndex: ReadonlyMap<number, MapNode>;
  /**
   * 布局：**归一化**坐标（0..1），`y = 0` 是第 1 行（底部），`y = 1` 是 Boss 行。
   *
   * 为什么归一化：像素坐标是渲染层的选择（CSS 网格 / canvas / 3D 都可能），
   * 而"谁在谁上面、谁和谁连线"是**模型**。闸门只断言后者。
   */
  readonly layout: ReadonlyMap<number, { x: number; y: number }>;
}

/**
 * 把 `map_node` 的原始数字拼成模型。
 *
 * `readNode(index)` 返回该节点的 8 个字段（`i32::MIN` = 越界，调用方负责跳过）。
 * 这里收一个读取函数而不是数组，是为了让闸门能用**合成**地图而不需要 wasm。
 */
export function buildMap(
  nodeCount: number,
  rows: number,
  readNode: (index: number, field: number) => number
): MapModel {
  const nodes: MapNode[] = [];
  const byIndex = new Map<number, MapNode>();
  const layout = new Map<number, { x: number; y: number }>();
  let maxCol = 0;

  for (let index = 0; index < nodeCount; index += 1) {
    const row = readNode(index, N_ROW);
    const col = readNode(index, N_COL);
    const kind = readNode(index, N_KIND);
    if (row < 0 || col < 0 || kind < 0) continue; // 越界/不存在的节点：不画
    // ⚠️ **先检查再截断**：第一版写成 `Math.min(3, readNode(...))` 然后再比 `> 3`，
    // 于是那条断言永远不可能成立（守卫装在了切口**下游** —— 见 docs/port-plan.md §4.19）。
    // 出边字段只有 3 个（4..6），越界就是布局或约定漂了，必须响亮失败而不是静默少画两条线。
    const degree = readNode(index, N_OUT_DEGREE);
    if (degree < 0 || degree > N_EDGE_LAST - N_EDGE_FIRST + 1) {
      throw new RangeError(`node ${index} out_degree ${degree} 越界（0..3）`);
    }
    const edges: number[] = [];
    for (let slot = 0; slot < degree; slot += 1) {
      const target = readNode(index, N_EDGE_FIRST + slot);
      if (target >= 0) edges.push(target);
    }
    const node: MapNode = { index, row, col, kind, edges, reachable: readNode(index, N_REACHABLE) === 1 };
    nodes.push(node);
    byIndex.set(index, node);
    maxCol = Math.max(maxCol, col);
  }

  const lastRow = Math.max(1, rows - 1);
  for (const node of nodes) {
    layout.set(node.index, {
      x: maxCol === 0 ? 0.5 : node.col / maxCol,
      y: node.row / lastRow,
    });
  }

  return { rows, nodes, byIndex, layout };
}

/** 节点类型 → 中文标签（地图图例与"这一格是什么"都用它）。 */
export function nodeKindLabel(kind: number): string {
  switch (kind) {
    case NODE_KIND.combat:
      return "战斗";
    case NODE_KIND.elite:
      return "精英";
    case NODE_KIND.rest:
      return "篝火";
    case NODE_KIND.shop:
      return "商店";
    case NODE_KIND.unknown:
      return "未知";
    case NODE_KIND.treasure:
      return "宝箱";
    case NODE_KIND.boss:
      return "首领";
    case NODE_KIND.bossChest:
      return "首领宝箱";
    case NODE_KIND.unassigned:
      return "未分配";
    default:
      return `未知类型 ${kind}`;
  }
}

/** 节点类型 → 图标（**文本**符号：不依赖图标字体，闸门也能断言）。 */
export function nodeKindGlyph(kind: number): string {
  switch (kind) {
    case NODE_KIND.combat:
      return "⚔";
    case NODE_KIND.elite:
      return "☠";
    case NODE_KIND.rest:
      return "🔥";
    case NODE_KIND.shop:
      return "🛒";
    case NODE_KIND.unknown:
      return "?";
    case NODE_KIND.treasure:
      return "▣";
    case NODE_KIND.boss:
      return "♛";
    case NODE_KIND.bossChest:
      return "▤";
    default:
      return "·";
  }
}

/**
 * 这一格会不会**开一场战斗**（SC-03 的判据之一，`docs/ui-state-model.md` 第 16 行）。
 *
 * ⚠️ `unknown`（`?` 房）只有**已经掷出"怪物"**时才算 —— 掷之前它可能变成事件/商店。
 * 把 `?` 房一律当战斗会让"进去是个事件"的格子显示"进入战斗"。
 */
export function opensFight(kind: number, unknownRoom: UnknownRoom): boolean {
  if (kind === NODE_KIND.combat || kind === NODE_KIND.elite || kind === NODE_KIND.boss) return true;
  if (kind === NODE_KIND.unknown && unknownRoom === UNKNOWN_ROOM.monster) return true;
  return false;
}
