"""§321 内核（一）：两件为 `mind_bloom` / `tomb_of_lord_red_mask` 服务的小东西。

1. `RunFacts.floor` + 条件原子 `floor`（数值型）—— wiki 的 Mind Bloom 第三个选项按**楼层**
   在 `[I am Rich]`（35–40）与 `[I am Healthy]`（41+）之间换。我们的层号是**本幕内的行号**
   （`RunState::floor` 的注释与 `EventTables` 的 `MinFloor` 同一个口径），所以内容写
   `at_most 6` / `at_least 7`（第三幕从绝对 35 层起算）。
2. `Fight: "boss"` ⇒ `3`（原来只有 `monster`=1 / `elite`=2）。Mind Bloom 的
   `[I am War]` 是"打一场**第 1 幕 Boss**"，所以档位要能表达 Boss —— 不是为了奖励文案，
   而是 `pantograph` / `slavers_collar` 这类"按战斗档位"的遗物读到的是这个数。
"""

import io
import re

EXPR = 'kernel/rd-core/src/run_expr.rs'
CONTENT = 'kernel/rd-core/src/content.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(EXPR, encoding='utf-8').read()

t = sub(t, """    /// §319：与 [`Self::deck`] **逐位对应**的类型名""",
        """    /// §321：**本幕内的层号**（`0` = 还没出发，`1..=15`）。`mind_bloom` 的第三个选项按它
    /// 在 `[I am Rich]` / `[I am Healthy]` 之间换。
    pub floor: i32,
    /// §319：与 [`Self::deck`] **逐位对应**的类型名""",
        'RunFacts floor')

t = sub(t, """    // §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自按类型上锁）。
    "card_tag",""",
        """    // §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自按类型上锁）。
    "card_tag",
    // §321：`floor` —— 本幕内的层号（`mind_bloom` 的第三个选项按它换）。
    "floor",""",
        'KINDS floor')

t = sub(t, """            "ascension" => i32::from(facts.ascension),""",
        """            "ascension" => i32::from(facts.ascension),
            // §321：层号（本幕内，`0` = 还没出发）。
            "floor" => facts.floor,""",
        'decide floor')

t = sub(t, """const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension", "card_damage"];""",
        """const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension", "card_damage", "floor"];""",
        'NUMERIC_KINDS floor')

io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(t)
print('run_expr: floor kind ok')

# 所有 `RunFacts` 字面量补 `floor`（与 §319 的 `deck_tags` 同一套做法：按行首缩进插）。
for path in (EXPR, CONTENT):
    tt = io.open(path, encoding='utf-8').read()
    pat = re.compile(r'(\n(\s+))deck_tags:')
    count = len(pat.findall(tt))
    tt, n = pat.subn(lambda m: '%sfloor: 0,%sdeck_tags:' % (m.group(1), m.group(1)), tt)
    assert n == count, '%s: %d of %d' % (path, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(tt)
    print('%s: floor added to %d literals' % (path, n))

# ── `Fight: "boss"` ⇒ 3 ────────────────────────────────────────────────────────────
t = io.open(CONTENT, encoding='utf-8').read()
t = sub(t, """                fight: match node.str_field("Fight").ok().flatten().unwrap_or("") {
                    "monster" => 1,
                    "elite" => 2,
                    _ => 0,
                },""",
        """                fight: match node.str_field("Fight").ok().flatten().unwrap_or("") {
                    "monster" => 1,
                    "elite" => 2,
                    // §321：`"boss"` —— `mind_bloom` 的 `[I am War]` 要"打一场第 1 幕 Boss"。
                    // 档位不只是文案：`pantograph` / `slavers_collar` 读的就是它。
                    "boss" => 3,
                    _ => 0,
                },""",
        'Fight boss')
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(t)
print('content.rs: Fight boss ok')
