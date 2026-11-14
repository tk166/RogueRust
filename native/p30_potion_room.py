"""§380 接线：商店药水货架在腰带满时不可点（`potionSlots` 一路传到 `ShopScene`）。

链路：`host.potionSlots()` → `RunStore.state.potionSlots` → `RunApp` 传给 `ShopScene`
→ `shelfRows(..., potionRoom)` 决定 `buyable`。

⚠️ 判据放在**模型**（`models.ts` 的 `shelfRows`）而不是组件里：闸门 27 直接编它、不需要浏览器。
"""

import io

# ── 1. 状态里加 potionSlots ────────────────────────────────────────────────
PATH = 'web-next/src/run/RunStore.ts'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''  readonly potions: readonly { slot: number; id: string; effect: number; needsFight: number }[];'''
NEW = '''  readonly potions: readonly { slot: number; id: string; effect: number; needsFight: number }[];
  /**
   * 药水腰带**容量**（`rd_run_potion_slots`，§380）。规则在内核：3 格 / A11 减 1 / `potion_belt` 加 2。
   *
   * ⚠️ 界面**不许**自己算这个数：容量是规则，不是展示偏好。商店的药水货架拿它判断
   * "腰带满了 ⇒ 不可买"（旧版没问，于是点了被内核拒绝 —— `web-soak` 的 dead control）。
   */
  readonly potionSlots: number;'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD = '''      potions: raw.exists
        ? Array.from({ length: this.host.potionCount() }, (_, slot) => ({
            slot,
            id: this.host.potionId(slot),
            effect: this.host.potionEffect(slot),
            needsFight: this.host.potionNeedsFight(slot),
          }))
        : [],'''
NEW = '''      potions: raw.exists
        ? Array.from({ length: this.host.potionCount() }, (_, slot) => ({
            slot,
            id: this.host.potionId(slot),
            effect: this.host.potionEffect(slot),
            needsFight: this.host.potionNeedsFight(slot),
          }))
        : [],
      potionSlots: raw.exists ? this.host.potionSlots() : 0,'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('RunStore: potionSlots')

# ── 2. 初始 state 也要有它（`initialState`）────────────────────────────────
OLD2 = '''      potions: [],
'''
assert t.count(OLD2) >= 1
idx = t.index(OLD2)
t = t[:idx] + '''      potions: [],
      potionSlots: 0,
''' + t[idx + len(OLD2):]
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('RunStore: initialState.potionSlots')

# ── 3. shelfRows 收一个"还有没有位置" ──────────────────────────────────────
PATH = 'web-next/src/run/models.ts'
t = io.open(PATH, encoding='utf-8').read()
OLD = '''export function shelfRows(
  entries: readonly { slot: number; id: string; price: number }[],
  gold: number
): ShelfRow[] {
  return entries.map((entry) => ({
    slot: entry.slot,
    id: entry.id,
    price: entry.price,
    forSale: entry.price >= 0,
    affordable: entry.price >= 0 && entry.price <= gold,
  }));
}'''
NEW = '''export function shelfRows(
  entries: readonly { slot: number; id: string; price: number }[],
  gold: number,
  /**
   * 还有没有地方放（§380：只有药水那一排需要 —— 腰带满了就装不下）。
   * `undefined` = 这一排没有容量限制（卡/遗物）。
   */
  room = true
): ShelfRow[] {
  return entries.map((entry) => ({
    slot: entry.slot,
    id: entry.id,
    price: entry.price,
    forSale: entry.price >= 0,
    affordable: entry.price >= 0 && entry.price <= gold,
    // "买得起"与"放得下"是两件事：腰带 3/3 时金币再多也买不了。
    room,
  }));
}

/** 腰带还能不能再装一瓶（`§380`）。`slots <= 0` = 没有局 ⇒ 当作不能。 */
export function beltHasRoom(held: number, slots: number): boolean {
  return slots > 0 && held < slots;
}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('models: shelfRows(room) + beltHasRoom')
