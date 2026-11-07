"""§274 文档收尾：README 的遗物细节 → docs/sts-wiki-gap.md；README 只留统计数字。"""
import io

README = 'D:/Vibe/sts-tui/README.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'

README_OLD = '''* **遗物**：**108 / 193**（`native/audit_relic_gap.py` 的账；逐条清单在 **`docs/relic-inventory.md`**，
  由 `--write` 生成、193 行、标明"有/缺"）。数据源是 wiki 的 `Module:Relics/data`（Lua 表，离线留档）。
  效果仍是手写规则，但**"回合末/回合初"这一类已经零内核改动**（§260）：遗物只是"开战时挂一条带
  触发器的内容状态"，规则写在内容里（`orichalcum` / `mercury_hourglass` / `horn_cleat` /
  `captains_wheel` / `stone_calendar` / `cloak_clasp` / `incense_burner` / `pocketwatch`），
  还有走**标签**（`ice_cream` / `calipers`）、"数牌组"（`du_vu_doll`）与"每第 N 张某类型牌"
  （`kunai`/`shuriken`/`ornamental_fan`/`letter_opener`/`nunchaku`/`ink_bottle`/`pen_nib`）、
  "敌人死亡时"（`gremlin_horn` / `the_specimen`，后者靠新事件 `FoeDowned`）与"伤害管线数值改写"
  （`the_boot` / `torii` / `tungsten_rod`）、以及**改写别的状态幅值**（`paper_phrog` /
  `paper_krane`，靠 `PassiveModifiers.AppliesToStatusId`）与"施加易伤时附带虚弱"
  （`champion_belt`，靠 `event.statusIs`）、以及**改状态施加**（`snecko_skull` 多施一层毒、
  `ginger`/`turnip` 让虚弱/脆弱撒不上，靠两条本移植自己的管线 `StatusStacks` / `StatusImmunity`）、
  **条件修饰器**（`red_skull`："HP ≤ 50% 时 +3 力量"，靠 `PassiveModifiers.Condition` 这条布尔
  表达式）与**同侧改写**（`odd_mushroom`："你有易伤时只受 25%"，靠 `OverrideScope = Self`）。
  **内容门要求"内容里的每件遗物内核都实现"**，所以缺的 85 件不会半吊子地出现在池子里。
  ⚠️ `Blight`（无尽模式）13 件不做；`Starter`/`Boss`/`Shop`/`Event` 是不可掉落的桶。'''

README_NEW = '''* **遗物**：**115 / 193**（`native/audit_relic_gap.py` 的账，`IMPLEMENTED: … 内核不认识` 必须为 0；
  逐条清单在 `docs/relic-inventory.md`，193 行、标明"有/缺"）。
  分档、载体决策树与已实现规则清单见 **`docs/sts-wiki-gap.md` §D.2**；
  方法论见 **`docs/function_scaling_up_for_relics.md`**。'''

GAP_SECTION = '''
### D.2 遗物：**115 / 193** —— 已实现的规则与剩下的分档（§259–§274）

> 这一节原先长在 `README.md` 里。搬到这里的理由：README 只留**统计数字**，
> "某件遗物靠哪条管线成立"属于缺口/载体文档。方法论另有
> `docs/function_scaling_up_for_relics.md`。

**账**（`native/audit_relic_gap.py`，数据源 wiki 的 `Module:Relics/data`，Lua 表离线留档）：

| 桶 | 有 / 总 | 说明 |
|---|---|---|
| Common | 34 / 36 | 普通池 |
| Uncommon | 23 / 36 | 普通池 |
| Rare | 26 / 34 | 普通池 |
| Boss | 16 / 30 | 只从 Boss 奖励来 |
| Shop | 5 / 20 | 只从商人来 |
| Event | 14 / 18 | 只从事件来 |
| Starter | 4 / 4 | 开局自带 |
| Special | 0 / 2 | `circlet` 一类 |
| Blight | 0 / 13 | **无尽模式，不做** |

**效果怎么实现的**（不是"每件一个 if"，而是按载体归类）：

| 载体 | 遗物 |
|---|---|
| **零内核改动**：开战挂一条带触发器/修饰器的**内容状态**（§260） | `orichalcum` `mercury_hourglass` `horn_cleat` `captains_wheel` `stone_calendar` `cloak_clasp` `incense_burner` `pocketwatch` |
| 走**标签**（`ice_cream` / `calipers`）、"数牌组"（`du_vu_doll`）、"每第 N 张某类型牌"（§262） | `kunai` `shuriken` `ornamental_fan` `letter_opener` `nunchaku` `ink_bottle` `pen_nib` |
| "敌人死亡时"（`gremlin_horn` / `the_specimen`，后者靠新事件 `FoeDowned`）、"伤害管线数值改写" | `the_boot` `torii` `tungsten_rod` |
| **改写别的状态幅值**（`PassiveModifiers.AppliesToStatusId`）、"施加易伤时附带虚弱"（`event.statusIs`） | `paper_phrog` `paper_krane` `champion_belt` |
| **改状态施加**：多施一层毒 / 让虚弱、脆弱撒不上（本移植自己的两条管线 `StatusStacks` / `StatusImmunity`） | `snecko_skull` `ginger` `turnip` |
| **条件修饰器**（`PassiveModifiers.Condition` 布尔表达式）/ **同侧改写**（`OverrideScope = Self`） | `red_skull`（HP ≤ 50% 时 +3 力量）`odd_mushroom`（你有易伤时只受 25%） |
| **战斗类型**（`KindMask`，§269） | `preserved_insect` `pantograph` `slavers_collar` `sling_of_courage` |
| **奖励屏**（§269） | `question_card` `busted_crown` `prayer_wheel` `white_beast_statue` `black_star` |
| **加牌那一刻**（`push_card`，§270） | `omamori` `darkstone_periapt` 三个蛋 `ceramic_fish` |
| **金币 / 商店价**（`adjust_gold` / `shop_price`，§270–§273） | `bloody_idol` `ectoplasm` `maw_bank` `smiling_mask` `membership_card` `the_courier` |
| **进房间**（`begin_node`，§271） | `meal_ticket` `ssserpent_head` `ancient_tea_set` |
| **药水**（§271） | `sozu` `toy_ornithopter` |
| **`?` 房分流**（§272） | `tiny_chest` `juzu_bracelet` |
| **拾取那一刻**（`push_relic`，§274） | `old_coin` `lees_waffle` `war_paint` `whetstone` `astrolabe` `pandoras_box` `empty_cage` |
| 篝火六选项（§259） | `girya` `peace_pipe` `shovel` `dream_catcher` `coffee_dripper` `fusion_hammer` `mark_of_the_bloom` |

**内容门要求"内容里的每件遗物内核都实现"**，所以缺的那 78 件不会半吊子地出现在池子里
（`audit_relic_gap.py` 的 `IMPLEMENTED: … 内核不认识` 必须为 0）。

**剩下 78 件按"缺哪块载体"分档**（细节见方法论文档 §3 / §8）：

| 档 | 件数 | 缺什么 | 例子 |
|---|---|---|---|
| 轻资产 | ~20 | 有钩子、缺一条判断 | `face_of_cleric` `sacred_bark` `golden_eye` `wing_boots` |
| 中资产 | ~30 | 缺一个**事实/事件** | `sundial` `the_abacus`（缺 `DeckShuffled`）、`tough_bandages` `tingsha`（缺 `CardDiscarded`）、`hand_drill`（缺"打穿格挡"）、`bottled_*`（拾取时绑牌）、`gambling_chip` `singing_bowl` |
| 不做 | 13 | 无尽模式 `Blight` 桶 | `accursed` `hauntings` `muzzle` |
| 其他角色 | ~15 | `Watcher`/`Silent`/`Defect` 专属 | `pure_water` `cracked_core` `ninja_scroll` `emotion_chip` |
'''


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    g = io.open(GAP, encoding='utf-8').read()
    # 插在 D.1 之后（"### G." 之前那一节是 D.1；找它的结束点 = 下一个 "### " 标题）
    anchor = '### G. ★ 基础值偏差：§191 修掉了 8 条，剩 3 条是写明了的简化'
    assert g.count(anchor) == 1
    g = g.replace(anchor, GAP_SECTION.strip('\n') + '\n\n' + anchor)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = patch(r, README_OLD, README_NEW, 'readme relic block')
    # 全文其它数字
    r = r.replace('/ 108 遗物 /', '/ 115 遗物 /')
    r = r.replace('145,220 B 的 `rdcf` 镜像', '145,220 B 的 `rdcf` 镜像')
    r = r.replace('（主计划 §1–§273）', '（主计划 §1–§274）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('README → gap D.2 moved')


main()
