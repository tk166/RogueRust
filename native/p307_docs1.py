"""§307 文档核对（一）：`docs/sts-wiki-gap.md` + `README.md`。

数字全部来自**脚本输出**，不手抄：
* `native/gap_check.py` 的 pastable 区块（原文贴入）；
* `native/audit_relic_gap.py`（152/193 + 桶 + METADATA 0）；
* `native/audit_card_gap.py --offline`（147/220，缺 73 全是观者）；
* `native/audit_asc_gap.py`（98 变体 / 85 动作）；
* `wc -l`（rd-core 75,382 / rd-run 16,318 / rd-wasm 21,062）。
"""
import io
import json
import subprocess

ROOT = 'D:/Vibe/sts-tui/'
GAP = ROOT + 'docs/sts-wiki-gap.md'
README = ROOT + 'README.md'
CONTENT = ROOT + 'tools/contentc/packages/sts/sts.roguedeck.json'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def run(*args):
    out = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                         encoding='utf-8', errors='replace')
    return out.stdout + out.stderr


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    tables = doc['EncounterTables']
    pools = {key: len(value) for key, value in tables.items() if isinstance(value, list)}
    events = {key: len(value) for key, value in doc['EventTables'].items() if isinstance(value, list)}
    top_events = sorted({e['Id'] for value in doc['EventTables'].values()
                         if isinstance(value, list) for e in value})

    # ── §1 表格里的四行 ───────────────────────────────────────────────────────────────────────
    patch(GAP,
          '''| 状态 | 内容里每一条状态要么有内核规则、要么**显式声明为 inert**（`is_declared_inert()`，**18 条**，`gap_check.py` 打印全名）。''',
          '''| 状态 | **146 条**；每一条要么有内核规则、要么**显式声明为 inert**（`is_declared_inert()`，**37 条**，`gap_check.py` 打印全名）。''')

    patch(GAP,
          '''| 卡牌（**数量**） | **117 行 = 61 张基础 + 56 条升级行**；其中 Red（铁甲战士）**40 / 75**，Colorless **14 / 70**（含诅咒与衍生牌）。**逐张盘点见 §A.1** | §218–§233 / `audit_card_gap.py` |''',
          '''| 卡牌（**数量**） | **293 行 = 154 张基础 + 139 条升级行**；口径内 **147 / 220（齐的 147 张里 Red 75/75 + Colorless 70/70 + 诅咒/状态）**，**缺的 73 张全是观者**。**逐张盘点见 §A.1** | §218–§233 / §306 核对 / `audit_card_gap.py` |''')

    patch(GAP,
          '''**6 条走内容数据**（A2/A3/A4 与 A17/18/19 的 `EACT.ProgramAsc`）。数值侧：**89 条变体 / 80 个动作** + 事件列表的 A15 变体。逐条见 §E | §159 / §187–§192、`gap_check.py` |''',
          '''**6 条走内容数据**（A2/A3/A4 与 A17/18/19 的 `EACT.ProgramAsc`）。数值侧：**98 条变体 / 85 个动作**（**53 个动作仍无 wiki 出处**，`audit_asc_gap.py` 打印）+ 事件列表的 A15 变体。逐条见 §E | §159 / §187–§192 / §306 核对、`gap_check.py` |''')

    patch(GAP,
          '''| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |''',
          '''| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |
| 遗物 | **152 / 193**；分桶与载体清单见 §D.2，逐条清单在 `docs/relic-inventory.md` | §259–§274 / §292–§305 |''')

    # ── §1.1 pastable 区块（原文贴入）────────────────────────────────────────────────────────
    patch(GAP,
          '''```
monsters 47 / encounters 34 / cards 117 (base 61 + plus 56) / statuses 46 /
enemy actions 130 / relics 15 / potions 33 / events 14 (6+4+4) / start deck 10
ascension variants 89 over 80 actions
image full   content.sts.rdcf             92644 B
image core   content.sts.core.rdcf        76448 B
```''',
          '''```
monsters 50 / encounters 47 / cards 293 (base 154 + plus 139) / statuses 146 /
enemy actions 138 / relics 152 / potions 33 / events 22 (10+8+4) / start deck 10
ascension variants 98 over 85 actions
image full   content.sts.rdcf            168008 B
image core   content.sts.core.rdcf       132044 B
```''')

    patch(GAP,
          '''> `89 / 80` 是**变体 / 动作**；`14` 是三个幕的事件池之和（`6+4+4`），不是单池大小。''',
          '''> `98 / 85` 是**变体 / 动作**；`22` 是三个幕的事件池之和（`10+8+4`），**不是**不同事件数 ——
> `golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用，去重之后是 **19 条**（§F.25）。
> `relics 152` 是**内容行**；wiki 有 193 条，缺 41 条（§D.2）。''')

    # ── §A.1：把当次账钉在"跑法"下面 ─────────────────────────────────────────────────────────
    patch(GAP,
          '''python -X utf8 native/audit_card_gap.py --offline   # 只读索引，CI/无网时用''',
          '''python -X utf8 native/audit_card_gap.py --offline   # 只读索引，CI/无网时用
```

**§306 核对的最新账**（`--offline`，wiki 索引 `native/wiki_card_index.json`，990 行）：

```
in-scope missing: 73   (have 147 of 220)
Red     75 / 75   （齐）
Colorless 70 / 70 （齐）
Purple  0 / 72    （缺 73 里的一张是 Purple Power；这 73 张全部属于观者）
content-only: blur, buffer, malaise, nightmare, patient_guard, rip_and_tear, skewer
             （wiki 归在别的颜色下，或本移植自有）''')

    # ── §D.2：桶表 + 现状行 ───────────────────────────────────────────────────────────────────
    patch(GAP, '''### D.2 遗物：**115 / 193** —— 已实现的规则与剩下的分档（§259–§274）''',
               '''### D.2 遗物：**152 / 193** —— 已实现的规则与剩下的分档（§259–§274，§292–§305）''')

    patch(GAP,
          '''| 桶 | 有 / 总 | 说明 |
|---|---|---|
| Common | 34 / 36 | 普通池 |
| Uncommon | 23 / 36 | 普通池 |
| Rare | 26 / 34 | 普通池 |
| Boss | 16 / 30 | 只从 Boss 奖励来 |
| Shop | 5 / 20 | 只从商人来 |
| Event | 14 / 18 | 只从事件来 |
| Starter | 4 / 4 | 开局自带 |
| Special | 0 / 2 | `circlet` 一类 |
| Blight | 0 / 13 | **无尽模式，不做** |''',
          '''| 桶 | 有 / 总 | 说明 |
|---|---|---|
| Common | 34 / 36 | 缺 `damaru` / `data_disk`（Defect 专属） |
| Uncommon | 29 / 36 | 缺 7 件，**6 件是别的角色专属**（`bottled_*` 三件 + `gold_plated_cables` / `symbiotic_virus` / `teardrop_locket`）与静默的 `ninja_scroll` |
| Rare | 30 / 34 | 缺 `emotion_chip` / `golden_eye` / `tingsha` / `tough_bandages` |
| Boss | 23 / 30 | 缺 7 件，**全是别的角色的能量/球**（`frozen_core` `holy_water` `hovering_kite` `inserter` `nuclear_battery` `violet_lotus` `wrist_blade`） |
| Shop | 17 / 20 | 缺 `melange` / `prismatic_shard` / `runic_capacitor` |
| Event | 17 / 18 | 只差 `necronomicon`（**明确不做**：打两次） |
| Starter | 2 / 4 | 铁甲战士的 `burning_blood` + 通用的 `black_blood`；缺 `cracked_core` / `pure_water` |
| Special | 0 / 2 | `circlet` 一类，**不做**（wiki 自己也标无用） |
| Blight | 0 / 13 | **无尽模式，不做** |

> 口径（§306 核对）：`native/audit_relic_gap.py` → `内容 152 条（152 条内核认识）`、
> `MISSING: 41`、`METADATA（两边都有但写错）: 0`、`IMPLEMENTED: … 内核不认识: 0`。
> 41 件里 **13 件 Blight + 2 件 Special + 约 18 件别的角色专属** ⇒ 铁甲战士这条线上真正
> 可做的只有 `necronomicon`（不做）、`tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）、
> `golden_eye` / `bottled_*`（拾取时绑牌）这几类。''')

    patch(GAP,
          '''**内容门要求"内容里的每件遗物内核都实现"**，所以缺的那 78 件不会半吊子地出现在池子里''',
          '''**内容门要求"内容里的每件遗物内核都实现"**，所以缺的那 41 件不会半吊子地出现在池子里''')

    patch(GAP,
          '''**§292 之后是 66 件**（Wave 1 做了 11 件 + 修了 `Shop` 档的静默缺口；逐件清单见
`port-plan.md` §292.6）。按"缺哪块载体"分档（细节见方法论文档 §3 / §8）：

| 档 | 件数 | 缺什么 | 例子 |
|---|---|---|---|
| 轻资产 | ~20 | 有钩子、缺一条判断 | `face_of_cleric` `sacred_bark` `golden_eye` `wing_boots` |
| 中资产 | ~30 | 缺一个**事实/事件** | `tough_bandages` `tingsha`（缺 `CardDiscarded`）、`bottled_*`（拾取时绑牌）、`gambling_chip`（§293–§295 之后的余项） |
| 不做 | 13 | 无尽模式 `Blight` 桶 | `accursed` `hauntings` `muzzle` |
| 其他角色 | ~15 | `Watcher`/`Silent`/`Defect` 专属 | `pure_water` `cracked_core` `ninja_scroll` `emotion_chip` |''',
          '''**§292 之后又做了 37 件**（§292–§305 逐节清单见 `port-plan.md` 对应小节）。剩下的 41 件按
"缺哪块载体"分档：

| 档 | 件数 | 缺什么 | 例子 |
|---|---|---|---|
| 别的角色的语言 | ~18 | 球 / 姿态 / 毒 / 弃牌事实 | `frozen_core` `nuclear_battery` `teardrop_locket` `emotion_chip` `tingsha` |
| 拾取时绑牌 | 3 | "选一张**攻击/技能/能力**牌绑进遗物" | `bottled_flame` / `bottled_lightning` / `bottled_tornado` |
| 静默的 | ~5 | 有钩子、缺一条判断 | `golden_eye`（`Scry`）`tough_bandages`（`CardDiscarded`）`ninja_scroll`（手上全是攻击） |
| 明确不做 | 15 | 无尽模式 / 无意义 | `necronomicon` + 13 件 `Blight` + 2 件 `circlet` |''')

    # ── §D.3：遭遇池（当前事实 + Act 2 的真实缺口）───────────────────────────────────────────
    old_start = '### D.3 遭遇：Act 1 的池子与还缺的三件（§275）'
    old_end = '### D.4 两个**表达不了**的机制缺口（分析见 `docs/mechanism-gaps-analysis.md`）'
    s = io.open(GAP, encoding='utf-8').read()
    start = s.index(old_start)
    end = s.index(old_end)
    new_d3 = '''### D.3 遭遇：三幕的池子（§275 / §287 / §306 核对）

当前事实（`sts.roguedeck.json` 的 `EncounterTables`，数字直接读出来）：

| 幕 | 普通池 | 精英池 | Boss 池 |
|---|---|---|---|
| 1 | **17** | 3（`three_sentries` / `gremlin_nob` / `lagavulin`） | 3（Slime Boss / Guardian / Hexaghost） |
| 2 | **3**（`shelled_parasite` / `chosen` / `snecko`） | 3（`gremlin_leader` / `book_of_stabbing` / `slavers`） | 3（Champ / Automaton / Collector） |
| 3 | **6**（`byrds` / `orb_walker` / `spiker` / `darklings` / `maw` / `spire_growth`） | 3（`giant_head` / `nemesis` / `reptomancer`） | 3（Time Eater / Awakened One / Donu & Deca） |

另外两处专用池：`EliteEvent`（3 条，`Dead Adventurer` 的伏击；Lagavulin 用**醒着的**变体，§287）
与 `ColosseumSlavers` / `ColosseumChampions`（各 1 条，`The Colosseum` 的两场，§286）。

**★ 最大的内容缺口在 Act 2 的普通池**：wiki 的 City 是 **Easy 5 + Hard 8 = 13** 种组合
（Easy：Spheric Guardian / Chosen / Shelled Parasite / 3 Byrds / 2 Thieves；Hard：Chosen+Byrds、
Cultist+Chosen、Sentry+Spheric Guardian、Snake Plant、Snecko、Centurion and Mystic、3 Cultists、
Shelled Parasite and Fungi —— `slaythespire.wiki.gg/wiki/The_City`），我们只有 **3** 条。
缺的组合里有 3 条要**新怪物**：`spheric_guardian`、`snake_plant`、`centurion` / `mystic`
（其余用现有怪物就能拼：`chosen` + `byrds`、`cultist` + `chosen`、`sentry` + 需要 Spheric、
`three_cultists`、`shelled_parasite` + 需要 Snake Plant 之外的那条可以拼）。

⚠️ 旧版本这一节写着"还缺三件"（Act 1 的三条组合遭遇），**那三条 §276/§277 已经做完**；
五个精英（Lagavulin / Book of Stabbing / Slavers / Nemesis / Reptomancer）也都做完了 ——
`Elite` / `Elite2` / `Elite3` 各 3 条就是证据。留着过期条目比漏写更坏。

'''
    s = s[:start] + new_d3 + s[end:]

    # ── §D.4：两个缺口都已关闭 ───────────────────────────────────────────────────────────────
    s = s.replace('''### D.4 两个**表达不了**的机制缺口（分析见 `docs/mechanism-gaps-analysis.md`）

| 缺口 | 缺什么载体 | 方案 |
|---|---|---|
| ~~真实事件的**剧情分支**被合并 + 条件选项~~ | **§278/§279/§280 已做**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`/`RequiresAsc`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose` / `gold_cost` / `heal_pct` / `heal_full` / 小数百分比（千分）。**事件级条件（"这个事件出不出现"）仍未做** —— 见 `docs/event-gaps.md` §3.1。 |
| 战斗中**每回合重掷**的随机没有值节点 | 一个"从程序里问随机数"的表达式 | `randomInt(Min,Max)` 走 `CombatState` 现有 RNG；★ 结果要在计划里固化（预检也会求值） |''',
'''### D.4 两个机制缺口：**都已关闭**（§277 提，§278–§281 关）

| 缺口 | 状态 |
|---|---|
| 真实事件的**剧情分支**被合并 + 条件选项 | ✅ **已关**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`/`RequiresAsc`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose` / `gold_cost` / `gold_all` / `card:<id>` / `heal_pct` / `heal_full` / 小数百分比（千分）。**事件级条件（"这个事件出不出现"）仍未做**，但它不是"表达不了"，而是"会重掷 `?` 房的每一次抽取" —— 见 `docs/event-gaps.md` §3.1。 |
| 战斗中**每回合重掷**的随机没有值节点 | ✅ **已关**：`expr::randomInt{Min,Max}` + `CombatState::draw_in_range`（唯一入口，`random_step` 推进、`seed` 不动）。★ 当年的担心（"预检也求值会吃掉两次"）经核对是**错的**：`preflight` 只查结构不求值 —— 真正的约束是"求值器只读"，所以取数只能在派发点。§281 有记录。 |

⚠️ **这一节原先叫"两个表达不了"，现在是"两个已关闭"**：留在这里是因为它记录了当年
"内容表达不了"的判断如何被推翻（也包括两条**当时以为是坑、其实是误判**的结论）。
''')

    # ── 新增 §F.25（插在 §F.24 之前，保持 F 段的时间顺序）────────────────────────────────────
    patch(GAP, '''### F.24 遗物：只改视图（§305）''',
               '''### F.25 遗物收尾：E 类手牌保留（§306）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `runic_pyramid` | *"At the end of your turn, you no longer discard your hand"* | §268 就接线了（内容状态带 `retain_hand` 标签 + `host.rs` 读标签）；**§306 才第一次有端到端判据** | 一致（修了一处偏差，见下） |
| Ethereal 与它的关系 | `Keywords`：*"If an Ethereal card is in your hand at the end of your turn, it is Exhausted"*；`Runic_Pyramid`：*"Still fires: Ethereal cards still Exhaust"* | **§306 修正**：原来整手保留把 Ethereal 也赦免了（`discard_hand` 整段短路）。现在"先算落点、再决定留不留"，落点 = 消耗堆那一档穿过去 | 一致（§306 之前是**偏差**） |

判据：`runic_pyramid_keeps_the_whole_hand_and_ethereal_still_exhausts`（rd-wasm，真打一场）——
三层：没有遗物 ⇒ 手牌 0；有遗物 ⇒ 手牌 > 0；Ethereal 消耗数**两侧相等**且 > 0。
负控 2 条全红（回到整段短路 / 把 Ethereal 也留下）。

### F.24 遗物：只改视图（§305）''')

    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(s)
    print('sts-wiki-gap.md updated')

    # ── README ────────────────────────────────────────────────────────────────────────────
    patch(README, '> 主计划在 `docs/port-plan.md`（§1–§233，每一轮都留数字、记下被推翻的结论）。',
                  '> 主计划在 `docs/port-plan.md`（§1–§306，每一轮都留数字、记下被推翻的结论）。')

    patch(README,
          '''| **战斗内核** | `rd-core` 21 个源文件、约 57k 行。''',
          '''| **战斗内核** | `rd-core` **22** 个源文件、约 **75k** 行。''')

    patch(README,
          '''| **运行层** | `rd-run` 约 7.9k 行。''',
          '''| **运行层** | `rd-run` 约 **16.3k** 行。''')

    patch(README,
          '''| **内容** | **49 怪 / 43 遭遇 / 293 条卡行（154 张基础 + 139 条升级行）/ 124 状态 / 130 敌人动作 / 115 遗物 / 33 药水（满池）/ 14 事件（三幕 6+4+4）/ 10 张起始牌**；**79 个动作有升阶变体**（91 个变体）。编译成 144,872 B 的 `rdcf` 镜像（core 镜像 111,528 B）。''',
          '''| **内容** | **50 怪 / 47 遭遇 / 293 条卡行（154 张基础 + 139 条升级行）/ 146 状态 / 138 敌人动作 / 152 遗物 / 33 药水（满池）/ 19 个事件（三幕池 10+8+4 = 22 条，跨幕复用 3 条）/ 10 张起始牌**；**85 个动作有升阶变体**（98 个变体）。编译成 168,008 B 的 `rdcf` 镜像（core 镜像 132,044 B）。''')

    patch(README,
          '''* **遗物**：**115 / 193**（`native/audit_relic_gap.py` 的账，`IMPLEMENTED: … 内核不认识` 必须为 0；
  逐条清单在 `docs/relic-inventory.md`，193 行、标明"有/缺"）。''',
          '''* **遗物**：**152 / 193**（`native/audit_relic_gap.py` 的账：`MISSING: 41`、
  `METADATA（两边都有但写错）: 0`、`IMPLEMENTED: … 内核不认识: 0`；逐条清单在
  `docs/relic-inventory.md`，193 行、标明"有/缺"）。**缺的 41 件里 18 件是别的角色的球/姿态/毒、
  13 件是无尽模式 `Blight`、2 件 `circlet`、1 件 `necronomicon`（明确不做）**，
  铁甲战士这条线上真正的缺口只剩 `tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）、
  `golden_eye`（缺 `Scry`）与三件 `bottled_*`（拾取时绑牌）。''')

    patch(README,
          '''* **事件**：14 个（三幕 6+4+4，与 wiki 的池子对齐），选项支持**一串**效果；A15 的 10/11 个房间有
  变体。仍是压缩过的：真实事件的**剧情分支**被合并（例：Golden Idol 的 Outrun / Smash / Hide
  三选一在我们这里只有两选项）。''',
          '''* **事件**：**19 个**（三幕池 10+8+4 = 22 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用）。**剧情分支已经是真树**（`EVND` 段表 + `EV.Entry`，选项数不固定，
  `golden_idol` 的两段三选一、`dead_adventurer` 的 21 个分支屏都在），选项支持条件
  （`Requires` / `RequiresAsc`）与一串效果。**仍缺**：事件级条件（"这条事件出不出现"）、
  "从手上任选一件遗物失去"（`N'loth`）、以及 Act 2 的 5 条事件
  （`vampires` / `masked_bandits` / `knowing_skull` / `council_of_ghosts` / `cursed_tome`）——
  逐条见 `docs/event-gaps.md`。''')

    patch(README,
          '''* **敌人**：47 怪 / 35 遭遇，三幕的弱/精英/Boss 池都是 wiki 的三选一。''',
          '''* **敌人**：**50 怪 / 47 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**（wiki 是 Easy 5 + Hard 8 的分子，我们用单池近似）。''')

    patch(README,
          '''  少数招式的 A17/A18 附加规则只做到"禁令"那一层。''',
          '''  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池只有 3 条**
  （`shelled_parasite` / `chosen` / `snecko`，wiki 是 13 种组合）—— 这是当前最大的敌人侧缺口，
  其中 3 条要新怪物（`spheric_guardian` / `snake_plant` / `centurion` + `mystic`）。''')

    patch(README,
          '''* **仍缺的机制**（不是内容行，是载体）：可变伤害已能表达（开局 `Rolls` + 计数器，§193/§258），
  但**战斗中随机**（每回合重掷）没有值节点；Boss 分裂/相位（除 Slime Boss）、''',
          '''* **仍缺的机制**（不是内容行，是载体）：~~战斗中的随机~~（§281 已做：`expr::randomInt` +
  `CombatState::draw_in_range`，唯一入口）、~~事件剧情分支~~（§278/§279 已做）——
  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、
  **"任选一件遗物失去"**的问句（`N'loth`）、Boss 分裂/相位（除 Slime Boss）、''')

    patch(README, '''### 5.2 20 道闸门''', '''### 5.2 21 道闸门''')

    patch(README,
          '''| 20 | `web-pixel` | `PIXEL_TEST PASS`（像素判据 + 故障注入自检） |''',
          '''| 20 | `web-pixel` | `PIXEL_TEST PASS`（像素判据 + 故障注入自检） |
| 21 | `coverage-matrix` | `COVERAGE_MATRIX PASS (rows=N, tests=N, fresh)` + `SELFTEST PASS (5 fixtures)`（生成物必须与盘上一致；孤儿行 / 偏差表漂移 / 扫描器自坏都是红） |''')

    patch(README,
          '''| `RD_DEBUG.givePotion("fire_potion")` | 往腰带里塞一瓶指定药水（测试掉落抽签太慢时的替代） |
| `RD_DEBUG.dropPotions()` | 清空腰带 |''',
          '''| `RD_DEBUG.givePotion("fire_potion")` | 往腰带里塞一瓶指定药水（测试掉落抽签太慢时的替代） |
| `RD_DEBUG.giveRelic("runic_pyramid")` | 按 id 塞一件遗物（有的遗物只在商人/事件里有，靠种子碰不到） |
| `RD_DEBUG.startAnEvent("forgotten_altar")` | 直接打开一条事件（同上；面板的写者是 `renderNode`） |
| `RD_DEBUG.dropPotions()` | 清空腰带 |''')

    patch(README,
          '''| `docs/` | `port-plan.md`（主计划 §1–§233）、`spec/`（21 份规格书）''',
          '''| `docs/` | `port-plan.md`（主计划 §1–§306）、`spec/`（19 份规格书）''')

    print('README updated')


main()
