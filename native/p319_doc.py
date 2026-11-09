"""§319 文档 —— README / wiki-gap / event-gaps / port-plan 四处的数字与清单。

数字全部来自 `native/gap_check.py` 的 pastable 区块（events 25 (10+8+7)、镜像 179,896 /
142,956 B），**不手抄**：手抄的那一份在 §318 已经漂过一次。
"""

import io

README = 'README.md'
WIKI = 'docs/sts-wiki-gap.md'
GAPS = 'docs/event-gaps.md'
PLAN = 'docs/port-plan.md'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d occurrences' % (label, n)
    return t.replace(old, new)


# ── README ──────────────────────────────────────────────────────────────────────────
t = io.open(README, encoding='utf-8').read()
t = sub(t,
        '**21 个事件**（三幕池 10+8+6 = 24 条，跨幕复用 3 条）',
        '**22 个事件**（三幕池 10+8+7 = 25 条，跨幕复用 3 条）',
        'README event count')
t = sub(t, '编译成 179,288 B 的 `rdcf` 镜像（core 镜像 142,344 B）',
         '编译成 179,896 B 的 `rdcf` 镜像（core 镜像 142,956 B）', 'README image size')
io.open(README, 'w', encoding='utf-8', newline='\n').write(t)
print('README ok')

# ── docs/sts-wiki-gap.md ────────────────────────────────────────────────────────────
t = io.open(WIKI, encoding='utf-8').read()
t = sub(t, 'enemy actions 159 / relics 152 / potions 33 / events 24 (10+8+6) / start deck 10',
         'enemy actions 159 / relics 152 / potions 33 / events 25 (10+8+7) / start deck 10',
         'wiki-gap counts')
t = sub(t, '`24` 是三个幕的事件池之和（`10+8+6`）', '`25` 是三个幕的事件池之和（`10+8+7`）',
        'wiki-gap pool sum')
io.open(WIKI, 'w', encoding='utf-8', newline='\n').write(t)
print('wiki-gap ok')

# ── docs/event-gaps.md ──────────────────────────────────────────────────────────────
t = io.open(GAPS, encoding='utf-8').read()
t = sub(t,
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **3**（§318 补了 `Mysterious Sphere` / `Winding Halls`） | 其余 **4**：`falling` 要"按**类型**删牌"、`sensory_stone` 要"无色牌三选一"、`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |',
        '| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **4**（§318 补了 `Mysterious Sphere` / `Winding Halls`，§319 补了 `Falling`） | 其余 **3**：`sensory_stone` 要"无色牌 N 选 1"、`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |',
        'event-gaps act3 row')
t = sub(t, '| `falling` | 3 | "失去一张**能力/技能/攻击**牌"（按类型删）—— `remove_card` 有，按 tag 删没有 |',
        '| ~~`falling`~~ | 3 | **§319 已做**：`remove_card_random:<kind>`（随机删一张该类型）+ 条件原子 `card_tag`（没有该类型 ⇒ 按钮不画；三种都没有 ⇒ wiki 那条兜底 `[Land]`） |',
        'event-gaps falling row')
io.open(GAPS, 'w', encoding='utf-8', newline='\n').write(t)
print('event-gaps ok')

# ── docs/port-plan.md ───────────────────────────────────────────────────────────────
t = io.open(PLAN, encoding='utf-8').read()
assert '## §319' not in t, 'port-plan already has §319'
entry = """
## §319 `falling` —— 按**类型**随机删牌 + 选项按类型上锁

wiki 的 Falling 三个选项都是 **Lose (a random <type>)**（`[Land]` Skill / `[Channel]` Power /
`[Strike]` Attack），而且 **没有该类型的牌时那条选项根本不出现**
（*"if the player has no Powers for the [Channel] option, it is replaced with [Locked]
Requires: Power Card"*）。所以这一条需要的不是"带筛选的选牌问句"（原计划），而是两件更小的东西：

| 件 | 位置 | 形状 |
|---|---|---|
| `EventEffect::RemoveCardRandom(CardKind)` | `rd-run` | `remove_card_random:<kind>`；应用时就地掷一次 `RunStream::Event`，**没有问句**（wiki 明写 random） |
| 条件原子 `card_tag` | `rd-core::run_expr` | `{"Kind":"card_tag","Op":"has","Id":"skill"}`；数的是 `RunFacts::deck_tags`（与 `deck` 逐位对应） |

三处值得一提：

1. **类型词表只有一份**：`CardKind::wire_name` / `from_wire`。它的三个读者是
   `remove_card_random:<kind>` 的解析、`rd-wasm` 填 `deck_tags`、以及内容的 `Requires.Id`。
   `from_wire` 认不出时**返回 `None` 并让内容报错**，绝不退回 `Other` —— 否则
   `remove_card_random:powerr` 会"删一张类型未知的牌"。
2. **一个候选都没有 ⇒ `RunError::NoEligibleCard`**（新变体，不复用 `DeckEmpty`）。内容层面那条
   选项已经被 `card_tag` 藏起来了，所以走到这里说明**条件与效果对不上**，那是要响的事。
3. **兜底那一条**：wiki 的特例是"连一张合格牌都没有时只剩一个没有描述的 `[Land]`"。内容里
   第四条选项用三个 `lacks` 原子表达（`MAX_REQUIREMENTS = 4` 够用），效果是 `nothing`。

判据（`rd-run`，4 条）：

- `falling_removes_a_card_of_the_named_kind` —— 牌组里攻击/技能都有，删技能：尺寸 -1、
  `defend` 只剩 1 张、攻击**没动**。把 `kind` 忽略掉（退化成 `remove_at(0)`）会红。
- `falling_refuses_when_the_kind_is_absent` —— `RemoveCardRandom(Power)` 在没有能力牌的牌组里
  ⇒ `NoEligibleCard`，且**整个 `RunState` 相等**（"拒绝 ⇒ 一个字节都不改"）。
- `falling_is_deterministic_for_a_seed` —— 同种子两次跑出同一副牌。
- `remove_card_random_takes_a_kind_and_refuses_a_typo` —— 词表两侧：`:skill` 能解析，
  `:powerr` / `:空` 都是 `None`；裸词 `remove_card` 仍然是原来的**改牌问句**（两条路不许混）。

`rd-core` 的穷尽判据也一起吃到了新原子：`every_kind_answers_both_sides` 加了 `card_tag` 的
六对（`has`/`lacks` × 有/没有/大小写/空 id —— 空 id 是 `MissingId`，与 `relic` 同形），
`the_unknown_room_events_are_readable` 的闭词表加了 `remove_card_random:` 前缀与 22 条事件表。

**两个"内容形状"的坑**（都是响着红的，不是静默）：

- `EventTables.Events3` 的每一格必须是 `{"Id": ...}`。塞裸字符串会编译出一格
  `"falling"`，于是**整个池子读不出来**（`slot_list` 返回 `None`）—— 判据只报
  "`Events3` is missing or holds more than 24 ids"，根因在镜像里。
- 光进池子不够：`?` 房的事件入口在 **`UnknownRooms`**（`EV` 表）里，漏了那一行就是
  "84 段、83 可达"（`the_unknown_room_events_are_readable` 的孤儿段判据）。

数字：事件 **22**（三幕池 10+8+7 = 25）、`rd-core 810 / rd-run 198 / rd-wasm 162`、
镜像 179,896 / core 142,956 B。Act 3 事件 3/7 → **4/7**。
"""
t = t.rstrip('\n') + '\n' + entry
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t)
print('port-plan ok')
