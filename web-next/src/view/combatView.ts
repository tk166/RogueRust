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

// ⚠️ 扩展名写全 `.js`：闸门 56 把本文件**直接编译成 ESM** 跑（不经打包器），
// Node 的 ESM 解析不猜扩展名。这是本仓库既有的约定（见 `i18n/index.ts` 的头注释）。
import type { DropOption } from "../input/pointerMachine.js";
import { liveEnemySlots, type MockScene } from "../mock/scene.js";
import type { CombatSnapshot } from "../wasm/snapshot.js";
import { displayName, displayText } from "../i18n/index.js";
import cardMeta from "./cardMeta.js";

/** 与 `cardMeta.ts` 的 `CardMeta["kind"]` 一致（内容包 `Tags` 的五种）。 */
export type CardKind = "attack" | "skill" | "power" | "status" | "curse";

export interface ViewCard {
  /**
   * **合成 id**（`hand-<slot>-<defSlot>`）：只用来当 React key / 命中标识。
   *
   * ⚠️ 它**不是**内容 id —— 拿它查素材表/中文表会走降级。内容 id 是 `defId`。
   */
  readonly id: string;
  /** 内容 id（`strike` / `strike+`）：素材表与 i18n 都按它查。 */
  readonly defId: string;
  readonly name: string;
  readonly cost: number | "X";
  readonly kind: CardKind;
  readonly targeted: boolean;
  readonly rules: string;
  /** 费用够不够（wasm 的动作表已经过滤过"能不能出"，这里只用于灰化显示）。 */
  readonly playable: boolean;
}

/**
 * 一个状态实例（§378）。`id` 是内容定义 id（`standard.strength` / `standard.constricted`），
 * `stacks` 是层数（可能为 1）。
 */
export interface ViewStatus {
  readonly id: string;
  /** 中文名（`statuses` 表；查不到退回 `id`）。 */
  readonly name: string;
  readonly stacks: number;
}

export interface ViewEnemy {
  readonly slot: number;
  /**
   * **合成 id**（`enemy-<slot>`）：只用来当 React key。
   *
   * ⚠️ 拿它查素材表会走降级（`enemyLook("enemy-0")` 命中哈希兜底 ⇒ 每只怪随机一个原型）。
   * 内容 id 是 `defId`（`cultist` / `spike_slime_m` …）。
   */
  readonly id: string;
  /** 内容 id（`cultist` / `spike_slime_m` …）：素材表与 i18n 都按它查。 */
  readonly defId: string;
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly alive: boolean;
  /** 一行意图文本（"攻击 9" / "未知"）。wasm 给 kind+damage，这里只做展示。 */
  readonly intent: string;
  /** 身上的状态（力量/易伤/虚弱/…，含观察向量里没有的那些，如 `constricted`）。 */
  readonly statuses: readonly ViewStatus[];
}

export interface ViewHero {
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly energy: number;
  readonly maxEnergy: number;
  readonly statuses: readonly ViewStatus[];
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
  /** 动作表版本号（手势提交前比对，见 `GameStore.stateEpoch`）。 */
  readonly epoch: number;
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
 * 卡牌的元数据（种类 / 要不要玩家选目标）—— **查表，不猜**。
 *
 * 上一版按规则文本里有没有 `damage` 猜种类（中文一来就全判成技能），并且用
 * `actions.some(targetSlot >= 0)` 反推"要不要目标" —— 后者是第十四轮 Review P1-A 的根因：
 * 内核**故意**为"每张可出的牌 × 每个活敌人"各发一条动作，`targetSlot` 是**枚举策略**，
 * 不是卡牌的目标声明。于是"防御"被当成定向牌，拖到空白处会被回弹（实测：能量/格挡/手牌都不变）。
 */
function metaOf(cardId: string): { kind: CardKind; targeting: "none" | "singleEnemy" } {
  const found = cardMeta[cardId];
  if (found) return found;
  // `strike+` 之类：剥掉 `+` 查基础条目（与 i18n 表同样的剥壳规则）。
  const base = cardMeta[cardId.replace(/\++$/, "")];
  if (base) return base;
  // 查不到：退回最保守的假设（不要目标 + 技能色），**不**按文案猜。
  return { kind: "skill", targeting: "none" };
}

export interface WasmNames {
  cardName(slot: number): string;
  cardText(slot: number): string;
  enemyName(slot: number): string;
  /**
   * 战斗者身上的状态实例（`-1` = 英雄，`0..5` = 敌人墙位）。
   *
   * ⚠️ **可选**：`?mock` 那条路（P1 的确定局面）没有 wasm，状态一律为空数组。
   * 写成必需会让 mock 分支编不过，而 mock 分支是 P1 那 94 条断言的夹具。
   */
  statuses?(whom: number): { id: string; stacks: number }[];
}

/**
 * 状态 id → 可读标签。
 *
 * i18n 表里没有的那一条**不显示裸 id**（`standard.spore_cloud` 在界面上是一串机器码）：
 * 剥掉命名空间、下划线换空格 ⇒ `spore cloud`。它仍然是英文（诚实：说明这条没翻译），
 * 但至少读得出来。回退**照常计数**（`coverage()` 不会因此少报）。
 */
function statusLabel(id: string): string {
  const translated = displayName("statuses", id);
  if (translated !== id) return translated;
  return id.replace(/^standard\./, "").replace(/_/g, " ");
}

/** 状态实例 → 展示形状。 */
function viewStatuses(
  names: WasmNames,
  whom: number
): readonly ViewStatus[] {
  const raw = names.statuses?.(whom) ?? [];
  return raw.map((status) => ({
    id: status.id,
    name: statusLabel(status.id),
    stacks: status.stacks,
  }));
}

/**
 * 从**真实内核快照**建视图。
 *
 * `optionsFor` 直接读内核动作表：一张牌有哪些落点、每条动作的 `actionIndex` 是什么，
 * 全部由 `rd_env_action_*` 说了算。UI 不再自己算"能不能打这个敌人"。
 */
export function viewFromWasm(snapshot: CombatSnapshot, names: WasmNames, epoch = 0): CombatView {
  const hand: ViewCard[] = snapshot.hand.map((card) => {
    // 内核给的是**定义 id**（`strike` / `strike+`）；中文由 i18n 表查，内核不需要知道中文。
    const cardId = names.cardName(card.slot);
    const rules = displayText("cards", cardId) || names.cardText(card.slot);
    const actions = snapshot.actions.filter(
      (action) => action.kind === "play" && action.handSlot === card.slot
    );
    const meta = metaOf(cardId);
    return {
      id: `hand-${card.slot}-${card.defSlot}`,
      defId: cardId,
      name: displayName("cards", cardId),
      cost: card.cost,
      kind: meta.kind,
      // ⚠️ "要不要目标"来自**内容元数据**，不是动作表的 `targetSlot`（见 `metaOf`）。
      targeted: meta.targeting === "singleEnemy",
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
      statuses: viewStatuses(names, -1),
    },
    // ⚠️ **死掉的敌人不进视图**（玩家实测：打死了还站在场上，而且下一回合还换一个新意图 ——
    // 虽然点了也不会生效）。内核把 `alive = 0` 的格子留在快照里是对的（位置要稳定、动作表要
    // 稳定），但"要不要画"是展示层的决定：一具站着的尸体比一个空位更让人困惑。
    //
    // 副作用是好的：`layout.enemies` 里没有它 ⇒ 拖牌不会命中它（它本来也不是合法目标）。
    enemies: snapshot.enemies
      .filter((enemy) => enemy.alive)
      .map((enemy) => ({
        slot: enemy.slot,
        id: `enemy-${enemy.slot}`,
        defId: names.enemyName(enemy.slot),
        name: displayName("monsters", names.enemyName(enemy.slot)),
        hp: enemy.hp,
        hpMax: enemy.hpMax,
        block: enemy.block,
        alive: enemy.alive,
        intent: intentText(enemy.intentKind, enemy.intentDamage),
        statuses: viewStatuses(names, enemy.slot),
      })),
    hand,
    turn: snapshot.turn,
    round: snapshot.round,
    result: snapshot.result,
    epoch,
    optionsFor(handSlot: number): DropOption[] {
      const actions = snapshot.actions.filter(
        (action) => action.kind === "play" && action.handSlot === handSlot
      );
      if (actions.length === 0) return [];
      const cardId = names.cardName(handSlot);
      const meta = metaOf(cardId);
      const label = displayName("cards", cardId);
      if (meta.targeting === "none") {
        // 内核会为无目标牌也枚举出"×每个活敌人"的多条动作（过度指定目标对规则无害）。
        // UI 侧把它们**归并成一个代表动作**：业务上"丢哪儿都算数"，`actionIndex` 取第一条
        // 真实动作（**不虚构** `targetSlot = -1` 的内核条目）。
        return [{ slot: -1, actionIndex: actions[0].index, label: `打出 ${label}` }];
      }
      return actions.map((action) => ({
        slot: action.targetSlot,
        actionIndex: action.index,
        label: `${label} → 敌人 ${action.targetSlot}`,
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
      // Mock 局面没有内核状态：空数组（不是"假装有 0 层"）。
      statuses: [],
    },
    enemies: scene.enemies.map((enemy) => ({
      slot: enemy.slot,
      id: enemy.id,
      defId: enemy.id,
      name: enemy.name,
      hp: enemy.hp,
      hpMax: enemy.maxHp,
      block: 0,
      alive: enemy.hp > 0,
      intent: enemy.intent,
      statuses: [],
    })),
    hand: scene.hand.map((card) => ({
      // ⚠️ id 保持原样：P1 的闸门按 `strike` 这样的 id 断言。重复 id 不影响 React key
      // （`Stage` 用的是 `card.id + index`）。
      id: card.id,
      // Mock 的 id 就是内容 id（`strike` / `bash`），所以直接用它。
      defId: card.id,
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
    epoch: 0,
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
