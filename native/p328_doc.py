"""§328 文档。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §328' not in t
t = t.rstrip('\n') + '\n' + """
## §328 A17/18/19 招式表：先量化，再补，再上闸门

### 量化（这一步比补更重要）

"还剩哪些招式表没做"不能用印象回答。写了三遍审计脚本（`native/p328_audit*.py`），
前两遍都**漏**了，第三遍才对：

1. 第一遍按**文件名**当怪物 id —— 快照其实是按 **wiki 页面** 存的（`slavers.txt` 里有
   `= Blue Slaver =` / `= Red Slaver =` 两节，`shapes.txt` 里有 Spiker/Repulsor/Exploder），
   于是 59 个怪物里 25 个"没有快照"、166 条动作里 16 条"名字对不上"；
2. 第二遍按**节**切 —— 但正则把 `== Pattern ==` 也当成节名（`^=\\s*(.+?)\\s*=$` 会匹配它），
   而且单怪快照根本没有节头，结果只匹配到 **1** 条动作；
3. 第三遍：`^=\\s*([^=]+?)\\s*=$` + "首个节头之前算页面自己的怪物" + `DisplayName` 认领 +
   "节名与 id 互相包含"兜底 ⇒ **115/166** 条动作对得上。

结论：wiki 写了 `{{Asc|N|` 而内容缺档的只有 **6** 条，其中 **3 条是别的机制已表达**：

| 动作 | wiki 的档 | 我们的表达 |
|---|---|---|
| `darkling.nip` | A2（9-13） | 遭遇记录的 `Rolls`（`roll.nip`） |
| `book_of_stabbing.multi_stab` | A18（N = 回合+1） | `book_stab_single_bump` 计数器 |
| `the_guardian.twin_slam` | A9/A19（Mode Shift 35/40） | `mode_shift_budget` 计数器 |

真缺 3 条，全是 A17：`cultist.incantation`（Ritual 4 → 5）、`fungi_beast.grow`（Strength 4 → 5）、
`fat_gremlin.smash`（5 伤害 + 1 Weak，**再加** 1 Frail）。

⚠️ 顺带确认了一件好事：带 `ProgramAsc` 的 **107** 条动作**全部**被检查器的 `INV_ASC_VARIANTS`
钉住 —— 也就是说"值漂了"这一类问题已经有闸门，缺的只是"档位漏了"。

### 闸门：把临时审计变成常设

`native/sts_content_check.py` 加了 `check_wiki_asc_levels`（`[7b]`）：直接读
`native/wiki_asc/*.txt` 的意图行，数 `Effect` 里的 `{{Asc|N|`，要求内容该动作的 `ProgramAsc`
**至少**覆盖这些等级。

两条独立的账现在都在：

* `INV_ASC_VARIANTS`（人抄的清单）—— 证明"内容与清单一致"，连**值**都比；
* `check_wiki_asc_levels`（wiki 快照驱动）—— 证明"清单与 wiki 一致"的**档位**那一半。

"别的机制表达"的三条走显式白名单 `INV_ASC_LEVELS_BY_OTHER_MEANS`，**每条都带理由**
（空理由会被 `fail`）。负控两条：① 删掉 `cultist` 的 A17 ⇒
`asc.wiki.cultist.incantation: the wiki names A[17], the content has A[2]`；
② 删掉白名单里 `the_guardian.twin_slam` 那一条 ⇒ `asc.wiki.the_guardian.twin_slam` 立刻红
（白名单条目必须真的被用到，否则它就是静音开关）。

行为侧判据 `the_three_a17_move_rows_take_effect_in_the_fight` 在 **A16 / A17** 两侧各跑一次
（只测 A17 会漏掉"内容写了、`intent::execute_action` 没选中"）；负控把 A17 改回 4 层 ⇒
红在 `A17: fungi_beast.grow -> standard.strength`。

数字：`rd-core 812 / rd-run 214 / rd-wasm 177`、units **1203**（下限 1202 → 1203）；
四条对拍不动（`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §328 ok')

g = io.open(GAPS, encoding='utf-8').read()
old = '| **精英池** |'
idx = g.index(old)
# 在"精英池"那一行后面加一行说明招式表覆盖
row_end = g.index('\n', idx)
note = ('\n| **招式表升档** | §328：wiki 写了 `{{Asc\\|N\\|` 而内容缺档的动作 **0** 条'
        '（审计 115/166 条意图行；3 条由别的机制表达：`darkling.nip` 走 `Rolls`、'
        '`book_of_stabbing.multi_stab` 走 A18 计数器、`the_guardian.twin_slam` 走 `mode_shift_budget` 计数器）'
        ' | — （`native/sts_content_check.py` 的 `[7b]` 每次验收都重比一遍） |')
g = g[:row_end] + note + g[row_end:]
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g)
print('gap doc ok')
