"""修"半可用状态"：wasm 没装载好时**不许**静默回退到 Mock 局面。

## 症状

闸门 29 一开始就绿了前几条：`mode()` 说 `wasm`，但视图里是 10 张 `打击/防御`、英雄 72 血
—— 那是 **Mock 局面**。因为

```ts
const view = MOCK_MODE || !wasmView ? viewFromMock(scene) : wasmView;
```

`wasmView` 还没准备好时静默用了 Mock。plan P2 的退出条件写着"失配时显示诊断，**不进入半可用
状态**" —— 这就是半可用：玩家看到一副能拖能打的牌，而它跟内核毫无关系。

## 修法

* 默认路径下 `view` = `wasmView ?? EMPTY_VIEW`（空局面，`mode: "wasm"`），**不回退**；
* 空局面时在画布上盖一条状态条：装载中 / 装载失败的原因（`WasmMismatch` 的诊断清单）。
"""

import io

PATH = 'web-next/src/App.tsx'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const MOCK_MODE = new URLSearchParams(window.location.search).has("mock");''',
    '''/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const MOCK_MODE = new URLSearchParams(window.location.search).has("mock");

/**
 * 装载期间的**空局面**。
 *
 * ⚠️ 为什么不回退到 Mock：plan P2 要求"失配时显示诊断，不进入半可用状态"。第一版在
 * `wasmView === null` 时静默用 Mock，于是闸门 29 看到的是 10 张演示牌 + 72 血 —— 一副能拖能打
 * 却与内核毫无关系的牌。宁可空屏 + 状态条。
 */
const EMPTY_VIEW: CombatView = {
  mode: "wasm",
  hero: { name: "铁甲战士", hp: 0, hpMax: 0, block: 0, energy: 0, maxEnergy: 0 },
  enemies: [],
  hand: [],
  turn: 0,
  round: 0,
  result: "ongoing",
  optionsFor: () => [],
  endTurnOption: () => null,
};''',
    'empty view',
)

sub(
    '''  const view: CombatView = useMemo(
    () => (MOCK_MODE || !wasmView ? viewFromMock(scene) : wasmView),
    [scene, wasmView]
  );''',
    '''  const view: CombatView = useMemo(
    () => (MOCK_MODE ? viewFromMock(scene) : (wasmView ?? EMPTY_VIEW)),
    [scene, wasmView]
  );''',
    'no mock fallback',
)

sub(
    '''      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    '''      {/* 装载中 / 装载失败：显示诊断，**不进半可用**。 */}
      {!MOCK_MODE && !wasmView && (
        <div className="wasm-status" data-wasm-status>
          {wasmError ? `内核装载失败：${wasmError}` : "正在装载内核…"}
        </div>
      )}

      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    'status bar',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('no mock fallback')
