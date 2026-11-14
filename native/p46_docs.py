"""§385–§391 的文档（玩家第三轮）。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: %d' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


SECTION = '''

---

## §385–§391 玩家第三轮：三哨兵相位、掷骰伤害、史莱姆老大分裂、状态名、悬浮窗

七条报障。这一轮有一条**重要教训**：玩家给的存档 `RDA1-…` 因为**内容指纹变了**被内核
拒收（`这份档案是另一份内容里的一局（档案 54af44dd，本机 a4733e56）`）—— 那是设计如此
（内容变了 id 未必还对得上），但也意味着**内容修正会作废旧存档**。所以复现靠"闸门 + 真战斗
测试"，不靠存档。

| # | 报障 | 根因 | 修法 |
|---|---|---|---|
| 7 | 商店/事件删卡、篝火锻造的选卡界也是英文名，且行宽参差 | `DeckSelectOverlay` 用内核的英文 `titles` **盖住**了 i18n 中文名（与 §384 同一个病根）；没有卡面；行宽由内容决定 | i18n 优先 → 徽章 + 中文名 + 悬浮详情；`.deck-select-row` 里名字 `flex: 1` ⇒ 每行等宽 |
| 8 | 奖励屏的遗物没有悬浮窗 | 面板由各屏自己画，奖励屏那份只挂在药水/卡上 | 统一到**一个** store + **一个**宿主（§389） |
| 9 | 战斗里的遗物/药水/卡牌/状态也要悬浮窗（显示在药水栏下方、战场上方） | 同上；且手牌的文字层是 `pointer-events: none`（必须，否则挡 3D 射线） | `CardTipHost` 挂在 subbar 之后；手牌用**状态驱动**（`hoverCardSlot`/`detailSlot`），状态 chip 单独开事件 |
| 10 | 第一次精英战三只哨兵相位相同 | 内核按 `(round-1) % Actions.len()` 取招 ⇒ 三条 `Actions` 一样就同相；wiki：**中间的从 Beam 起手**（1+2） | 内容把 `sentry_2` 的 `Actions` 换序（名册 + 内联两份都要换，闸门要求一致） |
| 11 | `orichalcum` / `incense_burner` 等状态显示英文 | `zh.ts` 的 `statuses` 表只有 13 条（来自仓库里的 legacy 文件），内容有 150 条 | 三条来源：legacy → **跨表复用**（`standard.X` 的 `X` 在 relics/cards/potions 里已翻译）→ 人工译名表 ⇒ **158/150**（含别名） |
| 12 | 攻击数值是 0（虱子的 Bite / Curl Up） | 意图预览 `program_damage` 只认**字面量**；而 Bite 的伤害是 `combatantCounter("roll.bite")`（开战掷 5–7）⇒ 答 -1 | 预览带**状态**求值（`combatantCounter` / `combatantStatusStacks`），解不出的仍然答 -1（不猜） |
| 13 | 史莱姆老大半血不分裂；被砸 35 后血条不动 | ① 内容阈值写的是 **≤10 血**、召唤两只**中等**史莱姆固定 10 血、外加一条"半血改打 slam"的规则把分裂挡掉了；② 顶栏在战斗里读的是**运行层** HP（那是故意不跟的，战斗结算才写回） | ① 阈值改 **50% 上限**、召唤 1 只 L 酸 + 1 只 L 尖各带**当前血量**、删掉 slam 规则；② 顶栏在战斗中读**战斗快照** |

### 385.1 三哨兵：wiki 两个来源

* wiki.gg `Sentry`：*"Uses Bolt followed by Beam, repeating… **In the Elite encounter, the middle
  Sentry instead uses Beam followed by Bolt.**"*
* fandom `Sentry`：*"1st and 3rd sentries will always start with Bolt while the 2nd sentry will
  always start with Beam."*

内核的循环是 `(round - 1) % Actions.len()`（`intent.rs::select_action` B3/B4）—— **按轮次**取，
不看"上一招"。所以"换序"就是"换相位"，**不需要动内核**。
⚠️ 内容里 encounter 的**内联条目**与 `Monsters` **名册**必须一致（`sts_content_check.py` 会比对），
两份都要换；名册的动作顺序还对着 `inv:§4.2`，所以闸门那张表也要一起改（并写上 wiki 原话）。

### 385.2 掷骰伤害：为什么"不猜"这条纪律要留一半

预览现在能解 `combatantCounter` / `combatantStatusStacks`（都只需要**状态**，不需要掷骰）。
仍然解不出来的（`multiply` 套状态修饰、`sel.eventTarget` 指向别人）**照旧答 -1**，
界面上就不显示数字 —— 猜一个中位数比不显示更糟：玩家会拿它做决策。

### 385.3 史莱姆老大：三处内容修正 + 一条已知偏差

wiki.gg `Slime Boss`：*"When its HP is at or below 50%, it will split into 2 smaller Slimes
**with its current HP**."* / *"Split — Disappears and spawns 1 Acid Slime (L) and 1 Spike Slime (L)
with its current HP."*

三处修正：阈值 `currentHealth * 100 <= maxHealth * 50`、召唤 `acid_slime_l` + `spike_slime_l`
各带 `currentHealth`、删掉那条 `slam` 规则（并把 Boss 身上不属于它的 `standard.split` 摘掉）。

⚠️ **顺序是有语义的**：`Then` 里必须**先造后毁**。第一版写的是"先销毁自己"，于是
`currentHealth` 求值时本体已经不在 ⇒ 两只 L 史莱姆只有 **1 点血**（测试当场抓到）。

⚠️ **已知偏差**：原版是"血量到 50% ⇒ 当前意图**立刻**变成 Split，然后在它的回合分裂"；
我们是在**受到伤害的那一刻**就分裂（少一个回合的"预备"）。

### 385.4 顶栏 HP：战斗内读哪一份

`RunStore.reconcile` 的注释写着"战斗内运行层的 HP 是**故意**不跟的"（战斗结算才写回）。
于是玩家被砸 35 点、顶栏血条纹丝不动 —— 看起来像"这次攻击没生效"。
修法：`liveHp = inFight ? combat.hero.hp : run.health`。两种情况下都对（战斗外两者相等，有对账保证）。

### 385.5 状态中文名：三条来源

1. **legacy 表**（原来的 13 条 + 五条轴，无前缀的键同时登记 `standard.` 别名）；
2. **跨表复用**：`standard.X` 的 `X` 在 `relics` / `cards` / `potions` / `monsters` 里已经翻译过
   ⇒ 直接用（`orichalcum` → 奥利哈钢、`incense_burner` → 香炉、`corruption` → 腐化…91 条）。
   理由：状态名与它来源的名字本来是一回事，两份翻译只会漂；
3. **人工译名表**（`STATUS_ZH`，51 条）：只在状态里出现的词（`curl_up` 蜷缩 / `artifact` 神器 /
   `intangible` 无形…）。来源是官方中文本地化，**只作显示名**，不进任何规则。

覆盖：**158/150**（含别名；`standard.thorns` 这类无前缀 legacy 键也算）。

### 385.6 一个面板（§389）

需要"指一下就显示详情"的地方有六处，分属两棵组件树（外壳 / 战斗屏）。所以：
**模块级 store + 一个宿主**，挂在 subbar 之后 = **药水栏下方、战场上方**（玩家点名要的位置）。
* 鼠标 `pointerenter` / 触摸 `pointerdown` / 键盘 `focus` 三条路都调 `showTip()`；
* 手牌**不能**挂指针事件（`.text-layer` 是 `pointer-events: none`，必须的：否则挡 3D 射线），
  所以手牌的详情由 **`hoverCardSlot` / `detailSlot` 状态**驱动；
* 状态 chip 很小、在名牌/头顶，单独 `pointer-events: auto`（不会挡住把牌拖到敌人身上）。

### 385.7 闸门

闸门 56（`ui-layout-words`）从 19 条扩到 **27 条**：新增
状态名穷尽 + `orichalcum`/`incense_burner` 点名、遗物 chip 的悬浮窗、牌组选择器的
卡面/中文名/**等宽**/费用、战斗中顶栏 HP == 战斗快照。

内核新增三条**真战斗**测试（`rd-wasm`）：
`the_three_sentries_start_out_of_phase`、`the_intent_preview_reads_rolled_damage`、
`the_slime_boss_splits_into_two_large_slimes_at_half_health`。
另有两条**旧内容**测试按新事实改写（`host::the_boss_phase_splits_once_at_low_health` 的阈值夹具、
`intent::a_combinator_rule_switches_the_move` 改成"半血不改招"+ 组合条件换靶子到
`spheric_guardian`）。

### 385.8 还欠的

* 存档与内容指纹绑定 ⇒ **每次改内容都会作废旧存档**（这是设计，但玩家会觉得"回档没了"）；
* 分裂的"预备回合"没做（见 385.3 的偏差）；
* `intent.targetIntendsAttack` 这类"读目标"的条件在预览里仍然答 -1（`观察弱点` 的意图条不显示伤害，
  它本来也不造成伤害，所以不影响）；
* 状态 chip 只有名字 + 层数，没有图标；`STATUS_ZH` 那 51 条没有第二来源核对（只作显示名）。
'''

PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §385' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + SECTION)

edit(
    'README.md',
    '> **卡牌详情**：奖励屏/商店/**战斗中的选牌弹窗**（武装、头击…）里把鼠标移到牌上（触屏是按住）',
    '> **卡牌详情**：奖励屏/商店/**战斗中的选牌弹窗**（武装、头击…）/**牌组选择器**（删卡、锻造）里\n> 把鼠标移到牌上（触屏是按住）',
    'readme tip',
)
print('docs written')
