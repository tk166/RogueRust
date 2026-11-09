"""§313（九）：文档 —— Act 2 现在 12 / 13，只剩 `2 Thieves`（要 `mugger`）。

数字全部来自 `gap_check.py`：`54 / 55 / 147 / 150 / 109 / 95 / 173,808 / 137,088`。
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
    patch(GAP, '''monsters 52 / encounters 54 / cards 293 (base 154 + plus 139) / statuses 147 /
enemy actions 144 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 102 over 89 actions
image full   content.sts.rdcf            171180 B
image core   content.sts.core.rdcf       134744 B''',
'''monsters 54 / encounters 55 / cards 293 (base 154 + plus 139) / statuses 147 /
enemy actions 150 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 109 over 95 actions
image full   content.sts.rdcf            173808 B
image core   content.sts.core.rdcf       137088 B''')

    patch(GAP, '''| Centurion and Mystic | Hard | 6 | ❌ 要"指定某一只友军"的选择器 |''',
'''| Centurion and Mystic | Hard | 6 | ✅ §313（`sel.alliesWithDefinition` + `intent.allyMissingHealth`） |''')

    patch(GAP, '''两条缺口各缺什么（**不是"没抄"**）：

1. **`mugger`** —— 全新怪物。它和 Looter 共享 `stolen_gold` / `carryAwayStolenGold`，但它的
   招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；照 Looter 的骨架写等于
   **发明**一条规则，所以等到能核对清楚时再做。
2. **`centurion` + `mystic`** —— `Protect` 要给 **Mystic**（不是自己、也不是全体）挂 15 块；
   `Mystic` 的 `Heal` 要给全体敌人回 16（这条已有：`sel.allAllies` + `heal`）。前者缺
   "按定义挑一只友军"的选择器 —— `sel.allAllies` 会把 Centurion 自己也算上。''',
'''只剩一条缺口：

**`mugger`**（`2 Thieves` 用）—— 全新怪物。它和 Looter 共享 `stolen_gold` /
`carryAwayStolenGold`，但它的招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；
照 Looter 的骨架写等于**发明**一条规则，所以等到能核对清楚时再做。

### D.3.2 Centurion + Mystic 带来的两块新零件（§313）

| 零件 | 形状 | 为什么不能复用旧的 |
|---|---|---|
| `sel.alliesWithDefinition` | 叶子 `AllAlliesOfSource` + 一层 `DefinitionFilter` | `Protect` 要给 **Mystic**（按**定义**）。`sel.lowestHealthAlly` 在 Centurion 掉到 10 血时会返回 Centurion —— 那是另一个行为，负控就是把它换上去，判据当场红 |
| `intent.allyMissingHealth` | `{Op, Value}`，数**自己阵营**里缺 ≥ Value 血的人 | `intent.healthPercent` 只看出手者自己；Mystic 是后排奶妈，"自己缺 16 血"几乎是另一条规则 |
| `combatantCount`（表达式） | `{Selector, AliveOnly}` | `Protect` 的"独自时自保"要在**动作程序**里数活着的友军。`intent.enemyAliveCount` 只活在**意图规则**的条件求值器里 —— 写进程序会 `Expr(UnsupportedKind)`（实测撞过） |

⚠️ 一条**踩过两次**的坑：`intent.not` 的内层必须是 `intent.allOf`，不能写表达式的 `and`
（那是**表达式**的布尔与，条件求值器不认识 ⇒ `UnknownConditionKind`）。第一次改的时候只在
`Monsters` 里改、忘了 `Encounters` 里那份**敌人记录副本**还在用旧规则，于是"改完还是红"。''')
    print('gap doc updated')


main()
