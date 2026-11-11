"""把扇形的叠放顺序改成 StS 的"越靠右越靠前"，并让布局暴露**命中点**。

## 为什么

第一版扇形 `z = 0.9 + |t| * 0.12` 是**对称**的：两端的牌在最前，中间那张 z 最小 ⇒
390px 宽、10 张牌互相压住时，**中间那张被左右邻牌完全盖住**，既看不见也点不到
（闸门 25 实测：按第 5 张牌的位置命中了第 6 张）。

StS 的做法是叠放顺序**单调**：右边那张永远压着左边那张。这样每张牌都露出左边一条，
"看得见的"与"点得到的"是同一个区域。

同时布局里加 `hitX/hitY`：**闸门不应该自己猜"该按牌中心还是按露出条"** —— 那是布局的
知识，应该由布局自己说出来（否则又是"同一个词表两处认识"，§4.20）。
"""

import io

STAGE = 'web-next/src/stage/Stage.tsx'
LAYOUT = 'web-next/src/stage/layout.ts'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    LAYOUT,
    '''  visibleW: number;''',
    '''  visibleW: number;
  /**
   * **命中点**：按下去能选中这张牌的那个像素（不是牌心）。
   *
   * 叠放顺序单调（右压左）时，每张牌只露出左边一条；牌心可能被右边的牌盖住。
   * 这个点由布局算（它知道露出多少），**闸门不该自己猜**。
   */
  hitX: number;
  hitY: number;''',
    'layout hitX',
)

edit(
    STAGE,
    '''  return {
    x: t * spread,
    // 弧线：两端略高，中间略低（像手里握着的一把牌）。
    y: -1.62 + Math.abs(t) * 0.26,
    z: 0.9 + Math.abs(t) * 0.12,
    angle: -t * 0.26,
    t,
  };''',
    '''  return {
    x: t * spread,
    // 弧线：两端略高，中间略低（像手里握着的一把牌）。
    y: -1.62 + Math.abs(t) * 0.26,
    // ⚠️ z **只随序号单调递增**（越靠右越靠前），**不要**写成 `0.9 + |t| * 0.12`：
    // 那样是对称的，两端在最前、中间 z 最小，窄屏互相压住时中间那张会被完全盖住，
    // 于是"看不见的牌也点不到"（闸门 25 抓到的就是这一条）。
    z: 0.9 + index * 0.008,
    angle: -t * 0.26,
    t,
  };''',
    'fanTransform z monotonic',
)

edit(
    STAGE,
    '''    // 露出来的宽度 = min(牌宽, 与右边邻牌中心的间距)。最右那张没有右邻，用与左邻的间距。
    for (let index = 0; index < cards.length; index += 1) {
      const card = cards[index];
      const neighbour = cards[index + 1] ?? cards[index - 1];
      const stride = neighbour ? Math.abs(neighbour.x - card.x) : card.w;
      card.visibleW = Math.min(card.w, Math.max(stride, 1));
    }''',
    '''    // 露出来的宽度 = min(牌宽, 与右邻中心的间距)；最右那张没有右邻 ⇒ 整张都露着。
    // 命中点往**左**挪半个被压住的量：露出的是左边那条。
    for (let index = 0; index < cards.length; index += 1) {
      const card = cards[index];
      const neighbour = cards[index + 1];
      const stride = neighbour ? Math.abs(neighbour.x - card.x) : card.w;
      card.visibleW = Math.min(card.w, Math.max(stride, 1));
      card.hitX = card.x - (card.w - card.visibleW) / 2;
      card.hitY = card.y;
    }''',
    'visibleW + hitX',
)

edit(
    STAGE,
    '''          <mesh
            key={`hit-${card.id}-${index}`}
            position={[local.x, local.y, local.z + 0.02]}
            rotation={[0, 0, local.angle]}
            onPointerDown={(event) => {''',
    '''          <mesh
            key={`hit-${card.id}-${index}`}
            // 命中面放在所有**静止**视觉之前（`local.z` 最大约 0.98），并同样按序号单调叠放。
            position={[local.x, local.y, 1.2 + index * 0.008]}
            rotation={[0, 0, local.angle]}
            onPointerDown={(event) => {''',
    'hit quad z',
)

# 闸门：按命中点，不按牌心
edit(
    'native/ui_next_check.mjs',
    '''async function cardPoint(slot) {
  return evaluate(`(() => {
    const card = window.__p1.layout().cards.find((c) => c.slot === ${slot});
    return card ? { x: card.x, y: card.y } : null;
  })()`);
}''',
    '''/**
 * 一张牌的**命中点**（`hitX/hitY`，不是牌心）。
 *
 * 叠放顺序单调时牌心可能被右邻盖住 —— 按牌心会命中隔壁那张（第一版就这么错了，
 * 而且因为只看"提交数变没变"而**假绿**过一轮）。命中点由布局给出。
 */
async function cardPoint(slot) {
  return evaluate(`(() => {
    const card = window.__p1.layout().cards.find((c) => c.slot === ${slot});
    return card ? { x: card.hitX, y: card.hitY } : null;
  })()`);
}''',
    'gate hitX',
)
print('monotonic stacking + hitX')
