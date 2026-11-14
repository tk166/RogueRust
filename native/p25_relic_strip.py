"""§378：顶栏只有"✦ 2"一个数字 ⇒ 加一条**常驻遗物条**（徽章 + 名字）。

## 为什么放在 subbar 而不是顶栏

顶栏已经有 8 个格子（HP/金币/幕/层/牌组/遗物/药水/设置），再塞 10 个遗物会把它挤成两行、
在 390px 上直接溢出。`run-subbar` 是"第二排常驻信息"，药水腰带就在那儿 —— 遗物条放同一排，
战斗里和商店里都看得见（`run-main` 之上一律渲染）。

## 判据

`data-relic-strip` 的格子数 == `run.relicCount`，每格有 `data-relic-id`（内容 id），
名字走 i18n。闸门 55 拿它断言"遗物真的画出来了，不是只有数字"。
"""

import io

PATH = 'web-next/src/run/RunApp.tsx'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''      {/* ── 药水腰带 + 牌堆浏览 ───────────────────────────────────────────── */}
      {run && (
        <div className="run-subbar">'''

NEW = '''      {/* ── 遗物条 + 药水腰带 + 牌堆浏览 ───────────────────────────────────── */}
      {run && (
        <div className="run-subbar">
          {/*
            §378：遗物**必须看得见**。玩家报的是"我方的药水和遗物在战场和商店 ui 里没有显示"——
            顶栏只有一个 `✦ 2`，而"我到底有什么遗物"是每一次决策的前提（回血/加金币/加能量）。
            徽章 + 名字（名字可 hover 看 id），与药水腰带同一排。
          */}
          <div className="relic-strip" data-relic-strip={state.relics.length}>
            {state.relics.map((id, index) => (
              <span className="relic-chip" key={`${id}-${index}`} data-relic-id={id} title={id}>
                <Badge look={badgeLook("relics", id)} title={id} />
                <span className="relic-chip__name">{displayName("relics", id)}</span>
              </span>
            ))}
            {state.relics.length === 0 && <span className="muted">没有遗物</span>}
          </div>'''

assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('RunApp: 遗物条')
