"""§326 文档 —— 三个"已知缺口"的收口。

数字：units 1201、rd-core 812 / rd-run 214 / rd-wasm 175、
镜像（重编后以 gap_check 为准）。
"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


text = io.open(PLAN, encoding='utf-8').read()
assert '## §326' not in text, 'port-plan already has §326'
entry = """
## §326 三个已知缺口的收口：`parasite` / 战斗内 NoHeal / `Doubt` 的时序

三条都是**之前如实记下来的偏差**，不是新功能。三条的共同点：它们在"看起来都对"的地方
一直是对的，只在某一侧漏掉。

### 1. `parasite` 的移除惩罚

wiki：*"If transformed or removed from your deck, lose 3 Max HP."*

落点是 `remove_at` —— 牌离开牌组的**唯一**入口（删牌、改造、`remove_all`、商店、烟斗全走它）。
写在别处就会有一条路漏掉，而漏掉的那条看起来完全正常。

⚠️ 这是"内容规则写在运行层"：**先例已经存在**（`ASCENDERS_BANE` 就是同一个形状 ——
`remove_card` 直接拒绝删它），所以这里也是一个命名常量 `PARASITE` + 一条上限损失常量，
而不是去读内容（§133）。上限**至少留 1**：打到 0/负数会让每一条按上限算的效果跟着错，
而那些错都不会响。

判据四条：删牌 / 改造 / 按种类全删（两张 ⇒ -6）/ **删别的牌不该掉上限**（负向对照）。

### 2. `mark_of_the_bloom` 的战斗内治疗

§321 只挡住了运行层的治疗汇（`heal_after_combat`）；战斗内的药水/卡牌/状态触发走
`exec::heal_for`，那才是战斗侧的**唯一**汇（`magic_flower` 的 ×150% 也在那儿）。

做法：`CombatState.heal_blocked`（**model-only**，参考没有这个字段 ⇒ 不进 `hash_golden`
也不进快照，与 `encounter` 同一条规矩）＋ `heal_for` 里一次 gate ＋ `rd-wasm` 在
"战斗建好、第 1 回合还没开始"那一刻从 `RunState::blocks_healing()` 写进去（晚于第 1 回合的话，
回合初的治疗已经漏过去了）。

判据两侧：`rd-core` 对镜像里**每一条** `node.heal` 都验"挡住时 0 / 不挡时真的回"；
`rd-wasm` 验"这位有没有被接进战斗"（没接时 `rd-core` 的判据照样绿，所以两半各测一次）。

### 3. `Doubt` 的回合末时序（`Normality` 同族的偏差根因）

旧顺序：① 牌在手生命周期（`Doubt` 在这里给 1 层 Weak）→ ② 弃手牌 → ③ TurnEnded 触发器
（**`standard.weak` 的衰减就在这里**）→ ④ 时长衰减。于是 Doubt 给的 Weak 在同一次回合末
被自己的衰减吃掉；参考里它留到下一回合。

修法：改成 **③④①②**。三条既有契约都保住：

* `Burn` / `Regret` 属于 ①，仍在**弃手牌之前**（Regret 数完整手牌，参考原话
  "before the end-of-turn discard, which is deferred"）；
* 敌人在自己回合末给玩家上的状态（走同一个 ③）也不会被同一次回合末吃掉（与参考同侧）；
* `Doubt` 的 Weak 落在衰减之后 ⇒ 活到下一回合。

⚠️ 这是一次**顺序契约**改动，所以先看基线：`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、
`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394` **全部不动**（这四条对拍里的场景没有"同一回合末
既跑 ① 又跑 ③"的组合），`rd-core` 也只有**一条**判据红 —— 而那条正是当初**记录旧行为**的
`the_two_event_curses_behave_as_their_pages_say`（它当时断言"被吃掉"，并写着"这是已知的顺序
偏差"）。把它的断言翻成"活下来"，它就从记录偏差变成了钉住修正 —— 这正是"判据写在行为上"
的价值。

数字：`rd-core 812 / rd-run 214 / rd-wasm 175`、units **1201**（下限 1197 → 1201）。
"""
text = text.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(text)
print('port-plan ok')

# wiki-gap 的偏差表里，Doubt 那一行要改成"已修"。
t = io.open(GAPS, encoding='utf-8').read()
if 'Doubt' in t and '§326' not in t:
    print('note: wiki-gap mentions Doubt; check the deviation table by hand')
