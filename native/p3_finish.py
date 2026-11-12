"""CombatScreen：战斗有结果后的"继续"面板（P3 用它收尾）。"""

import io

P = 'web-next/src/combat/CombatScreen.tsx'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    '''      {/*
        战斗有结果：**只有**外层给了 `onFinish` 才画"继续"（P2 回归页没有下一屏）。
        文案来自内核的 `result` 判别值，不是"我猜打赢了"。
      */}
      {view.result !== "ongoing" && props.onFinish && (
        <div className="combat-finished" data-combat-finished={view.result}>
          <h2>{view.result === "victory" ? "战斗胜利" : view.result === "defeat" ? "战败" : "战斗结束"}</h2>
          <p className="combat-finished-hint">
            {view.result === "victory" ? "敌人已被击败。" : "这一局到此为止。"}
          </p>
          <button type="button" data-combat-continue onClick={() => props.onFinish?.()}>
            {view.result === "victory" ? "领取奖励" : "结束这一局"}
          </button>
        </div>
      )}

      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}''',
    'finish panel',
)

# 战斗结束后不再显示手势提示（那一层按钮已经没有意义）
sub(
    '''      {!modalOpen && (
        <div className={`gesture-hint${noticeKind ? ` is-${noticeKind}` : ""}`} role="status" aria-live="polite">''',
    '''      {!modalOpen && view.result === "ongoing" && (
        <div className={`gesture-hint${noticeKind ? ` is-${noticeKind}` : ""}`} role="status" aria-live="polite">''',
    'hide hint when finished',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('CombatScreen: finish panel')
