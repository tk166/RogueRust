"""UX-6 手牌数量夹具 + UX-3 闭环（区域模型同时驱动 CSS 提示条）。

## UX-6：`?debug&hand=N`（1..12）

手牌数量会改变扇形宽度与紧凑态判定。原来只有 10 张这一种局面，等于没测过边界
（1 张时 `t` 恒为 0；12 张时 stride 会掉到"只剩费用"）。

## UX-3 闭环：提示条的位置也由 `computeCombatLayout` 决定

之前 CSS 里写死 `top: 14px`（宽屏）/`100px`（窄屏），与 JS 里的 HUD 高度是**两份认识**。
现在 `TextOverlay` 的 rAF 把 `regions.hudBottom + 6` 写进 `--hint-top`，CSS 只消费变量。
这样"气泡压 HUD"这件事在结构上不可能再发生，闸门也能拿**同一个**函数去断言。

同时把 `regions` 发布到 `layout`（闸门读它，不读硬编码常数）。
"""

import io

LAYOUT = 'web-next/src/stage/layout.ts'
STAGE = 'web-next/src/stage/Stage.tsx'
PROBE = 'web-next/src/probe.ts'
APP = 'web-next/src/App.tsx'
OVERLAY = 'web-next/src/overlay/TextOverlay.tsx'
CSS = 'web-next/src/styles.css'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① layout 发布 regions ──────────────────────────────────────────────────
edit(
    LAYOUT,
    '''export interface ScreenLayout {
  cards: CardScreen[];
  enemies: EnemyScreen[];
  width: number;
  height: number;''',
    '''export interface ScreenLayout {
  cards: CardScreen[];
  enemies: EnemyScreen[];
  /**
   * 版面区域（CSS 像素）：HUD / 战场 / 手牌 / 操作栏。
   * 由 `computeCombatLayout` 算出，**闸门用它断言**，不读硬编码常数。
   */
  regions: import("./combatLayout").CombatRegions | null;
  width: number;
  height: number;''',
    'layout regions type',
)

edit(
    LAYOUT,
    '''export const layout: ScreenLayout = { cards: [], enemies: [], width: 0, height: 0, frames: 0 };''',
    '''export const layout: ScreenLayout = {
  cards: [],
  enemies: [],
  regions: null,
  width: 0,
  height: 0,
  frames: 0,
};''',
    'layout regions init',
)

edit(
    STAGE,
    '''    layout.width = size.width;
    layout.height = size.height;''',
    '''    layout.regions = view.regions;
    layout.width = size.width;
    layout.height = size.height;''',
    'stage publish regions',
)

# ── ② 探针透出 regions ─────────────────────────────────────────────────────
edit(
    PROBE,
    '''    layout: () => ({
      cards: options.layout.cards.map((card) => ({ ...card })),
      enemies: options.layout.enemies.map((enemy) => ({ ...enemy })),
      width: options.layout.width,
      height: options.layout.height,
      frames: options.layout.frames,
    }),''',
    '''    layout: () => ({
      cards: options.layout.cards.map((card) => ({ ...card })),
      enemies: options.layout.enemies.map((enemy) => ({ ...enemy })),
      regions: options.layout.regions ? { ...options.layout.regions } : null,
      width: options.layout.width,
      height: options.layout.height,
      frames: options.layout.frames,
    }),''',
    'probe regions',
)

# ── ③ `?debug&hand=N` ─────────────────────────────────────────────────────
edit(
    APP,
    '''    return {
      ...base,
      enemies: Array.from({ length: count }, (_, i) => ({
        ...base.enemies[i % base.enemies.length], slot: i,
        id: `debug_enemy_${i}`, name: `演示敌人 ${i + 1}`,
        hp: 25 + i * 4, maxHp: 25 + i * 4, intent: `攻击 ${6 + i}`,
      })),
    };
  });''',
    '''    return {
      ...base,
      enemies: Array.from({ length: count }, (_, i) => ({
        ...base.enemies[i % base.enemies.length], slot: i,
        id: `debug_enemy_${i}`, name: `演示敌人 ${i + 1}`,
        hp: 25 + i * 4, maxHp: 25 + i * 4, intent: `攻击 ${6 + i}`,
      })),
    };
  });''',
    'noop anchor check',
)

# 手牌数量：与敌人同一段初始化里做（读同一个 query）
edit(
    APP,
    '''  const [scene, setScene] = useState<MockScene>(() => {
    const base = initialScene();''',
    '''  const [scene, setScene] = useState<MockScene>(() => {
    let base = initialScene();''',
    'app base let',
)

edit(
    APP,
    '''    const count = Number(raw);
    if (!Number.isInteger(count) || count < 1 || count > 6) return base;''',
    '''    // [P1-LAYOUT] ?debug&hand=N：手牌数量会改变扇形宽度与紧凑态判定，1..12 都要能看。
    const handRaw = query.get("hand");
    if (handRaw !== null) {
      const handCount = Number(handRaw);
      if (Number.isInteger(handCount) && handCount >= 1 && handCount <= 12) {
        base = {
          ...base,
          hand: Array.from({ length: handCount }, (_, i) => base.hand[i % base.hand.length]),
        };
      }
    }
    const count = Number(raw);
    if (!Number.isInteger(count) || count < 1 || count > 6) return base;''',
    'app hand count',
)

# ── ④ 提示条位置由 layout 驱动 ─────────────────────────────────────────────
edit(
    OVERLAY,
    '''      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-enemy]"))) {''',
    '''      // 提示条的位置也来自同一个纯函数（`regions.hudBottom`）：CSS 只消费变量，
      // 于是"气泡压 HUD"在结构上不可能再发生（两份认识 → 一份）。
      if (layout.regions) {
        document.documentElement.style.setProperty(
          "--hint-top",
          `${Math.round(layout.regions.hudBottom + 6)}px`
        );
      }
      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-enemy]"))) {''',
    'overlay hint var',
)

edit(
    CSS,
    '''.gesture-hint {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 14px);''',
    '''.gesture-hint {
  position: absolute;
  /* 位置由 `computeCombatLayout().regions.hudBottom` 通过 `--hint-top` 驱动（见 TextOverlay）。
     兜底值只在第一帧之前生效。 */
  top: var(--hint-top, 14px);''',
    'css hint top',
)

edit(
    CSS,
    '''  .gesture-hint { font-size: 11px; padding: 5px 10px; top: calc(env(safe-area-inset-top, 0px) + 100px); }''',
    '''  .gesture-hint { font-size: 11px; padding: 5px 10px; }''',
    'css narrow hint',
)
print('UX-6 + UX-3 loop')
