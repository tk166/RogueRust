"""抬起的牌，文字框用**整张牌宽**（`visibleW = w`）。

被压住的是"静止在手里"的牌；一旦抬起来，它就在最前面、整张都露着，
此时还按 `min(w, stride)` 排文字，会让规则折成 5 行（截图里"对所有/敌人造/成 8 点/伤害。"）。
"""

import io

p = 'web-next/src/stage/Stage.tsx'
t = io.open(p, encoding='utf-8').read()
old = '''    for (let index = 0; index < cards.length; index += 1) {
      const card = cards[index];
      const neighbour = cards[index + 1];
      const stride = neighbour ? Math.abs(neighbour.x - card.x) : card.w;
      card.visibleW = Math.min(card.w, Math.max(stride, 1));
      card.hitX = card.x - (card.w - card.visibleW) / 2;
      card.hitY = card.y;
    }'''
new = '''    for (let index = 0; index < cards.length; index += 1) {
      const card = cards[index];
      const neighbour = cards[index + 1];
      const stride = neighbour ? Math.abs(neighbour.x - card.x) : card.w;
      // 抬起的牌在最前面，整张都露着 ⇒ 文字用整张牌宽（否则规则会被压成很窄的一列）。
      card.visibleW = card.lifted ? card.w : Math.min(card.w, Math.max(stride, 1));
      card.hitX = card.x - (card.w - card.visibleW) / 2;
      card.hitY = card.y;
    }'''
assert t.count(old) == 1
io.open(p, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('lifted visibleW = w')
