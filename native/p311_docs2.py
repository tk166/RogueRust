"""§311（八·续）：README 的敌人行、§D.3 重写、`event-gaps.md` 的两处事实。

README 前两处已经在上一版脚本里落盘（`51 怪 / 52 遭遇`、`138→142` 的那一整行），
这个脚本只做剩下的部分，每一条都带 `assert count == 1`。
"""
import io

ROOT = 'D:/Vibe/sts-tui/'
GAP = ROOT + 'docs/sts-wiki-gap.md'
README = ROOT + 'README.md'
EVENTS = ROOT + 'docs/event-gaps.md'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


NEW_D3 = '''### D.3 遭遇：三幕的池子（§275 / §287 / §306 / §311 核对）

当前事实（`sts.roguedeck.json` 的 `EncounterTables`，数字直接读出来）：

| 幕 | 普通池 | 精英池 | Boss 池 |
|---|---|---|---|
| 1 | **17** | 3 | 3（Slime Boss / Guardian / Hexaghost） |
| 2 | **10** | 3（`gremlin_leader` / `book_of_stabbing` / `slavers`） | 3（Champ / Automaton / Collector） |
| 3 | **6** | 3（`giant_head` / `nemesis` / `reptomancer`） | 3（Time Eater / Awakened One / Donu & Deca） |

另外两处专用池：`EliteEvent`（3 条，`Dead Adventurer` 的伏击）与 `ColosseumSlavers` /
`ColosseumChampions`（各 1 条，`The Colosseum` 的两场）。

### D.3.1 Act 2：wiki 的 13 条，做了 10 条（§311）

| wiki（`The_City`） | 池 | 权重 | 状态 |
|---|---|---|---|
| Spheric Guardian | Easy | 2 | ✅ §311（新怪物） |
| Chosen | Easy | 2 | ✅ |
| Shelled Parasite | Easy | 2 | ✅ |
| 3 Byrds | Easy | 2 | ✅ §311（顺手修了 `enc_byrds` 只有 1 只的 bug） |
| 2 Thieves | Easy | 2 | ❌ 要 `mugger` |
| Chosen and Byrds | Hard | 2 | ✅ §311（1 Chosen + **1** Byrd） |
| Cultist and Chosen | Hard | 3 | ✅ §311 |
| Sentry and Spheric Guardian | Hard | 2 | ⛔ 见下面的"跨档位" |
| Snake Plant | Hard | 6 | ❌ 要 `standard.malleable` |
| Snecko | Hard | 4 | ✅ |
| Centurion and Mystic | Hard | 6 | ❌ 要"指定某一只友军"的选择器 |
| 3 Cultists | Hard | 3 | ✅ §311 |
| Shelled Parasite and Fungi | Hard | 3 | ✅ §311 |

三条缺口各缺什么（**不是"没抄"**）：

1. **`mugger`** —— 全新怪物。它和 Looter 共享 `stolen_gold` / `carryAwayStolenGold`，但它的
   招式序列在 wiki 上只有一张表（没有 Looter 那样逐步的文字规则）；照 Looter 的骨架写等于
   **发明**一条规则，所以等到能核对清楚时再做。
2. **`snake_plant`** —— 要 `standard.malleable`：受到**攻击**伤害时获得 X 块、且每次触发 X
   变大、回合开始重置。内核今天没有这条"会变的反应式状态"，是**新机制**。
3. **`centurion` + `mystic`** —— `Protect` 要给 **Mystic**（不是自己、也不是全体）挂 15 块；
   `Mystic` 的 `Heal` 要给全体敌人回 16（这条已有：`sel.allAllies` + `heal`）。前者缺
   "按定义挑一只友军"的选择器 —— `sel.allAllies` 会把 Centurion 自己也算上。

**⛔ `Sentry and Spheric Guardian` 是另一个问题**：判据 `check_ascension_health` 按**池子的
档位**钉一条 `MaxHealthAsc`（精英 A8 / 普通 A7），而一只怪物只允许**一条**。Sentry 的 wiki
数字是"38-42，**A8** 起 39-45"，它同时出现在 Act 1 的**精英**池与 Act 2 的**普通**池 —— 两条
要求不可能同时成立。要做这一条，先得让"同一只怪物跨档位"被建模（按 (monster, tier) 钉 HP）。

> ⚠️ **与 wiki 的已知偏差**：wiki 是 Easy（前两场）/ Hard（其余）两段式；我们每幕只有一个
> **带权重**的单池（`EncounterTables.Weak2` 的 `Weight` 已经是 wiki 的数字 ×5）。所以
> "前两场一定简单"这条规则没有 —— 与 Act 1 是同一条偏差。

'''


def main():
    # 1. README 的敌人行（含"少数招式的 A17/A18"那段）
    patch(README, '''* **敌人**：**50 怪 / 47 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**（wiki 是 Easy 5 + Hard 8 的分子，我们用单池近似）。''',
'''* **敌人**：**51 怪 / 52 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**、**Act 2 普通池 10 条**（wiki 的 13 条里 —— 我们**没有** Easy/Hard 的
  两段式，只用一个带权重的单池，这是与 wiki 的已知偏差）。''')

    patch(README, '''  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池只有 3 条**
  （`shelled_parasite` / `chosen` / `snecko`，wiki 是 13 种组合）—— 这是当前最大的敌人侧缺口，
  其中 3 条要新怪物（`spheric_guardian` / `snake_plant` / `centurion` + `mystic`）。''',
'''  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池 10 / 13** —— 缺
  `snake_plant`（要 `standard.malleable`）、`centurion` + `mystic`（要"指定某一只友军"的选择器）、
  `2 Thieves`（要 `mugger`）。逐条见 `docs/sts-wiki-gap.md` §D.3.1。''')

    # 2. §D.3 重写
    text = io.open(GAP, encoding='utf-8').read()
    start = text.index('### D.3 遭遇：三幕的池子（§275 / §287 / §306 核对）')
    end = text.index('### D.4 两个机制缺口：**都已关闭**（§277 提，§278–§281 关）')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(text[:start] + NEW_D3 + text[end:])

    # 3. event-gaps 的两处事实
    patch(EVENTS,
          '''| `mind_bloom` | 3 | "三选一：打一场 Boss / 复制整副牌 / 升级所有牌，代价是金币或掉血" | 大（要 `dup_deck` / `upgrade_all`，且"打一场 Boss"要运行层指定遭遇） |''',
          '''| `mind_bloom` | 3 | **wiki 的四个选项**（§311 更正：旧版这一格写错过）：① *I am War* —— 打一场第 1 幕 Boss，得稀有遗物 + 50（A15 25）金币；② *I am Awake* —— 升级所有牌 + `Mark of the Bloom`（**不能治疗**）；③ *I am Rich* —— 999 金币 + 2 张 `Normality`；④ *I am Healthy* —— 回满血 + `Doubt`；第三项按血量在 Rich / Healthy 之间换 | 大：要 `upgrade_all`、两条新诅咒、`mark_of_the_bloom`（"不能治疗"的载体）与"打一场**第 1 幕** Boss"（事件开战斗有了，**指定 Boss 池**还没有） |''')

    patch(EVENTS,
          '''| `ancient_writing` | 1 | 2 | 0 | 0 | 本移植自有（升一张牌） |''',
          '''| `ancient_writing` | 1 | 2 | 0 | 0 | **同名但不是 wiki 的那条**：我们用"升级一张牌"，wiki 的 Ancient Writing 是另一条事件（§311 记下这个命名冲突） |''')
    print('README enemy lines + D.3 + event facts updated')


main()
