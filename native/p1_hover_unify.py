"""UX-2（文字锚点）+ hover 双源统一。

## UX-2：紧凑态文字应落在**露出来的那条**上

`TextOverlay` 把文字框放在 `screen.x`（牌心）。但叠放顺序是"右压左"，牌心可能被右边的牌
盖住 —— 露出的是左边一条，其中心是 `hitX`。当前 33px 宽度下费用数字恰好还没被吃掉，**是运气**。

修法：紧凑态用 `hitX` 锚点，展开/抬起态（整张都露着）才用牌心。

## hover 双源：同一个事实不能有两个来源

原来"哪个敌人被指向"有两处：
* `Stage` 敌人的 `onPointerMove` → `onHover` → `setHoveredEnemySlot`（**R3F 射线**）；
* `App` 的 `window.pointermove` → `enemyAtScreen`（**屏幕命中**，带 `r+14` 触摸半径）。

两者几何不同（真 mesh vs 半径 +14px），于是敌人边缘会出现"绿环亮着但没有 hover 高亮"。
而且 R3F 的 hover 只在指针真的压在 mesh 上时才有事件，手指略偏就没有。

修法：**hover 也走屏幕命中**。`window.pointermove` 常驻（不再只在按住时跑），一次算出
* 指针下是谁（`hoveredEnemySlot` / `hoverCardSlot`，视觉用，任意敌人）；
* 指针下是不是**合法目标**（`state.hoverSlot`，提交与绿环用，只认合法集合）。

这两个是**两个不同的问题**，但都由**同一个函数** `enemyAtScreen` 回答 —— 不是两份几何。

顺带把 `Stage` 的敌人 `onPointerUp` / 背景板也去掉：抬起的落点已经由 `window.pointerup`
统一算（那条路径原本就在，只是 R3F 抢先在它之前处理了 tap）。R3F 现在只负责一件事：
**卡片上的按下**（需要 `pointerId` / `pointerType` / `button`）。
"""

import io

APP = 'web-next/src/App.tsx'
STAGE = 'web-next/src/stage/Stage.tsx'
OVERLAY = 'web-next/src/overlay/TextOverlay.tsx'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① TextOverlay：紧凑态锚在 hitX ─────────────────────────────────────────
edit(
    OVERLAY,
    '''        node.style.transform = `translate3d(${screen.x}px, ${screen.y}px, 0) translate(-50%, -50%)`;
        // 文字框用**露出来的那条**宽度，不是整张牌的宽度（见 `CardScreen.visibleW`）。
        node.style.width = `${screen.visibleW}px`;
        node.style.height = `${screen.h}px`;
        node.style.zIndex = String(screen.lifted ? 20 : 10 + slot);
        // 窄到放不下标题 ⇒ 只留费用（闸门读这个 class 来断言"要么读得到、要么明确收起"）。
        node.classList.toggle("is-compact", screen.visibleW < COMPACT_BELOW_PX && !screen.lifted);''',
    '''        const compact = screen.visibleW < COMPACT_BELOW_PX && !screen.lifted;
        // ⚠️ 锚点：紧凑态用 `hitX`（**露出来那条**的中心），不是牌心。
        // 叠放顺序是右压左，牌心可能被右邻盖住 —— 文字放牌心等于把费用数字塞到邻居底下。
        // 展开/抬起时整张牌都露着（`visibleW === w`，此时 hitX === x），用哪个都一样。
        const anchorX = compact ? screen.hitX : screen.x;
        node.style.transform = `translate3d(${anchorX}px, ${screen.y}px, 0) translate(-50%, -50%)`;
        // 文字框用**露出来的那条**宽度，不是整张牌的宽度（见 `CardScreen.visibleW`）。
        node.style.width = `${screen.visibleW}px`;
        node.style.height = `${screen.h}px`;
        node.style.zIndex = String(screen.lifted ? 20 : 10 + slot);
        // 窄到放不下标题 ⇒ 只留费用（闸门读这个 class 来断言"要么读得到、要么明确收起"）。
        node.classList.toggle("is-compact", compact);''',
    'overlay anchor',
)

# ── ② Stage：拆掉 hover / release 的 R3F 处理器 ────────────────────────────
edit(
    STAGE,
    '''  onCardHover: (slot: number) => void;
  onHover: (slot: number) => void;
  onRelease: (slot: number) => void;
}''',
    '''}''',
    'stage props',
)

edit(
    STAGE,
    '''  legalTargets, onCardDown, onCardHover, onHover, onRelease,''',
    '''  legalTargets, onCardDown,''',
    'stage signature',
)

edit(
    STAGE,
    '''            onPointerMove={(event) => {
              event.stopPropagation();
              onHover(enemy.slot);
            }}
            onPointerOut={() => onHover(-1)}
            onPointerUp={(event) => {
              event.stopPropagation();
              onRelease(enemy.slot);
            }}
''',
    '''            {/* ⚠️ 敌人身上**不再挂** onPointerMove / onPointerUp：hover 与落点都由
                `App` 的 window 监听经 `hitTest`（屏幕命中）统一算。
                这里再挂一份就是"同一个事实两个来源"—— 两者几何不同（真 mesh vs 半径+14px），
                边缘会出现"绿环亮着但没有 hover 高亮"。 */}
''',
    'enemy handlers',
)

edit(
    STAGE,
    '''      {/* 空白处兜底：指针不在敌人身上时命中它 ⇒ hoverSlot = -1 */}
      <mesh
        position={[0, 0, -3]}
        onPointerMove={(event) => {
          event.stopPropagation();
          onHover(-1);
        }}
        onPointerUp={(event) => {
          event.stopPropagation();
          onRelease(-1);
        }}
      >
        <planeGeometry args={[60, 60]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

''',
    '',
    'backdrop',
)

edit(
    STAGE,
    '''          onPointerOver={(event) => {
            if (event.pointerType === "mouse" || event.pointerType === "pen") onCardHover(index);
          }}
          onPointerOut={() => onCardHover(-1)}
          onPointerDown={(event) => {''',
    '''          onPointerDown={(event) => {''',
    'card hover handlers',
)

# ── ③ App：window.pointermove 常驻，一次算出 hover 与合法目标 ───────────────
edit(
    APP,
    '''    const currentTarget = (x: number, y: number) => {
      // [P1-UX] 命中范围由 Stage 的屏幕投影提供；不要复制三维队形公式。
      const legal = new Set(store.peek().options.filter((o) => o.slot >= 0).map((o) => o.slot));
      return enemyAtScreen(layout.enemies, x, y, legal);
    };
    const onMove = (event: PointerEvent) => {
      const p = activePointer.current;
      if (!p || p.id !== event.pointerId || modalOpen) return;
      const distance = Math.hypot(event.clientX - p.startX, event.clientY - p.startY);
      if (distance >= 8 && p.longPressTimer !== null) {
        window.clearTimeout(p.longPressTimer);
        p.longPressTimer = null;
      }
      const target = currentTarget(event.clientX, event.clientY);
      hoverRef.current = target;
      store.send({ type: "move", hoverSlot: target, distance });
    };''',
    '''    // [P1-UX] 命中范围由 Stage 的屏幕投影提供；不要复制三维队形公式。
    const legalSlots = () =>
      new Set(store.peek().options.filter((o) => o.slot >= 0).map((o) => o.slot));
    const allEnemySlots = () => new Set(layout.enemies.map((e) => e.slot));
    /** 指针下的敌人（**任意**敌人，视觉用）。 */
    const underPointer = (x, y) => enemyAtScreen(layout.enemies, x, y, allEnemySlots());
    /** 指针下是否是**合法目标**（提交与绿环用）。 */
    const currentTarget = (x, y) => enemyAtScreen(layout.enemies, x, y, legalSlots());

    const onMove = (event: PointerEvent) => {
      if (modalOpen) return;
      // ⚠️ 常驻（不再只在按住时跑）：hover 高亮也走**同一个**屏幕命中函数。
      // 以前 hover 来自 R3F 的射线、提交来自 hitTest，两者几何不同 ⇒ 边缘自相矛盾。
      setHoveredEnemySlot(underPointer(event.clientX, event.clientY));
      setHoverCardSlot(cardAtScreen(layout.cards, event.clientX, event.clientY));

      const p = activePointer.current;
      if (p && p.id !== event.pointerId) return; // 第二根手指不改变第一根的目标
      const distance = p
        ? Math.hypot(event.clientX - p.startX, event.clientY - p.startY)
        : 999; // 没有按住时"位移"无意义；只有 target 生效（点选后再点敌人）
      if (p && distance >= 8 && p.longPressTimer !== null) {
        window.clearTimeout(p.longPressTimer);
        p.longPressTimer = null;
      }
      if (store.peek().phase === "idle") return;
      const target = currentTarget(event.clientX, event.clientY);
      hoverRef.current = target;
      store.send({ type: "move", hoverSlot: target, distance });
    };''',
    'app onMove',
)

# 删掉 onHover / onRelease（已无消费者）
t = io.open(APP, encoding='utf-8').read()
start = t.index('  const onHover = useCallback(')
end = t.index('  // 点按语义：抬起在空白处')
removed = t[start:end]
assert 'onRelease' in removed and len(removed) < 1600, 'onHover/onRelease 区块形状不符（%d 字符）' % len(removed)
t = t[:start] + t[end:]
io.open(APP, 'w', encoding='utf-8', newline='\n').write(t)

edit(
    APP,
    '''          onCardHover={setHoverCardSlot}
          onHover={onHover}
          onRelease={onRelease}''',
    '''''',
    'app stage props',
)
print('UX-2 + hover unification applied')
