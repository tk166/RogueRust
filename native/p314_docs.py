"""§314（三）：文档 —— Act 2 齐了 13/13，并纠正 §311 写下的那句错话。

§311/§313 的文档里写着"`mugger` 的招式序列在 wiki 上只有一张表…照 Looter 的骨架写等于**发明**
一条规则"。**那句话是错的**：`Thieves` 页原文就是 *"**Mugger** has the same pattern as
**Looter**."* —— 所以照抄不是发明，是**按出处抄**。这一节把这句话改掉（留痕：错的是判断，
不是数据）。
"""
import io

ROOT = 'D:/Vibe/sts-tui/'
GAP = ROOT + 'docs/sts-wiki-gap.md'
README = ROOT + 'README.md'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch(GAP, '''monsters 54 / encounters 55 / cards 293 (base 154 + plus 139) / statuses 147 /
enemy actions 150 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 109 over 95 actions
image full   content.sts.rdcf            173808 B
image core   content.sts.core.rdcf       137088 B''',
'''monsters 55 / encounters 56 / cards 293 (base 154 + plus 139) / statuses 147 /
enemy actions 154 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 114 over 98 actions
image full   content.sts.rdcf            174928 B
image core   content.sts.core.rdcf       138140 B''')

    patch(GAP, '### D.3.1 Act 2：wiki 的 13 条，做了 12 条（§311–§313）',
               '### D.3.1 Act 2：wiki 的 13 条，**13 条齐了**（§311–§314）')

    patch(GAP, '| 2 Thieves | Easy | 2 | ❌ 要 `mugger` |',
               '| 2 Thieves | Easy | 2 | ✅ §314（`mugger` + 1 Looter 在左、1 Mugger 在右） |')

    patch(GAP, '''只剩一条缺口：

**`mugger`**（`2 Thieves` 用）—— 全新怪物。它和 Looter 共享 `stolen_gold` /
`carryAwayStolenGold`，但它的招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；
照 Looter 的骨架写等于**发明**一条规则，所以等到能核对清楚时再做。''',
'''**没有缺口了。** 上一版这里写着"`mugger` 的招式序列在 wiki 上只有一张表，照 Looter 的骨架写
等于发明一条规则" —— **那句话是错的**：`Thieves` 页原文就是 *"**Mugger** has the same pattern
as **Looter**."*。照抄不是发明，是**按出处抄**（§314）。留下的教训：把"我没找到出处"写成
"没有出处"，会让一条本来很便宜的内容永远排不上队。

⚠️ 唯一仍然例外的是 `Sentry and Spheric Guardian`（见下），它卡在"同一只怪物跨档位"的
**建模**上，不是内容没写。

### D.3.1b Mugger = Looter 的规则表 + Act 2 的数字（§314）

| 项 | Looter | Mugger |
|---|---|---|
| HP | 44-48（A7 46-50） | 48-52（A7 50-54） |
| Mug | 10（A2 11） | 10（A2 11） |
| Lunge | 12（A2 14） | 16（A2 18） |
| Smoke Bomb | 6 Block | 11 Block（A17 17） |
| Thievery | 15（A17 20） | 15（A17 20） |
| Escape | 带钱跑 | 同 |

顺手补上两个贼的 **Thievery A17 = 20**：它不是新规则，只是 `stolen_gold += X` 的第二个阈值
（wiki 两处表都写 `15 (20 17)`）。''')
    print('gap doc updated')


main()
