"""卡面接上二维素材：手牌 + 卡牌详情（`Badge`）。

## 为什么之前是空的

素材流水线（§369）只接到了**奖励屏 / 商店 / 牌组 / 药水**，而玩家最常看的地方 ——
**战斗手牌**与**卡牌详情** —— 还是纯文字。而且 `ViewCard.id` 是**合成 id**
（`hand-<slot>-<defSlot>`），拿它查素材表会走降级（`hand-0-1` 不在清单里）。

所以先补 `ViewCard.defId`（**内容 id**，`strike` / `strike+`），再在文字层画徽章。
"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. ViewCard 暴露内容 id ────────────────────────────────────────────────
patch('web-next/src/view/combatView.ts', [
    (
        'defId field',
        '''export interface ViewCard {
  readonly id: string;''',
        '''export interface ViewCard {
  /**
   * **合成 id**（`hand-<slot>-<defSlot>`）：只用来当 React key / 命中标识。
   *
   * ⚠️ 它**不是**内容 id —— 拿它查素材表/中文表会走降级。内容 id 是 `defId`。
   */
  readonly id: string;
  /** 内容 id（`strike` / `strike+`）：素材表与 i18n 都按它查。 */
  readonly defId: string;''',
    ),
    (
        'wasm defId',
        '''    return {
      id: `hand-${card.slot}-${card.defSlot}`,
      name: displayName("cards", cardId),''',
        '''    return {
      id: `hand-${card.slot}-${card.defSlot}`,
      defId: cardId,
      name: displayName("cards", cardId),''',
    ),
])
print('done')
