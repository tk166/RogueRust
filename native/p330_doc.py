"""§330 文档节的记录（port-plan）。"""

import io

PLAN = 'docs/port-plan.md'

t = io.open(PLAN, encoding='utf-8').read()
assert '## §330' not in t
t = t.rstrip('\n') + '\n' + """
## §330 文档对账：剔除过时信息，顺手挖出两个真 bug

两批改动的内容都要进文档：`0f3913a^..5842c59`（卡池/遗物/事件/篝火的系统性补全）与
`094d34e^..7b32823`（这一轮的流程与保真）。做法是**先把数字重算一遍再改字**，而不是照着旧文档改。

### 重算（全部由脚本给）

`gap_check.py` 的 pastable 区块、`audit_card_gap.py`、`audit_relic_gap.py`、`audit_asc_gap.py`。
过时最狠的几处：

| 位置 | 旧 | 现在 |
|---|---|---|
| README 内容行 | 153 遗物 / 35 事件（22 条池）/ 变体 124 / 188,528 B | **152 遗物** / 35 事件（**38 条池，110 个 `EVND` 段**）/ 变体 **128** / 189,024 B |
| README 观察向量 | 148 个 `i32` | **122**（`OBS_LEN` 的算式注释一直是 122） |
| README 事件 | "19 个…仍缺 Act 2 的 5 条" | **35 条 / 与 wiki 31 条比是 28 条**（11/12/7），只差 `cursed_tome` |
| README 敌人 | "58 怪 / 62 遭遇"（同一页另一处写 61/64） | **61 / 64** |
| gap §1 状态 | 146 | **148** |
| gap §1 卡行 | 293 = 154 + 139 | **295 = 155 + 140** |
| gap §1 Ascension | 98 变体 / 85 动作 / 53 无出处 | **128 / 107 / 59**，且缺档 **0**（闸门 `[7b]`） |
| gap §1.1 pastable | 变体 117/101、179,288 B | **128/107、189,024 B**；去重事件 21 → **35** |
| gap §D.3 池子表 | Act 2 = 10、Act 3 = 6 | **13 / 10**（wiki 13/13、10/10） |
| gap §D 遗物 | "15 件…总数仍未核对" | **152 / 193**，`audit_relic_gap.py` 早就在 |
| gap §D 篝火 | "只有 Rest / Smith" | **六个全通**（§259） |
| gap §D 商店 | "无色 14/70" | **70/70**（缺的只是商店那一排货架） |
| gap §D 事件 | "14 个（6+4+4）…词表闭集" | **35 条 / 28 of 31**，`EVND` 真树 |
| gap §A.1 | §246 时期的"施工单"（30+ 张待补） | 整段删掉（那些载体 §247–§252 全补了） |
| gap §H | 六个 Boss 各有一串"剩余差异" | 逐条重写，**基本全空** |

### 顺手挖出来的两个真 bug

1. **`The Champ` 二阶段每回合都 Execute**。`anger` 把 `champ_exec` 置 0、规则是
   `champ_exec <= 0 ⇒ Execute`，而 **`execute` 从不回写它** ⇒ 二阶段每回合命中。
   它活下来的原因值得记：判据是**手设**这个计数器的
   （`set_counter(&mut state, &actor, "champ_exec", 1)`）—— 判据把程序该做的事替它做了，
   与 §326 之前 `Doubt` 那条同一个病。
   修法不动内核：`anger` 写 `-1`（欠一次）、`execute` 写 0、四个随机招各 `+1`（相对计数器），
   规则拆成 `< 0` 与 `>= 2` 两条。判据改成**跑真程序**：写入侧（五条程序各自写什么）+
   读取侧（1 不 Execute、2 必须 Execute、-1 必须 Execute）。
   ⚠️ 踩到一个坑并记下来：**同一个 `CombatState` 里连跑四个动作**时后面的动作不写计数器
   （新 arena 里四个都正常），所以判据拆成"每条动作一个新 arena"，不去依赖累积状态。

2. **`Relics` 里 `mutagenic_strength` 重复了一行**（153 行、152 条）。22 道闸门一条都没红：
   `SEC_IDX` 照样索引得到、`audit_relic_gap.py` 用 `set` 自动吃掉重复，
   只有把 `gap_check` 的 153 与 audit 的 152 放在一起读才看得出来。
   ⇒ 加闸门 `[7g]`：**段内 id 不许重复**（1029 个 id、8 个段，负控把 `akabeko` 复制一份
   ⇒ `unique.Relics: 'akabeko' appears 2 times`）。

### 工具也会说谎：`audit_asc_gap.py` 的截断

`ROW = r"\\{\\{Intents Table/row([\\s\\S]*?)\\}\\}"` 非贪婪，而 `{{Asc|2|4}}` 自带 `}}`
⇒ 每行只读到**第一个**升档，于是它报了 18 条假 MISMATCH / 3 条假 MISSING（那三条在 `Rolls` 里）。
修成"按下一个 row/end 切块"，并把"由别的机制表达"的白名单挪到 `native/asc_other_means.py`
（检查器与审计脚本 import **同一份**，否则就是"同一个词表被两处认识就一定漂"）。
修完：MISSING 0 / MISMATCH 0 / VIA_OTHER_MEANS 5 / EXTRA 4（`Thievery` 的 A17 写在招式计数器里）。

数字：`rd-core 812 / rd-run 214 / rd-wasm 179`、units **1205**（下限不动）；
四条对拍不动（`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §330 ok')
