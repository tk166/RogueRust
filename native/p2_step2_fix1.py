"""修两处：Mock 视图的 id 保持原样；提交日志只记一次。

## ① id 被加了槽位后缀

`viewFromMock` 里我写成 `id: ${card.id}-${slot}`，于是 P1 闸门按 `strike` 比 id 就红了。
唯一性其实由 React key（`${card.id}-${index}`）保证，id 没必要动。

## ② 每次出牌被记两次

`applyCommit` 里 push 一次、effect 里又 push 一次 ⇒ 闸门"恰好 1 次提交"变成 2。
两个引擎都走 effect 那条路，所以只留 effect 里的那一次。
"""

import io

VIEW = 'web-next/src/view/combatView.ts'
APP = 'web-next/src/App.tsx'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    VIEW,
    '''    hand: scene.hand.map((card, slot) => ({
      id: `${card.id}-${slot}`,''',
    '''    hand: scene.hand.map((card) => ({
      // ⚠️ id 保持原样：P1 的闸门按 `strike` 这样的 id 断言。重复 id 不影响 React key
      // （`Stage` 用的是 `card.id + index`）。
      id: card.id,''',
    'mock id',
)

edit(
    APP,
    '''  const applyCommit = useCallback((entry: CommitLogEntry) => {
    commits.current.push(entry);
    setScene((current) => {''',
    '''  const applyCommit = useCallback((entry: CommitLogEntry) => {
    // ⚠️ **不要**在这里 push 提交日志：effect 里统一记一次（两个引擎都走那条路）。
    // 第一版两边都 push ⇒ 每次出牌被记两次，闸门"恰好 1 次提交"立刻红。
    setScene((current) => {''',
    'single push',
)
print('fixed')
