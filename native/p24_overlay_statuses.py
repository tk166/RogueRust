"""§378：把状态画出来 —— 敌人标签里一行、英雄一侧一列。

## 为什么是 DOM 而不是 3D

与卡面文字同一条结论（`TextOverlay` 的头注释）：3D 文字要中文字形图集，DOM 用系统字体、
0 字节、任何字号都清晰。位置仍由 `layout` 驱动（英雄用 `layout.hero`，敌人用 `layout.enemies`）。

## 形状

* 敌人：`enemy-label` 里加一行 `.enemy-status`，每格 `名字 层数`（层数为 1 时只写名字）。
* 英雄：`.hero-status` 一列，钉在**左侧英雄头顶**（`layout.hero` 的投影点）。

⚠️ 层数**必须**显示：`力量 3` 与 `力量 1` 是两种不同的局面，只写"力量"等于没说。
"""

import io

PATH = 'web-next/src/overlay/TextOverlay.tsx'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 敌人标签里加状态 ────────────────────────────────────────────────────
OLD = '''      {scene.enemies.map((enemy) => (
        <div key={enemy.id} className="enemy-label" data-enemy={enemy.slot}>
          <span className="enemy-label__name">{enemy.name}</span>
          <span className="enemy-label__hp">
            {enemy.hp}/{enemy.hpMax}
          </span>
          <span className="enemy-label__intent">{enemy.intent}</span>
        </div>
      ))}'''

NEW = '''      {scene.enemies.map((enemy) => (
        <div key={enemy.id} className="enemy-label" data-enemy={enemy.slot}>
          <span className="enemy-label__name">{enemy.name}</span>
          <span className="enemy-label__hp">
            {enemy.hp}/{enemy.hpMax}
          </span>
          <span className="enemy-label__intent">{enemy.intent}</span>
          {/*
            §378：状态（力量/易伤/虚弱/束缚…）。玩家报的是"我方和敌人的各种状态看不到"——
            一个看不见的减益就是玩家没法绕开的减益。层数必须写出来（1 层与 3 层是两种局面）。
          */}
          {enemy.statuses.length > 0 && (
            <span className="enemy-label__status" data-enemy-status={enemy.slot}>
              {enemy.statuses.map((status) => (
                <span
                  key={status.id}
                  className="status-chip"
                  data-status-id={status.id}
                  data-status-stacks={status.stacks}
                  title={status.id}
                >
                  {status.name}
                  {status.stacks !== 1 ? ` ${status.stacks}` : ""}
                </span>
              ))}
            </span>
          )}
        </div>
      ))}

      {/*
        §378：英雄状态。位置由 `layout.hero`（3D 侧每帧投影）驱动，与敌人标签同一个 rAF 循环。
        放在 DOM 层而不是 3D：中文要字形图集，DOM 是 0 字节。
      */}
      {scene.hero.statuses.length > 0 && (
        <div className="hero-status" data-hero-status={scene.hero.statuses.length} ref={heroRef}>
          {scene.hero.statuses.map((status) => (
            <span
              key={status.id}
              className="status-chip"
              data-status-id={status.id}
              data-status-stacks={status.stacks}
              title={status.id}
            >
              {status.name}
              {status.stacks !== 1 ? ` ${status.stacks}` : ""}
            </span>
          ))}
        </div>
      )}'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# ── 2. 英雄状态也要跟帧（与敌人标签同一个 rAF）──────────────────────────────
OLD2 = '''      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-enemy]"))) {'''
NEW2 = '''      const heroNode = layer.querySelector<HTMLElement>("[data-hero-status]");
      if (heroNode && layout.hero) {
        // 英雄头顶再往上一点：与敌人标签的 `-r-22` 同一个理由（别压住血条）。
        heroNode.style.transform = `translate3d(${layout.hero.x}px, ${layout.hero.y - 46}px, 0) translate(-50%, -100%)`;
      }
      for (const node of Array.from(layer.querySelectorAll<HTMLElement>("[data-enemy]"))) {'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('TextOverlay: 状态渲染 + 跟帧')
