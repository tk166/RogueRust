"""§320 文档 —— README / wiki-gap / event-gaps / port-plan。

数字全部来自 `native/gap_check.py` 的 pastable 区块（events 27 (10+9+8)、镜像 180,936 /
core 144,004 B）。
"""

import io

README = 'README.md'
WIKI = 'docs/sts-wiki-gap.md'
GAPS = 'docs/event-gaps.md'
PLAN = 'docs/port-plan.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(README, encoding='utf-8').read()
t = sub(t, '**22 个事件**（三幕池 10+8+7 = 25 条，跨幕复用 3 条）',
        '**24 个事件**（三幕池 10+9+8 = 27 条，跨幕复用 3 条）', 'README events')
t = sub(t, '编译成 179,896 B 的 `rdcf` 镜像（core 镜像 142,956 B）',
        '编译成 180,936 B 的 `rdcf` 镜像（core 镜像 144,004 B）', 'README image')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'enemy actions 159 / relics 152 / potions 33 / events 25 (10+8+7) / start deck 10',
        'enemy actions 159 / relics 152 / potions 33 / events 27 (10+9+8) / start deck 10',
        'wiki-gap counts')
t = sub(t, '`25` 是三个幕的事件池之和（`10+8+7`）', '`27` 是三个幕的事件池之和（`10+9+8`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

t = io.open(GAPS, encoding='utf-8').read()
t = sub(t,
        '| 2（The City，13 条） | Ancient Writing / Augmenter / The Colosseum / Council of Ghosts / Cursed Tome / Forgotten Altar / The Library / Masked Bandits / The Mausoleum / The Nest / Pleading Vagrant / Old Beggar / Vampires | **5**',
        '| 2（The City，13 条） | Ancient Writing / Augmenter / The Colosseum / Council of Ghosts / Cursed Tome / Forgotten Altar / The Library / Masked Bandits / The Mausoleum / The Nest / Pleading Vagrant / Old Beggar / Vampires | **6**（§320 补了 `the_library`）',
        'gap act2 row')
t = sub(t,
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **4**（§318 补了 `Mysterious Sphere` / `Winding Halls`，§319 补了 `Falling`） | 其余 **3**：`sensory_stone` 要"候选列表 + `colorless` 过滤"（与 `the_library` 同一件原子）、`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |',
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **5**（§318 补了 `Mysterious Sphere` / `Winding Halls`，§319 补了 `Falling`，§320 补了 `Sensory Stone`） | 其余 **2**：`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |',
        'gap act3 row')
t = sub(t,
        '| `the_library` | 2 | `[Sleep]` 回 33%（A15 20%）**已有** `heal_pct`；`[Read]` 要"从 **20 张**里选 1 张" —— 需要**事件窗口的候选列表**（`Pending::EventOffer`，容量 20 + 页面列表；`PendingChoice::Offered` 是战斗内 3 张，形状不同） | 中 |',
        '| ~~`the_library`~~ | 2 | **§320 已做**：`offer_cards:<n>:<filter>`（候选列表 `Pending::EventOffer`，容量 20）+ 页面候选面板 | — |',
        'gap library row')
t = sub(t,
        '| `sensory_stone` | 3 | 三个 `[Recall]`：**1 张无色牌 / 2 张 + 5 HP / 3 张 + 10 HP** —— 同一件 `EventOffer`，外加**抽候选时按 `colorless` tag 过滤**（内容里已有 99 张该 tag 的卡，不是缺池子；缺的是"按 tag 抽候选"这一步） | 中 |',
        '| ~~`sensory_stone`~~ | 3 | **§320 已做**：`offer_cards:<n>:colorless`（`PoolCard::colorless` 由 `rd-wasm` 从 `CARD.Tags` 填）+ 段链表达"2/3 张" | — |',
        'gap stone row')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps ok')

t = io.open(PLAN, encoding='utf-8').read()
assert '## §320' not in t, 'port-plan already has §320'
entry = """
## §320 事件候选列表（`the_library` / `sensory_stone`）

两条事件要的是同一件东西：**事件窗口里摊开 `n` 张新牌，玩家取一张进牌组**。

| 事件 | 内容 |
|---|---|
| `The Library`（2 幕） | `[Sleep]` 回 33%（A15 20%）/ `[Read]` **20 选 1** |
| `Sensory Stone`（3 幕） | `[Recall]` 1 张无色 / 2 张 + 5 HP / 3 张 + 10 HP |

### 形状

| 件 | 位置 | 说明 |
|---|---|---|
| `EventEffect::OfferCards(u8, OfferFilter)` | `rd-run` | `offer_cards:<n>:<any|colorless>`；应用时从**池子**抽 `n` 张互不相同的候选（`RunStream::Event`），摊进 `event_offer` |
| `Pending::EventOffer = 9` | `rd-run` | 新的待答屏；`event_next` 复用既有尾巴，所以"三次 Recall"是内容把三段 `Next` 串起来 |
| `PoolCard::colorless` | `rd-run` | 内容事实（`CARD.Tags`），由 `rd-wasm` 填 —— `rd-run` 不读内容（§133） |
| `rd_run_event_offer_len / _id_* / _title_* / _take` | `rd-wasm` | 页面读候选、按**内核槽号**取牌 |
| `describeEventOffer` | `web/ui_panels.js` | 一行一张候选，按钮带内核槽号；张数不写死（20 与 3 走同一份代码） |

### 三条纪律

1. **候选与改牌抢同一个位置**：一条选项里既有 `offer_cards` 又有 `DeckChange` ⇒
   `TwoDeckChanges`（`pending` 只有一个），并且**整个 `RunState` 不变**。
2. **池子凑不出 `n` 张 ⇒ `PoolTooSmall`**（不是"少给几张"）。内容门也在写的时候就拦：
   `offer_cards:<n>:<filter>` 的 `n` 必须在 1..=20，且 `colorless` 池子真的够。
3. **取牌那一刻才进牌组**（`push_card`），所以三个蛋（`molten_egg` 等）在**进组时**生效 ——
   wiki："All card choices … are non-upgraded unless you have Toxic Egg, Molten Egg, or
   Frozen Egg"。

### 判据

`rd-run` 六条：候选互不相同且口径正确（无色池里抽不出有色牌）、`Any` 不筛、超额候选被拒且
状态不变、候选与改牌不能同处、**候选进存档**（含 `Pending::EventOffer`，读回来还能接着选）
且进指纹、取牌时蛋生效（`strike` → `strike+`）。
`rd-core`：事件数 22 → 24、闭词表加 `offer_cards:`。内容门：词表 + 张数上界 + 池子够不够。
页面：`ui_test.mjs` 用 20 与 3 两种快照各跑一遍（写死任一数字都会红），并验"槽号不是下标"。

三条负控各红在预期位置：面板写死 3 行 / 内核忽略过滤（无色池抽出有色牌）/ 内容写 21 张。

⚠️ **没有覆盖到的两处**（老实写在这里）：`browser_test.mjs` 里**没有**这条的 DOM 场景
（`?` 房抽到指定事件不可控，页面那条路的证据只有 `ui_test` 的纯函数 + `smoke` 的导出对账）；
`hash_golden` 仍然不含 `PendingChoice`（§320 只保证候选在规范文本里，Golden 对拍没跑到这条路径）。

数字：事件 **24**（三幕池 10+9+8 = 27）、`rd-core 810 / rd-run 204 / rd-wasm 162`、
units 1176、镜像 180,936 / core 144,004 B。Act 2 事件 5/13 → **6/13**，Act 3 4/7 → **5/7**。
"""
t = t.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan ok')
