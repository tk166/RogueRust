"""§310（五）：文档 —— F.19 那条错了两年的"wiki"列，以及镜像大小的两处数字。

这条错的性质值得单独写一段：**"wiki"那一列是从我们自己的行为抄的**。
代码给 +3 力量/+3 敏捷 → 文档把"wiki 语义"也写成 +3 力量/+3 敏捷 → 对账永远通过。
而 `coverage-matrix` 还把 `orange_pellets_pays_once_all_three_card_kinds_were_played`
（测试名把错规则写死）记成 `Implemented + TestNamed`：那条测试替 bug 站了岗。
"""
import io

ROOT = 'D:/Vibe/sts-tui/'
GAP = ROOT + 'docs/sts-wiki-gap.md'
README = ROOT + 'README.md'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # 镜像大小（§310 重编之后）
    patch(GAP, 'image full   content.sts.rdcf            168008 B',
               'image full   content.sts.rdcf            167996 B')
    patch(README, '编译成 168,008 B 的 `rdcf` 镜像（core 镜像 132,044 B）。',
                 '编译成 167,996 B 的 `rdcf` 镜像（core 镜像 132,044 B）。')

    # F.19：那一行既是内容错误，也是**核对方法**的错误
    patch(GAP,
          '''| `orange_pellets` | 一回合内 Power+Attack+Skill ⇒ +3 力量/敏捷 | **已做**（纯内容，三个计数器） | 一致（Focus 属 Defect，本角色没有 ⇒ 只给力量+敏捷） |''',
          '''| `orange_pellets` | 一回合内 Power+Attack+Skill ⇒ **清除所有 Debuff** | **§310 修正**（新节点 `node.removeDebuffs`；三个计数器仍在） | 曾是**偏差**（给 +3 力量/+3 敏捷 —— 那不是同一条规则）。⚠️ 旧版本这一行的"wiki"列写的就是我们自己的行为，所以"对账"永远通过 |''')

    # 在 F.19 表格下补一条方法学的注
    patch(GAP,
          '''| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **§300 已做**（新节点 `setCardCostOverride`） | 已修 |''',
          '''| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **§300 已做**（新节点 `setCardCostOverride`） | 已修 |

> ⚠️ **这张表的"wiki"列必须来自 wiki，不能来自我们的代码。** §310 就是一次教训：
> `orange_pellets` 那一行两列都写"+3 力量/敏捷"，于是代码错、文档跟着错、对账一路绿。
> 判据的写法也跟着改了 —— 见 §F.26。''')

    # 新增 F.26（§310）
    patch(GAP, '''### F.24 遗物：只改视图（§305）''',
          '''### F.26 遗物：清负面状态（§310）

| 项 | wiki（两个独立来源） | 我们 | 性质 |
|---|---|---|---|
| `orange_pellets` | *"Whenever you play a Power, Attack, and Skill in the same turn, **remove all debuffs**"* | **§310 修正**：新节点 `node.removeDebuffs`，按**定义**的极性筛（`status_polarity`），删实例而不是把层数减到 0 | 一致（§310 之前是**内容错误**，不是简化） |

判据：`orange_pellets_removes_every_debuff_and_keeps_the_buffs`（rd-core，真打三张牌）——
四侧：只有两类 ⇒ 不清；三类齐 ⇒ Weak/Frail 清空；**正面状态一条不许动**；第四张牌不重复付。
负控：把"只清 Debuff"改成"清 Buff" ⇒ 判据红（这就是判据里"正面状态"那一侧存在的理由）。

⚠️ 实现里踩过一个坑，记在这里因为它是一个**通用形态**：第一版用
`StatusInstance.polarity` 判极性，结果把力量/敏捷也清了 —— 实例上的极性是
`applyStatus` 那一刻**抄**进去的字段，谁都可能写错（测试助手给每条都写 `Debuff`）。
内核里早就有唯一入口 `status_polarity(definition_id, content)`（内容 `STAT.Polarity` 优先、
目录兜底，Artifact 也用它）。**"字段里有一份现成的值"不等于"那是权威的值"。**

### F.24 遗物：只改视图（§305）''')
    print('docs updated')


main()
