"""把 HUD 高度模型调到与实测一致，并让闸门断言对比**模型**而不是常数。

## 事实

* 纯函数里 `hudBottom = HUD_PAD + hudRows * HUD_ROW_H = 14 + 2*34 = 82`；
* 但 390×844 的截图里 uikit HUD 实际占到约 **86** CSS 像素（一张 780×1688 的 2x 图里
  HP/BLK/EN/TURN 四个盒子在 y≈28..172）；
* 于是提示条按模型放在 88px，会贴着 HUD 底边（差 2px）。

把 `HUD_ROW_H` 调到 36 ⇒ `hudBottom = 86`、提示条 92，留 6px 余量。

## 断言改成对比模型

原来那条写死 `hintTop >= 96`（我当初手工把提示条挪到 100px 时留下的常数）。现在位置由
`regions.hudBottom` 驱动，断言就该拿**同一个**值比 —— 否则又是"两份认识"。
uikit 的 HUD 是 3D 画的，DOM 量不到，所以模型与真机的一致性靠截图人工复核（这条在注释里写明）。
"""

import io

LAYOUT = 'web-next/src/stage/combatLayout.ts'
GATE = 'native/ui_next_check.mjs'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    LAYOUT,
    '''/** HUD 一行的高度（uikit 的 padding + 文字）。窄屏会折成两行。 */
const HUD_ROW_H = 34;''',
    '''/**
 * HUD 一行的高度（uikit 的 padding + 文字）。
 *
 * 36 是**量出来的**：390×844 的截图里 HP/BLK/EN/TURN 四个盒子占到约 86 CSS 像素
 * （14 padding + 2×36）。uikit 的 HUD 是 3D 画的，DOM 量不到 —— 所以这个数只能靠截图校准，
 * 改动 HUD 内边距时要跟着改。
 */
const HUD_ROW_H = 36;''',
    'HUD_ROW_H',
)

edit(
    GATE,
    '''check(
  (portraitLayout.hintTop ?? 0) >= 96,
  "窄屏提示气泡在 HUD 下方（HUD 是 uikit 的 3D 层，DOM 量不到 ⇒ 这条用布局常量）",
  `hintTop=${portraitLayout.hintTop}`
);''',
    '''// ⚠️ 对比的是 `computeCombatLayout().regions.hudBottom`（**同一个**函数算出来的），
// 不是硬编码常数 —— 否则提示条位置与断言又成了"两份认识"。
// uikit 的 HUD 是 3D 画的、DOM 量不到，所以模型与真机的一致性靠截图人工复核。
check(
  portraitLayout.regions !== null && (portraitLayout.hintTop ?? 0) >= portraitLayout.regions.hudBottom,
  "窄屏提示气泡在 HUD 下方（对比 regions.hudBottom）",
  `hintTop=${portraitLayout.hintTop}, hudBottom=${portraitLayout.regions?.hudBottom}`
);''',
    'gate hint vs model',
)

# 顺手把另外两条版面断言也接到模型上（手牌底边 vs 操作栏、敌人 vs 战场区）
edit(
    GATE,
    '''const portraitLayout = await evaluate(`(() => {
  const l = window.__p1.layout();
  const hint = document.querySelector(".gesture-hint");
  const rect = hint ? hint.getBoundingClientRect() : null;
  return {
    width: l.width, height: l.height,
    cards: l.cards.map((c) => ({ slot: c.slot, top: Math.round(c.y - c.h / 2), bottom: Math.round(c.y + c.h / 2) })),
    enemies: l.enemies.map((e) => ({ slot: e.slot, x: Math.round(e.x), y: Math.round(e.y), r: Math.round(e.r) })),
    hintTop: rect ? Math.round(rect.top) : null,
  };
})()`);''',
    '''const portraitLayout = await evaluate(`(() => {
  const l = window.__p1.layout();
  const hint = document.querySelector(".gesture-hint");
  const rect = hint ? hint.getBoundingClientRect() : null;
  return {
    width: l.width, height: l.height,
    regions: l.regions,
    cards: l.cards.map((c) => ({ slot: c.slot, top: Math.round(c.y - c.h / 2), bottom: Math.round(c.y + c.h / 2) })),
    enemies: l.enemies.map((e) => ({ slot: e.slot, x: Math.round(e.x), y: Math.round(e.y), r: Math.round(e.r) })),
    hintTop: rect ? Math.round(rect.top) : null,
  };
})()`);''',
    'gate portrait regions',
)

edit(
    GATE,
    '''check(tooClose === null, "竖屏相邻敌人间距放得下三行标签", JSON.stringify(tooClose));''',
    '''check(tooClose === null, "竖屏相邻敌人间距放得下三行标签", JSON.stringify(tooClose));

// 敌人必须整个落在**战场区**里（`regions.combatTop..combatBottom`）—— 这是区域模型
// 真正被用上的地方：队形若把敌人推进 HUD 或手牌区，这条会红。
const combatStrays = portraitLayout.regions
  ? portraitLayout.enemies.filter((enemy) => {
      const top = enemy.y - enemy.r;
      const bottom = enemy.y + enemy.r;
      return top < portraitLayout.regions.combatTop || bottom > portraitLayout.regions.combatBottom;
    })
  : [];
check(
  portraitLayout.regions !== null && combatStrays.length === 0,
  "竖屏敌人整个落在战场区内（regions.combatTop..combatBottom）",
  JSON.stringify({ strays: combatStrays, regions: portraitLayout.regions })
);
// 手牌底边不许越过操作栏
const handOverrun = portraitLayout.regions
  ? portraitLayout.cards.filter((card) => card.bottom > portraitLayout.regions.actionsTop)
  : [];
check(
  portraitLayout.regions !== null && handOverrun.length === 0,
  "竖屏手牌底边不越过操作栏（regions.actionsTop）",
  JSON.stringify({ overrun: handOverrun, actionsTop: portraitLayout.regions?.actionsTop })
);''',
    'gate regions asserts',
)
print('HUD model + gate asserts vs model')
