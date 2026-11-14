"""§378：把状态实例接进视图层（`combatView.ts`）—— 英雄与敌人各一份。

形状：`statuses: readonly ViewStatus[]`，`ViewStatus = { id, name, stacks }`。
`name` 走 i18n（`statuses` 表），查不到就退回 id（与其它表同一条回退链）。
"""

import io

PATH = 'web-next/src/view/combatView.ts'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 类型 ────────────────────────────────────────────────────────────────
OLD = '''export interface ViewEnemy {'''
NEW = '''/**
 * 一个状态实例（§378）。`id` 是内容定义 id（`standard.strength` / `standard.constricted`），
 * `stacks` 是层数（可能为 1）。
 */
export interface ViewStatus {
  readonly id: string;
  /** 中文名（`statuses` 表；查不到退回 `id`）。 */
  readonly name: string;
  readonly stacks: number;
}

export interface ViewEnemy {'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''  /** 一行意图文本（"攻击 9" / "未知"）。wasm 给 kind+damage，这里只做展示。 */
  readonly intent: string;
}'''
NEW = '''  /** 一行意图文本（"攻击 9" / "未知"）。wasm 给 kind+damage，这里只做展示。 */
  readonly intent: string;
  /** 身上的状态（力量/易伤/虚弱/…，含观察向量里没有的那些，如 `constricted`）。 */
  readonly statuses: readonly ViewStatus[];
}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''export interface ViewHero {
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly energy: number;
  readonly maxEnergy: number;
}'''
NEW = '''export interface ViewHero {
  readonly name: string;
  readonly hp: number;
  readonly hpMax: number;
  readonly block: number;
  readonly energy: number;
  readonly maxEnergy: number;
  readonly statuses: readonly ViewStatus[];
}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 2. `WasmNames` 加 statuses ─────────────────────────────────────────────
OLD = '''export interface WasmNames {
  cardName(slot: number): string;
  cardText(slot: number): string;
  enemyName(slot: number): string;
}'''
NEW = '''export interface WasmNames {
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

/** 状态实例 → 展示形状（中文名走 i18n，查不到退回 id）。 */
function viewStatuses(
  names: WasmNames,
  whom: number
): readonly ViewStatus[] {
  const raw = names.statuses?.(whom) ?? [];
  return raw.map((status) => ({
    id: status.id,
    name: displayName("statuses", status.id),
    stacks: status.stacks,
  }));
}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 3. 两个生产者 ──────────────────────────────────────────────────────────
OLD = '''    hero: {
      name: "铁甲战士",
      hp: snapshot.hero.hp,
      hpMax: snapshot.hero.hpMax,
      block: snapshot.hero.block,
      energy: snapshot.hero.energy,
      maxEnergy: snapshot.hero.energyMax,
    },'''
NEW = '''    hero: {
      name: "铁甲战士",
      hp: snapshot.hero.hp,
      hpMax: snapshot.hero.hpMax,
      block: snapshot.hero.block,
      energy: snapshot.hero.energy,
      maxEnergy: snapshot.hero.energyMax,
      statuses: viewStatuses(names, -1),
    },'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''        block: enemy.block,
        alive: enemy.alive,
        intent: intentText(enemy.intentKind, enemy.intentDamage),
      })),'''
NEW = '''        block: enemy.block,
        alive: enemy.alive,
        intent: intentText(enemy.intentKind, enemy.intentDamage),
        statuses: viewStatuses(names, enemy.slot),
      })),'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''      block: scene.hero.block,
      energy: scene.hero.energy,
      maxEnergy: scene.hero.maxEnergy,
    },'''
NEW = '''      block: scene.hero.block,
      energy: scene.hero.energy,
      maxEnergy: scene.hero.maxEnergy,
      // Mock 局面没有内核状态：空数组（不是"假装有 0 层"）。
      statuses: [],
    },'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''      block: 0,
      alive: enemy.hp > 0,
      intent: enemy.intent,
    })),'''
NEW = '''      block: 0,
      alive: enemy.hp > 0,
      intent: enemy.intent,
      statuses: [],
    })),'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('combatView: 状态实例接进来了')
