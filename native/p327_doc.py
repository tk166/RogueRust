"""§327 文档：四条精英遭遇的保真度收口（内容 §173/§175 就在，这次补升档）。"""

import io

PLAN = 'docs/port-plan.md'
GAPS = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PLAN, encoding='utf-8').read()
assert '## §327' not in t
t = t.rstrip('\n') + '\n' + """
## §327 四条精英遭遇的保真度收口（Book of Stabbing / Slavers / Nemesis / Reptomancer）

⚠️ 先纠正一条**过期结论**：这四条组合遭遇在 §173/§175 就已经落地（`Elite2` = Gremlin Leader /
Book of Stabbing / Slavers，`Elite3` = Giant Head / Nemesis / Reptomancer），而且早有 8 条判据
（`the_five_elite_encounters_match_the_wiki_numbers`、`book_of_stabbing_multistab_starts_at_two_hits`、
`nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks`、
`reptomancer_switches_to_snake_strike_when_four_daggers_are_out`、
`reptomancer_spawns_two_daggers_at_a18_only`、`blue_slaver_never_rakes_twice_in_a_row_at_a17`、
`slaver_red_scrape_applies_two_vulnerable_from_a17`、`the_composed_encounters_pick_from_their_candidates`）。
"缺组合遭遇"这条说法本身是错的（§256 的判据注释里已经写过一次，这次再从文档里删干净）。

真正缺的是**升档数值**。对着 `native/wiki_asc/*.txt`（项目自己的 wiki 快照）逐条核，
Book of Stabbing（6×N → A3 7×N、21 → A3 24、A18 的 N 增量）、Nemesis（6×3 → A3 7×3、
3 Burns → A18 5 Burns）、Reptomancer（30 → A3 34、13×2 → A3 16×2、A18 召唤 2 只）
**全部对得上**。两处真偏差：

### 1. `blue_slaver` / `slaver_red` 的 HP 档位是 A7，不是 A8

wiki infobox 写的是 `| Type = Normal`，`AscHP` 落在 **A7**（"普通敌人更硬"）；
它们是**普通怪**，只是恰好也出现在 Act 2 的精英池 `Slavers` 里。项目原来的规则是
"档位按**池子**推"（普通 A7 / 精英 A8 / Boss A9），于是这两条在 `enc_slavers` 里被写成了 A8 ——
A7 那一档会少 2 点血。

修法沿用 §315 的先例（`Sentry` 是镜像案例：精英怪出现在 Act 2 的普通池里，钉 A8）：
内容改 A7 + 检查器的 `INV_ASC_HP_LEVEL` 加两条。两个独立来源核对：
wiki.gg「HP 46-50 | 48-52 | **7**」与 SlaySpireDB「Ascension 7 and up | 48–52」。

### 2. `taskmaster.scouring_whip` 的升档：A2 而不是 A3，且缺 A18

wiki 原话：*"Deals 7 damage. Adds (1 Wound; **A2: 2**; **A18: 3** Wounds) into your discard pile.
(; **A18: Gains 1 Strength**.)"* —— 内容里只有一条 **A3** 的行（值 2 Wound 是对的，档位错了），
A18 那一档整个缺失。

修法：`ProgramAsc` 改成 A2（2 Wound）与 A18（3 Wound + 自身 1 Strength）；
检查器的独立清单 `INV_ASC_VARIANTS` 同步（那份清单原来记的 `(3, …)` 抄的是**当时的内容**，
不是 wiki —— 这正是"清单只证明它自己"的形状）。

### 顺手修的一个自己的错

第一次改检查器时我加了**第三份** `INV_ASC_HP_LEVEL`，而文件里本来就有两份
（3201 的按池子那份早已被 3266 的按怪物那份遮蔽、成了死表）。删掉死表、只留一份 ——
"同一个词表被两处认识就一定漂"。

判据：`taskmaster_scouring_whip_scales_wounds_and_strength_by_ascension` 跑 **A1 / A2 / A17 / A18**
四档（阈值两侧各一次）；负控把 A2 档改回 A3 → 红在 `A2: Wounds into the discard pile`。
HP 档位的负控是**删掉检查器那两条 pin** → `asc.hp.slaver_red: pinned at A7, the wiki's AscHP row is A8`。

数字：`rd-core 812 / rd-run 214 / rd-wasm 176`、units **1202**（下限 1201 → 1202）；
四条对拍不动（`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
"""
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan §327 ok')

# gap 文档：精英池那一行本来就写着"齐了"，补一句档位说明。
g = io.open(GAPS, encoding='utf-8').read()
old = '| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了） |'
new = '| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了；§327 补了升档数值：Slaver 的 HP 档位 A7、Taskmaster 的 Whip A2/A18） |'
assert g.count(old) == 1, 'gap elite row'
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(g.replace(old, new))
print('gap doc ok')
