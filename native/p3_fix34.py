"""修闸门 34：3D 拾取改用 `window.__p1` 的真实布局 + CDP 鼠标；摘要计数提到 try 外。"""

import io

P = 'native/ui_next_loop_check.mjs'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''let failures = 0;''',
    '''let failures = 0;
/** 摘要用（在 `try` 里填；摘要行在 `try` 外，不能直接用里面的 `const`）。 */
const summary = { nodes: 0, steps: 0, chain: [] };''',
    'summary counters',
)

sub(
    '''    // 屏幕坐标：从 `window.__ui` 的布局拿（P1 的投影），没有就用命中测试反推。
    const points = await ev(`(() => {
      const ui = window.__ui;
      if (!ui) return null;
      const cards = ui.layout().cards;
      const enemies = ui.layout().enemies;
      const card = cards.find((c) => c.slot === ${chosenSlot});
      const enemy = enemies.find((e) => e.slot === ${chosenAction.targetSlot});
      if (!card || !enemy) return null;
      const toScreen = (p) => {
        const v = p.project ? p.project(ui.camera()) : p;
        return { x: v.x, y: v.y };
      };
      return { card: { x: card.x, y: card.y }, enemy: { x: enemy.x, y: enemy.y } };
    })()`);
    return { chosenSlot, chosenAction, points, enemies: state.enemies };''',
    '''    // 屏幕坐标来自 **`window.__p1`**（P1 每帧投影出来的真值，闸门 25–31 用的同一个）：
    // 手牌用 `hitX/hitY`（命中点），敌人用 `x/y` + `r`（身体中心与半径）。
    // ⚠️ 不要自己从 3D 坐标推屏幕像素 —— 那会变成"闸门和页面对布局的理解不一致"。
    const points = await ev(`(() => {
      const probe = window.__p1;
      if (!probe) return null;
      const screen = probe.layout();
      const card = screen.cards.find((c) => c.slot === ${chosenSlot});
      const enemy = screen.enemies.find((e) => e.slot === ${chosenAction.targetSlot});
      if (!card || !enemy) return null;
      return { card: { x: card.hitX, y: card.hitY }, enemy: { x: enemy.x, y: enemy.y } };
    })()`);
    return { chosenSlot, chosenAction, points, enemies: state.enemies };''',
    '3d layout via __p1',
)

sub(
    '''    // 真实鼠标：按下 → 移动 → 抬起（走 pointer 事件链，触发状态机）
    await page.drag(targetPick.points.card, targetPick.points.enemy);
    await sleep(200);''',
    '''    // 真实鼠标：按下 → 分 6 步移动 → 抬起（走 pointer 事件链，触发状态机）。
    // 与闸门 29 同一手法：中间必须有 move 事件，否则"极快拖动"会走另一条分支。
    const from = targetPick.points.card;
    const to = targetPick.points.enemy;
    await page.send("Input.dispatchMouseEvent", {
      type: "mousePressed", x: from.x, y: from.y, button: "left", buttons: 1, clickCount: 1,
    });
    for (let step = 1; step <= 6; step += 1) {
      const ratio = step / 6;
      await page.send("Input.dispatchMouseEvent", {
        type: "mouseMoved",
        x: from.x + (to.x - from.x) * ratio,
        y: from.y + (to.y - from.y) * ratio,
        button: "left",
        buttons: 1,
      });
      await sleep(16);
    }
    await page.send("Input.dispatchMouseEvent", {
      type: "mouseReleased", x: to.x, y: to.y, button: "left", buttons: 0, clickCount: 1,
    });
    await sleep(250);''',
    'real mouse drag',
)

sub(
    '''  const domNodes = await ev(`document.querySelectorAll("[data-node]").length`);''',
    '''  const domNodes = await ev(`document.querySelectorAll("[data-node]").length`);
  summary.nodes = map.nodes.length;''',
    'summary nodes',
)

sub(
    '''  const settled = await ev("window.__run.hand()");''',
    '''  summary.steps = steps;
  const settled = await ev("window.__run.hand()");''',
    'summary steps',
)

sub(
    '''  let scene = await sceneMatchesDom("装载后");''',
    '''  const chain = [];
  const noteScene = (id) => chain.push(id);
  let scene = await sceneMatchesDom("装载后");
  noteScene(scene.base);''',
    'chain start',
)

sub(
    '''  scene = await sceneMatchesDom("开局后");''',
    '''  scene = await sceneMatchesDom("开局后");
  noteScene(scene.base);''',
    'chain 1',
)

sub(
    '''  scene = await sceneMatchesDom("选祝福后");''',
    '''  scene = await sceneMatchesDom("选祝福后");
  noteScene(scene.base);''',
    'chain 2',
)

sub(
    '''  scene = await sceneMatchesDom("进入节点后");''',
    '''  scene = await sceneMatchesDom("进入节点后");
  noteScene(scene.base);''',
    'chain 3',
)

sub(
    '''  scene = await sceneMatchesDom("开战后");''',
    '''  scene = await sceneMatchesDom("开战后");
  noteScene(scene.base);''',
    'chain 4',
)

sub(
    '''  scene = await sceneMatchesDom("结算后");''',
    '''  scene = await sceneMatchesDom("结算后");
  noteScene(scene.base);''',
    'chain 5',
)

sub(
    '''    scene = await sceneMatchesDom("领完奖励后");''',
    '''    scene = await sceneMatchesDom("领完奖励后");
    noteScene(scene.base);''',
    'chain 6',
)

sub(
    '''} finally {
  await page.close();
}''',
    '''  summary.chain = chain;
} finally {
  await page.close();
}''',
    'chain assign',
)

sub(
    '''console.log(
  `UI_NEXT_LOOP PASS nodes=${domNodesOk} steps=${stepsOk} scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02`
);''',
    '''console.log(
  `UI_NEXT_LOOP PASS nodes=${summary.nodes} steps=${summary.steps} ` +
    `scene-chain=${summary.chain.join(">")}`
);''',
    'summary print',
)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('gate34 patched')
