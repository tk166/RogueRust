"""§330 文档对账：README.md §2 与 docs/sts-wiki-gap.md 的过时条目。

两批改动的来源：
* 内容大扩充 `0f3913a^..5842c59`（卡池 147/220、遗物 152/193、事件树 EVND、篝火六选项…）；
* 游戏流程 `094d34e^..7b32823`（Act 2/3 池子补齐、三幕事件 28/31、parasite/NoHeal/Doubt、
  精英保真、A17/18/19、Boss 相位）。

⚠️ 数字一律来自 `native/gap_check.py` 的 pastable 区块与三个 audit 脚本，**不手抄**。
"""

import io

README = 'README.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ══════════════════════════════════════════════════════════════════════════════
# README
# ══════════════════════════════════════════════════════════════════════════════
t = io.open(README, encoding='utf-8').read()

# ① 内容行：数字全换（含遗物 152、事件 38 行 / 35 条、变体 128/107、镜像字节）。
t = sub(t, """| **内容** | **61 怪 / 64 遭遇 / 295 条卡行（155 张基础 + 140 条升级行）/ 148 状态 / 166 敌人动作 / 153 遗物 / 33 药水（满池）/ **35 个事件**（三幕池 13+15+10 = 38 条，跨幕复用 3 条）/ 10 张起始牌**；**107 个动作有升阶变体**（124 个变体）。编译成 188,528 B 的 `rdcf` 镜像（core 镜像 151,092 B）。""",
        """| **内容** | **61 怪 / 64 遭遇 / 295 条卡行（155 张基础 + 140 条升级行）/ 148 状态 / 166 敌人动作 / 152 遗物 / 33 药水（满池）/ **35 个事件**（三幕池 13+15+10 = 38 条，跨幕复用 3 条；110 个 `EVND` 段）/ 10 张起始牌**；**107 个动作有升阶变体**（128 个变体）。编译成 189,024 B 的 `rdcf` 镜像（core 镜像 151,460 B）。""",
        'content row')

# ② 观察向量：122，不是 148。
t = sub(t, """**148** 个 `i32` 的战斗观察向量""", """**122** 个 `i32` 的战斗观察向量""", 'obs len')

# ③ 事件条目：19 个 / 缺 5 条 Act 2 → 35 条 / 28 of 31 / 只剩 cursed_tome。
old_events = """* **事件**：**19 个**（三幕池 10+8+4 = 22 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用）。**剧情分支已经是真树**（`EVND` 段表 + `EV.Entry`，选项数不固定，
  `golden_idol` 的两段三选一、`dead_adventurer` 的 21 个分支屏都在），选项支持条件
  （`Requires` / `RequiresAsc`）与一串效果。**仍缺**：事件级条件（"这条事件出不出现"）、
  "从手上任选一件遗物失去"（`N'loth`）、以及 Act 2 的 5 条事件
  （`vampires` / `masked_bandits` / `knowing_skull` / `council_of_ghosts` / `cursed_tome`）——
  逐条见 `docs/event-gaps.md`。"""
new_events = """* **事件**：**35 条**（三幕池 13+15+10 = 38 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用，110 个 `EVND` 段）。**剧情分支是真树**（`EVND` 段表 + `EV.Entry`，
  选项数不固定），选项支持条件（`Requires` / `RequiresAsc`）、按类型的选牌问句
  （`the_library` 20 选 1、`sensory_stone`、`falling` 的按类型删牌）、事件中途开战斗
  （`dead_adventurer` / `mysterious_sphere` / `colosseum`）、以及 A15 的糟化分支。
  **与 wiki 的 31 条相比是 28 条**：Act 1 **11/11**、Act 2 **12/13**、Act 3 **7/7** ——
  唯一明确不做的是 `cursed_tome`（`necronomicon` 不在范围）。**仍缺**：事件级条件
  （"这条事件出不出现"）与"从手上任选一件遗物失去"（`N'loth`）。逐条见 `docs/event-gaps.md`。"""
t = sub(t, old_events, new_events, 'events bullet')

# ④ Ascension 条目：128/107、59 without、[7b] 闸门。
old_asc = """* **Ascension**：**20/20 条都有机制**（14 条运行层规则 + 6 条走 `EACT.ProgramAsc`）；A7/A8/A9 的
  生命值按 wiki 的 `AscHP` 逐条钉住（§206，`INV_ASC_HP`）。数据侧：**79 个动作有升档变体
  （91 个变体）**，其余 **51 个**动作没有 wiki 出处（`gap_check.py` 打印 `without a variant: 51`）；
  逐条对账用 `python -X utf8 native/audit_asc_gap.py`（§258 起有脚本，不再靠人眼）。"""
new_asc = """* **Ascension**：**20/20 条都有机制**（14 条运行层规则 + 6 条走 `EACT.ProgramAsc`）；A7/A8/A9 的
  生命值按 wiki 的 `AscHP` 逐条钉住（§206，`INV_ASC_HP`），**档位属于怪物、不属于池子**
  （§315/§327：`Sentry` 钉 A8，两只 Slaver 钉 A7）。数据侧：**107 个动作有升档变体
  （128 个变体）**，其余 **59 个**动作 wiki 没有出处（`gap_check.py` 打印 `without a variant: 59`）。
  **wiki 写了 `{{Asc|N|` 而内容缺档的动作是 0 条** —— 这条由验收闸门 `[7b]`
  （`sts_content_check.py` 的 `check_wiki_asc_levels`）每次重比一遍；人跑的对账是
  `python -X utf8 native/audit_asc_gap.py`（§330 修好了它"只读第一个档位"的解析 bug，
  现在 MISSING/MISMATCH 都是 0，剩下的 4 条 EXTRA 是 `Thievery` 的 A17 写在招式计数器里）。"""
t = sub(t, old_asc, new_asc, 'ascension bullet')

# ⑤ 敌人条目：58/62 → 61/64；池子数字按 gap_check（17/13/10、精英 3/3/3）。
old_enemy = """* **敌人**：**58 怪 / 62 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**、**Act 2 普通池 13 条**（wiki 13/13）、**Act 3 普通池 10 条**
  （wiki 10/10）—— 我们**没有** Easy/Hard 的两段式，只用一个带权重的单池，"""
new_enemy = """* **敌人**：**61 怪 / 64 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**、**Act 2 普通池 13 条**（wiki 13/13）、**Act 3 普通池 10 条**
  （wiki 10/10）—— 我们**没有** Easy/Hard 的两段式，只用一个带权重的单池，"""
t = sub(t, old_enemy, new_enemy, 'enemy bullet')

# ⑥ "仍缺的机制"：删掉 Boss 相位与 A17/18/19（都已收口）。
t = sub(t, """  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、
  **"任选一件遗物失去"**的问句（`N'loth`）、Boss 分裂/相位（除 Slime Boss）、
  A2/3/4 之外的招式表替换（A17/18/19 的动作级覆盖已是 `ProgramAsc`）、
  药水差 0 瓶但**整手牌改费 / 自动打出 / 死亡拦截**仍然只有部分路径、逃跑（见 `docs/sts-wiki-gap.md` §2）。""",
        """  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、
  **"任选一件遗物失去"**的问句（`N'loth`）、**"下一回合多抽 / 多能量"**（只有
  `draw_reduction` / `no_draw`，没有反向的两条）、以及敌人侧的**逃跑**（运行层的脱战已有）。
  Boss 分裂/相位与 A17/18/19 的招式表**已收口**（§327–§329：六个 Boss 的相位规则逐条对过 wiki，
  `[7b]` 每次验收重比档位）。见 `docs/sts-wiki-gap.md` §2。""",
        'mechanisms bullet')

# ⑦ 遗物条目：把"18 件别的角色"换成 audit 的分类计数（可复现）。
old_relic = """  `docs/relic-inventory.md`，193 行、标明"有/缺"）。**缺的 41 件里 18 件是别的角色的球/姿态/毒、
  13 件是无尽模式 `Blight`、2 件 `circlet`、1 件 `necronomicon`（明确不做）**，
  铁甲战士这条线上真正的缺口只剩 `tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）、
  `golden_eye`（缺 `Scry`）与三件 `bottled_*`（拾取时绑牌）。"""
new_relic = """  `docs/relic-inventory.md`，193 行、标明"有/缺"）。**缺的 41 件按稀有度分**：
  Common 2 / Uncommon 7 / Rare 4 / Boss 7 / Shop 3 / Starter 2 / Event 1 / Special 2 /
  **Blight 13**（无尽模式，不做）。其中 **20 件是别的角色的球/姿态/Scry**（Defect 9 / Silent 4 /
  Watcher 7）、3 件是 `bottled_*`（拾取时绑牌）、`necronomicon` 明确不做、`circlet` 两件是无尽模式；
  铁甲战士这条线上真正的缺口只剩 `tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）与
  `golden_eye`（缺 `Scry`）。"""
t = sub(t, old_relic, new_relic, 'relic bullet')

# ⑧ 新增一节：这一轮（§308–§330）改了什么。
anchor = """* **第四幕与钥匙**：没有。`Recall` 就挂在它上面。"""
flow = """* **第四幕与钥匙**：没有。`Recall` 就挂在它上面。

### 2.1 最近这一轮改了什么（§308–§330，`094d34e^..7b32823`）

这一轮是**流程与保真**，不是新内容层：

* **运行层**：`RunState` 的 18 个漏网字段补齐 + 一条 `state-fields` 闸门（§308）；
  拾取类遗物的原子性（§309）；`orange_pellets` 的"清负面状态"（§310）。
* **遭遇与怪物**：Act 2 普通池 3 → **13/13**（§311–§314）、Act 3 **10/10**（§316–§317）、
  Act 1 硬池三场（§275）、组合槽（§277）、`(monster, tier)` 的 HP 建模（§315）。
* **事件**：`EVND` 段表 + 概率 + 条件 + 按类型的选牌问句 + 事件中途开战斗，
  三幕 **28/31**（§318–§325，逐条见 `docs/event-gaps.md`）。
* **战斗语义的三处偏差收口**（§326）：`parasite` 的移除惩罚、`mark_of_the_bloom` 的**战斗内**
  治疗拦截、`Doubt` 的回合末时序（顺序改成 ③④①②，Weak 留到下一回合）。
* **敌人保真**：四条精英组合遭遇的升档数值（§327）、A17/18/19 招式表（§328，
  现在有闸门 `[7b]` 每次重比 wiki 的 `{{Asc|N|`）、六个 Boss 的相位规则（§329–§330）。
* **这一轮挖出的两个真 bug**：`The Champ` 二阶段**每回合都 Execute**（`champ_exec` 从没被程序
  回写过，判据手设了它 —— §330）；`Relics` 里 `mutagenic_strength` **重复一行**（§330，
  顺带加了一道"段内 id 不许重复"的闸门 `[7g]`）。"""
t = sub(t, anchor, flow, 'flow section')

io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README updated')
