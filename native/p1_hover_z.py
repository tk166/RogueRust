"""hover 抬牌不要改 z：z 在透视下会放大并下移，而手牌的绘制顺序根本不看 z。

## 症状

合并参考包后闸门 25 的版面断言红了：1280×800 中间那张牌底边 817（超过视口 17px）。
原因是 hover 时 `targetZ = 1.32`（把牌推到扇形前面），但：

* 手牌材质是 `depthTest={false}` + 固定 `renderOrder` ⇒ **绘制顺序与 z 无关**；
* 透视下 z 变大 ⇒ 投影更大、位置更低 ⇒ "轻抬"变成"放大并往下掉"。

## 修法

1. hover **不改 z**（只抬 `y` + 轻微放大）；
2. 叠放顺序改用 **per-card `renderOrder`**：静止 10+i、hover 25、抬起 30
   （这本来就是"谁盖谁"的正确表达，而不是借用三维深度）；
3. DOM 文字层的 `zIndex` 同步（hover 也要压在上面），否则牌上去了文字还在下面。
"""

import io

STAGE = 'web-next/src/stage/Stage.tsx'
OVERLAY = 'web-next/src/overlay/TextOverlay.tsx'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    STAGE,
    '''      const targetZ = lifted ? LIFT_Z : hovered ? 1.32 : local.z;''',
    '''      // ⚠️ hover **不改 z**：手牌 `depthTest=false` + 固定 renderOrder ⇒ 绘制顺序与 z 无关，
      // 而透视下 z 变大只会让牌更大更低（"轻抬"变成"放大并往下掉"，底边直接掉出视口）。
      // 叠放顺序交给下面的 per-card renderOrder。
      const targetZ = lifted ? LIFT_Z : local.z;''',
    'hover z',
)

edit(
    STAGE,
    '''      {/* 手牌：牌身 + 边框。**文字不在这里**（见 `TextOverlay`）。 */}
      {scene.hand.map((card, index) => (
        <group
          key={`${card.id}-${index}`}
          ref={(node) => {
            cardRefs.current[index] = node;
          }}
          position={[0, -8, 0]}
        >''',
    '''      {/* 手牌：牌身 + 边框。**文字不在这里**（见 `TextOverlay`）。 */}
      {scene.hand.map((card, index) => (
        <group
          key={`${card.id}-${index}`}
          ref={(node) => {
            cardRefs.current[index] = node;
          }}
          position={[0, -8, 0]}
        >''',
    'card map head',
)

# 牌身与边框的 renderOrder 改成按状态：静止 10+i、hover 25、抬起 30
edit(
    STAGE,
    '''          <mesh raycast={() => null} renderOrder={10}>''',
    '''          <mesh
            raycast={() => null}
            renderOrder={index === liftedSlot ? 30 : index === hoverCardSlot ? 25 : 10 + index}
          >''',
    'card renderOrder',
)

edit(
    STAGE,
    '''          <CardEdge />''',
    '''          <CardEdge
            order={index === liftedSlot ? 31 : index === hoverCardSlot ? 26 : 11 + index}
          />''',
    'edge renderOrder',
)

edit(
    STAGE,
    '''/** 牌框：单独一个组件，这样 `BoxGeometry` 只创建一次（内联在 map 里会每帧 new）。 */
function CardEdge() {
  const geometry = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(CARD_W, CARD_H, 0.03)), []);
  return (
    <lineSegments geometry={geometry} raycast={() => null} renderOrder={11}>''',
    '''/**
 * 牌框。`BoxGeometry` 每个实例创建一次（不是每帧）—— **不是**全手牌共享一份：
 * 每张牌都挂一个 `CardEdge` 实例，各自 `useMemo`。十张牌无所谓，正式实现应提到外面共享。
 */
function CardEdge({ order }: { order: number }) {
  const geometry = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(CARD_W, CARD_H, 0.03)), []);
  return (
    <lineSegments geometry={geometry} raycast={() => null} renderOrder={order}>''',
    'CardEdge comment',
)

# DOM 文字层：hover 也要压在上面
edit(
    OVERLAY,
    '''        node.style.zIndex = String(screen.lifted ? 20 : 10 + slot);''',
    '''        // 与 3D 侧的 per-card renderOrder 对齐：抬起 > hover > 静止（否则牌上去了文字还在下面）。
        node.style.zIndex = String(screen.lifted ? 30 : slot === hoverCardSlot ? 25 : 10 + slot);''',
    'overlay zIndex',
)
print('hover z removed, renderOrder per card')
