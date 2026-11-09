"""§315 记账：`MaxHealthAsc` 的档位按怪物钉 —— Act 2 真正 13 / 13。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
PLAN = ROOT + 'docs/port-plan.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

DOC = r"""
---

## §315 `(monster, tier)` 的 HP 建模：Act 2 真正 13 / 13

`Sentry and Spheric Guardian` 是 Act 2 的最后一条。它一直做不了，而我把它记成"要等跨档位建模"
—— 那句话**方向对，位置错**：卡住的不是内核，是**判据的模型**。

### 315.1 卡在哪

`check_ascension_health` 这样推档位：

    精英池 ⇒ A8、Boss 池 ⇒ A9、其余 ⇒ A7

多数怪物确实如此（普通 A7 / 精英 A8 / Boss A9），但 **Sentry 是反例**：它是 Act 1 的**精英**
（wiki：38-42，**A8** 起 39-45），**同时**又是 Act 2 的**普通**敌人 —— 同一只怪、同一张表。
按池子推，同一条怪物记录会被要求**同时**是 A7 与 A8，两条不可能同时成立。

### 315.2 改法：档位来自 wiki，不来自池子

`INV_ASC_HP_LEVEL` 显式写出"Sentry 是 A8"，其余怪物仍按池子推（**存量 100 多条记录一个字都
不用改**）。于是同一条 `{A8, 39}` 在精英池与普通池的**两处记录里都是正确答案**；A7 时没有可用
的行 ⇒ 血量仍是 38（内核取"≤ ascension 的最大阈值"，`+10%` 回退在跑层是 0）。

判据 `the_sentry_keeps_one_hp_table_across_two_tiers` 钉三件事：
① 两处记录的 `MaxHealthAsc` **一字不差**（否则就是两套数字，迟早漂）；
② **A7 时 38、A8 时 39**（在**普通**遭遇里也一样）—— 只钉 A8 不会把 A7 提前改掉；
③ 同一条遭遇第二个槽位（Spheric Guardian）的开局 40 块仍然生效。

**负控 2/2 红**（`native/p315_negative.py`）：把 `INV_ASC_HP_LEVEL` 清空（回到"按池子推"）
⇒ 清单判据红（这条正是 §311 记录的"两条不可能同时成立"）；把 Act 2 那条记录写成 `{A7, 39}`
⇒ A7 的断言红。

### 315.3 一条想记下来的方法学

同一条判据里"档位"与"数值"是**两个事实**：`{A8, 39}` 里的 8 来自 wiki 的表头、39 来自表体。
原来的实现把 8 从**池子**推出来，于是把"这只怪在哪个池子"当成了"它的表头是哪一档" —— 这两个
问题只对**大多数**怪物有同一个答案。**把"通常如此"写成"总是如此"，余下的那些就会一直做不了。**

### 315.4 账

内容：**55 怪 / 57 遭遇 / 147 状态 / 154 敌人动作 / 114 变体（98 动作）**；
镜像 **175,108 B**（core 138,320 B）；**Act 2 普通池 13 / 13 全部进池**。

`rd-core` 809 / `rd-run` 194 / `rd-wasm` **159**（+1）；聚合闸门 **22/22**（`rust-units 1162`）。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    if '§315 `(monster, tier)` 的 HP 建模' not in plan:
        io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)
    accept = io.open(ACCEPT, encoding='utf-8').read()
    assert accept.count('  [int]$UnitsFloor = 1161') == 1
    io.open(ACCEPT, 'w', encoding='utf-8', newline='\n').write(
        accept.replace('  [int]$UnitsFloor = 1161', '  [int]$UnitsFloor = 1162'))
    print('§315 recorded; UnitsFloor 1162')


main()
