"""闸门 29 的两处竞态：
① 视图就绪 ≠ 布局就绪（`layout().cards` 要等 useFrame 跑几帧）；
② `endTurn()` 之后要等 React 重渲染再读 `view()`（探针读的是 React 状态）。

两处都是"读得太早"，而不是功能坏了 —— 但读得太早会变成假红，必须修。
"""

import io

PATH = 'native/ui_wasm_ui_check.mjs'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''const view = await evaluate("window.__p1.view()");
check(view?.hand?.length === 5, "手牌来自内核：5 张", JSON.stringify(view?.hand?.length));''',
    '''const view = await evaluate("window.__p1.view()");
check(view?.hand?.length === 5, "手牌来自内核：5 张", JSON.stringify(view?.hand?.length));

// ⚠️ 视图就绪 ≠ 布局就绪：`layout().cards` 由 `useFrame` 每帧写，要等它跟上手牌数。
let layoutReady = false;
for (let attempt = 0; attempt < 100; attempt += 1) {
  layoutReady = await evaluate(
    `(() => {
      const l = window.__p1.layout();
      return l.frames > 20 && l.cards.length === window.__p1.view().hand.length && l.enemies.length > 0;
    })()`
  );
  if (layoutReady) break;
  await sleep(100);
}
check(layoutReady, "布局跟上手牌与敌人（投影帧数足够）");''',
    'layout wait',
)

sub(
    '''const ended = await evaluate("window.__p1.endTurn()");
check(ended?.accepted === true, "结束回合被内核接受", JSON.stringify(ended));
const clockAfter = await evaluate("window.__p1.view()");''',
    '''const ended = await evaluate("window.__p1.endTurn()");
check(ended?.accepted === true, "结束回合被内核接受", JSON.stringify(ended));
// ⚠️ 探针读的是 **React 状态**：`dispatch` 触发 setState，读太早会拿到旧快照（假红）。
await sleep(200);
const clockAfter = await evaluate("window.__p1.view()");''',
    'endTurn wait',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate 29 races fixed')
