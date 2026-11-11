"""探针加 hover 读数 + 闸门加三条断言。

## 为什么这三条必须进闸门

1. **hover 与合法目标同源**：这是本轮修的东西。断言"拖到敌人上方时，视觉 hover 与
   `state.hoverSlot` 是同一个敌人；松开在空白处两者都清空" —— 不查这条，"两个来源"会悄悄回来。
2. **紧凑态文字锚点（UX-2）**：文字必须落在**露出来那条**的中心（`hitX`），不是牌心。
3. **点选路径**：我拆掉了敌人身上的 `onPointerUp`（落点统一由 `window.pointerup` 算），
   而"按下牌→原地松开→再点敌人"这条路原来正是靠它。不测就等于赌它没坏。
"""

import io

PROBE = 'web-next/src/probe.ts'
APP = 'web-next/src/App.tsx'
GATE = 'native/ui_next_check.mjs'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① ProbeOptions（`debugSetEnemyHp` 那一份）───────────────────────────────
edit(
    PROBE,
    '''  detailSlot: () => number;
  modalOpen: () => boolean;
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 只在''',
    '''  detailSlot: () => number;
  modalOpen: () => boolean;
  /** 指针下的卡牌与敌人（视觉用）。由 `App` 提供，闸门用它验证"与合法目标同源"。 */
  hoveredCard: () => number;
  hoveredEnemy: () => number;
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 只在''',
    'ProbeOptions',
)

# ── ② Probe 接口（`typeScale` 那一份）──────────────────────────────────────
edit(
    PROBE,
    '''  detailSlot: () => number;
  modalOpen: () => boolean;
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 手牌文字的字号''',
    '''  detailSlot: () => number;
  modalOpen: () => boolean;
  /**
   * 指针下的卡牌与敌人（**视觉**用，任意敌人）。
   *
   * 与 `state().hoverSlot` 是两个不同的问题：`hoverSlot` 只认**合法目标**（提交与绿环用），
   * 这里认**任意**敌人（高亮与红圈用）。两者必须由**同一个**屏幕命中函数回答 ——
   * 闸门断言它们在合法目标上一致。
   */
  hovered: () => { card: number; enemy: number };
  openDetail: (slot: number) => void;
  setModal: (open: boolean) => void;
  /** 手牌文字的字号''',
    'Probe interface',
)

# ── ③ 实现 ────────────────────────────────────────────────────────────────
edit(
    PROBE,
    '''    detailSlot: () => options.detailSlot(),
    modalOpen: () => options.modalOpen(),''',
    '''    detailSlot: () => options.detailSlot(),
    modalOpen: () => options.modalOpen(),
    hovered: () => ({ card: options.hoveredCard(), enemy: options.hoveredEnemy() }),''',
    'probe impl',
)

# ── ④ App 提供 ────────────────────────────────────────────────────────────
edit(
    APP,
    '''      detailSlot: () => detailSlot,
      modalOpen: () => modalOpen,''',
    '''      detailSlot: () => detailSlot,
      modalOpen: () => modalOpen,
      hoveredCard: () => hoverCardSlot,
      hoveredEnemy: () => hoveredEnemySlot,''',
    'app probe args',
)

edit(
    APP,
    '''  }, [store, scene, detailSlot, modalOpen, onDetail]);''',
    '''  }, [store, scene, detailSlot, modalOpen, hoverCardSlot, hoveredEnemySlot, onDetail]);''',
    'app probe deps',
)

# ── ⑤ 闸门：hover 同源 + 点选路径 ─────────────────────────────────────────
edit(
    GATE,
    '''// ── 4. 只剩一个敌人时，定向牌仍**必须**落在敌人身上（与旧页面的有意分歧）──''',
    '''// ── 3c. hover 与合法目标同源（本轮修的"两个来源"）────────────────────────
// 以前 hover 来自 R3F 射线、提交来自 hitTest，几何不同（真 mesh vs 半径 +14px）⇒ 边缘自相矛盾。
const hoverCardAt = await cardPoint(7);
const grabbedHover = await mouseHold(hoverCardAt, enemy0At, { steps: 4 });
check(
  grabbedHover.phase === "pressed" && grabbedHover.handSlot === 7,
  "按下命中的是第 7 张牌（耸肩）",
  JSON.stringify(grabbedHover)
);
const hoverState = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  hoverState.h.enemy === hoverState.s.hoverSlot && hoverState.s.hoverSlot === 0,
  "拖到敌人 0 上方：视觉 hover 与合法目标**同一个**敌人",
  JSON.stringify(hoverState)
);
await mouseRelease(empty);
const hoverAfter = await evaluate("({ s: window.__p1.state(), h: window.__p1.hovered() })");
check(
  hoverAfter.h.enemy === -1 && hoverAfter.s.phase === "idle",
  "松开在空白处：hover 与目标都清空",
  JSON.stringify(hoverAfter)
);

// ── 3d. 点选路径（不拖拽）：按下同一张牌原地松开 ⇒ targeting；再点敌人 ⇒ 提交 ──
// 敌人身上的 onPointerUp 已被拆掉（落点统一由 window.pointerup 算），这条路必须实测。
const tapAt = await cardPoint(0);
const tapPress = await mousePress(tapAt);
check(
  tapPress.phase === "pressed" && tapPress.handSlot === 0,
  "点选路径：按下第 0 张牌",
  JSON.stringify(tapPress)
);
await mouseRelease(tapAt); // 原地松开 ⇒ 位移 0 ⇒ 点按语义
const afterTap = await evaluate("window.__p1.state()");
check(
  afterTap.phase === "targeting",
  "点选路径：原地松开后进入 targeting（未出牌）",
  JSON.stringify(afterTap)
);
const commitsBeforeTapTarget = (await evaluate("window.__p1.commits()")).length;
await page.send("Input.dispatchMouseEvent", {
  type: "mousePressed",
  x: enemy1At.x,
  y: enemy1At.y,
  button: "left",
  buttons: 1,
  clickCount: 1,
});
await page.send("Input.dispatchMouseEvent", {
  type: "mouseReleased",
  x: enemy1At.x,
  y: enemy1At.y,
  button: "left",
  buttons: 0,
  clickCount: 1,
});
await sleep(80);
commits = await evaluate("window.__p1.commits()");
check(
  commits.length === commitsBeforeTapTarget + 1 && commits.at(-1)?.targetSlot === 1,
  "点选路径：再点敌人 1 ⇒ 提交到敌人 1",
  JSON.stringify(commits.at(-1))
);

// ── 4. 只剩一个敌人时，定向牌仍**必须**落在敌人身上（与旧页面的有意分歧）──''',
    'gate hover/tap',
)

# ── ⑥ 闸门：紧凑态文字锚点 ────────────────────────────────────────────────
edit(
    GATE,
    '''check(
  readability.compactCount >= 5,
  "窄屏下多数牌收起为紧凑态（390px 放不下 10 个中文标题的实测结论）",
  `compact=${readability.compactCount}/10, minVisibleW=${readability.minVisibleW}px`
);''',
    '''check(
  readability.compactCount >= 5,
  "窄屏下多数牌收起为紧凑态（390px 放不下 10 个中文标题的实测结论）",
  `compact=${readability.compactCount}/10, minVisibleW=${readability.minVisibleW}px`
);

// ── UX-2：紧凑态的文字必须落在**露出来那条**的中心（hitX），不是牌心 ─────────
// 叠放顺序是右压左，牌心可能被右邻盖住 —— 文字放牌心等于把费用数字塞到邻居底下。
const anchorDrift = await evaluate(`(() => {
  const cards = window.__p1.layout().cards;
  const bySlot = new Map(cards.map((c) => [c.slot, c]));
  const worst = [];
  for (const node of document.querySelectorAll("[data-card]")) {
    if (!node.classList.contains("is-compact")) continue;
    const slot = Number(node.dataset.card);
    const screen = bySlot.get(slot);
    if (!screen) continue;
    const rect = node.getBoundingClientRect();
    worst.push({ slot, drift: Math.round(Math.abs((rect.left + rect.right) / 2 - screen.hitX)) });
  }
  return worst;
})()`);
check(anchorDrift.length > 0, "紧凑态至少有一张牌（否则这条断言没有样本）", JSON.stringify(anchorDrift));
check(
  anchorDrift.every((item) => item.drift <= 2),
  "紧凑态文字锚点落在露出条中心（与 hitX 偏差 <= 2px）",
  JSON.stringify(anchorDrift)
);''',
    'gate text anchor',
)
print('probe + gate assertions added')
