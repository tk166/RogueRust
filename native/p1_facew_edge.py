"""两件收尾：文字框用 `faceW`（牌面宽度）；`CardEdge` 几何体共享。

## 文字框

`visibleW` 是"露出来多少"（紧凑态 = 33px 的条），`faceW` 是"牌面看起来多宽"（旋转时比外接
矩形窄）。两者取小才对：
* 紧凑态：受 `visibleW` 限制（只能写在那条里）；
* 抬起/悬停：整张都露着，受 `faceW` 限制（要写在牌面上，别溢出到牌外）。

## 共享几何体（Review P2-E）

原来每个 `CardEdge` 实例各建一份 `EdgesGeometry`，注释还写着"只创建一次"（其实是"每次挂载
一次"）。改成模块级懒单例：十张牌共用一份，卸载也不释放（与共享材质同一惯例，进程内一份）。
"""

import io

OVERLAY = 'web-next/src/overlay/TextOverlay.tsx'
STAGE = 'web-next/src/stage/Stage.tsx'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    OVERLAY,
    '''        // 文字框用**露出来的那条**宽度，不是整张牌的宽度（见 `CardScreen.visibleW`）。
        node.style.width = `${screen.visibleW}px`;''',
    '''        // 文字框宽度取两者的小值（见 `CardScreen.visibleW` / `faceW`）：
        // 紧凑态受"露出来的那条"限制，抬起/悬停受"牌面看起来多宽"限制。
        node.style.width = `${Math.min(screen.faceW, screen.visibleW)}px`;''',
    'overlay width',
)

edit(
    STAGE,
    '''/**
 * 牌框。`BoxGeometry` 每个实例创建一次（不是每帧）—— **不是**全手牌共享一份：
 * 每张牌都挂一个 `CardEdge` 实例，各自 `useMemo`。十张牌无所谓，正式实现应提到外面共享。
 */
function CardEdge({ order }: { order: number }) {
  const geometry = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(CARD_W, CARD_H, 0.03)), []);
  return (
    <lineSegments geometry={geometry} raycast={() => null} renderOrder={order}>''',
    '''/**
 * 牌框几何体：**全手牌共享一份**（模块级懒单例）。
 *
 * 原来每个 `CardEdge` 实例各建一份 `EdgesGeometry`，注释却写着"只创建一次" —— 那是
 * "每次挂载一次"，十张牌就是十份（Review P2-E）。这里提成单例：进程内一份，不释放
 * （与共享材质的惯例一致；正式实现若要做多局/多 Canvas，应改由上下文注入并在卸载时 dispose）。
 */
let sharedCardEdge: THREE.EdgesGeometry | null = null;
function cardEdgeGeometry(): THREE.EdgesGeometry {
  if (!sharedCardEdge) {
    sharedCardEdge = new THREE.EdgesGeometry(new THREE.BoxGeometry(CARD_W, CARD_H, 0.03));
  }
  return sharedCardEdge;
}

function CardEdge({ order }: { order: number }) {
  return (
    <lineSegments geometry={cardEdgeGeometry()} raycast={() => null} renderOrder={order}>''',
    'CardEdge shared',
)
print('faceW + shared edge geometry')
