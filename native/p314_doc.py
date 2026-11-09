"""§314 记账：Mugger —— Act 2 普通池 13 / 13。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §314 Mugger：Act 2 的普通池 **13 / 13**

`2 Thieves` 是 Act 2 的最后一条组合。上一轮我把它记成"要 `mugger`，而它的招式序列在 wiki 上
只有一张表 —— 照 Looter 的骨架写等于**发明**一条规则"。**那句话是错的**：`Thieves` 页原文
就是

> *"**Mugger** has the same pattern as **Looter**."*

所以这一节没有设计，只有**按出处抄 + 换数字**：

| 项 | Looter | Mugger |
|---|---|---|
| HP | 44-48（A7 46-50） | 48-52（A7 50-54） |
| Mug | 10（A2 11） | 10（A2 11） |
| Lunge | 12（A2 14） | **16（A2 18）** |
| Smoke Bomb | 6 Block | **11 Block（A17 17）** |
| Thievery | 15（A17 20） | 15（A17 20） |
| Escape | 带钱跑 | 同 |

顺手把**两个贼**的 Thievery A17 = 20 补上（wiki 两处表都是 `15 (20 17)`）。它不是新规则，
只是 `stolen_gold += X` 的第二个阈值 —— 而 `ProgramAsc` 的变体是**整段程序**，所以 A17 档
必须把 A2 的伤害一起带上（取"最大阈值"，不是叠加）。

### 314.1 一个包装害我查了半天

第一版 `mugger.*` 的 `combatantCounter` 把 `CounterId` 写成了 `{"value": "last_move"}`（用了
`ident()` 包装），而**既有内容是裸字符串**。内核两边都读得懂（Id 包装被忽略），但检查器的
事实渲染把 `prev_move = last_move` 这一对"历史记账"认不出来 ⇒ `split_history` 不剥它 ⇒
`asc.mugger.*` 全红，报的却是"facts 不对"。

教训与 §313 同一条：**同一个字段在内容里有两种合法写法时，事实层只能认一种**。
顺手把全文件的 13 处同类包装统一成裸串（语义等价，编译器本来就忽略包装）。

### 314.2 判据与负控

`the_mugger_mugs_steals_fifteen_gold_and_escapes_with_it`（rd-wasm）三侧：
① 第 1 回合是 `Mug`（"和 Looter 同一套"的唯一可观察证据）；
② `Mug` 打 10 点 + `stolen_gold` 到 15；
③ `Escape` 把 15 记进 `gold_carried_away`、计数器清零、人摘出战斗。

**负控 2/2 红**（`native/p314_negative.py`）：给第 1 回合加一条 Lunge 规则 ⇒ ① 红；
把 `Escape` 里的 `carryAwayStolenGold` 拿掉 ⇒ ③ 红。两处都**同时**改 `Monsters` 与遭遇里的
敌人记录副本（§313 的教训）。

### 314.3 账

内容：**55 怪 / 56 遭遇 / 147 状态 / 154 敌人动作 / 114 变体（98 动作）**；
镜像 **174,928 B**（core 138,140 B）；**Act 2 普通池 13 / 13**（`Sentry and Spheric Guardian`
仍例外：它卡在"同一只怪物跨档位"的建模上，不是内容没写）。

`rd-core` 809 / `rd-run` 194 / `rd-wasm` **158**（+1）；聚合闸门 **22/22**（`rust-units 1161`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§314 Mugger' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1160') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1160', '  [int]$UnitsFloor = 1161'))
    print('§314 recorded; UnitsFloor 1161')


main()
