"""§319 第三半 —— 第一半里 `run_expr.rs` 的**结构体**改动被那次 assert 丢掉了。

（`p319_kernel.py` 先改了 `RunFacts` 的字段、`KINDS`、`decide` 的分支，然后 `impl CardKind`
的锚点少写了一行 `#[derive(...)]` 断言失败 —— 而写盘发生在后半段的循环里，循环**重新读盘**，
于是这三处改动凭空消失了，只留下"补字面量"那一半。判据当场报
`struct RunFacts has no field named deck_tags`（6 处），这就是判据的价值。）
"""

import io

RUN_EXPR = 'kernel/rd-core/src/run_expr.rs'


def main():
    t = io.open(RUN_EXPR, encoding='utf-8').read()

    if 'pub deck_tags' not in t:
        old = """    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
"""
        assert t.count(old) == 1, 'deck field'
        t = t.replace(old, old + """    /// §319：与 [`Self::deck`] **逐位对应**的类型名（`attack` / `skill` / `power` /
    /// `curse` / `status` / `other`），给条件原子 `card_tag` 用（`falling` 的三个选项
    /// 各自按类型上锁）。
    ///
    /// 为什么由调用方给：类型是**内容**的事（tag 位图 → `CardKind` 的映射在 `rd-wasm` 的
    /// `card_kind`，拼写只有 `CardKind::wire_name` 一份）。这一层只数"表里有没有"。
    pub deck_tags: &'a [&'a str],
""")

    if '"card_tag"' not in t:
        old = """    "card_damage",
];"""
        assert t.count(old) == 1, 'KINDS tail'
        t = t.replace(old, """    "card_damage",
    // §319：`card_tag` —— "牌组里有一张 <tag> 牌"（`Falling` 的三个选项各自按类型上锁）。
    "card_tag",
];""")

    if '"card_tag" => facts.deck_tags' not in t:
        old = """        "card" => facts.deck.contains(&id),
"""
        assert t.count(old) == 1, 'decide card arm'
        t = t.replace(old, old + """        // §319：按**类型**。`deck_tags` 与 `deck` 逐位对应，所以"有一张"就是"表里有"。
        "card_tag" => facts.deck_tags.contains(&id),
""")

    # `every_kind_answers_both_sides`：这条判据是"每种 kind 两侧都测"的穷尽表，
    # 新 kind 必须成对出现在里面。
    if 'let tags = ["attack", "skill", "attack", "curse"];' not in t:
        old = """        let relics = ["golden_idol"];
        let facts = RunFacts {"""
        assert t.count(old) == 1, 'every_kind head'
        t = t.replace(old, """        let relics = ["golden_idol"];
        // §319：与 `deck` 逐位对应（`strike`/`strike` 攻击、`defend` 技能、`regret` 诅咒）。
        let tags = ["attack", "skill", "attack", "curse"];
        let facts = RunFacts {""")

        old = """            deck: &deck,
            // §287：牌组里单次伤害的最高值。测试里给一个显式的数（`0` = 没有）。
            deck_tags: &[],
            max_hit_damage: 0,
        };
        // (kind, op, amount, id) —— 每一条都成对出现（成立 / 不成立）。"""
        assert t.count(old) == 1, 'every_kind facts'
        t = t.replace(old, """            deck: &deck,
            deck_tags: &tags,
            // §287：牌组里单次伤害的最高值。测试里给一个显式的数（`0` = 没有）。
            max_hit_damage: 0,
        };
        // (kind, op, amount, id) —— 每一条都成对出现（成立 / 不成立）。""")

        old = """            ("card", "lacks", 0, "strike", false),
        ];"""
        assert t.count(old) == 1, 'every_kind tail'
        t = t.replace(old, """            ("card", "lacks", 0, "strike", false),
            // §319：按**类型**。牌组里有攻击/技能/诅咒、**没有能力** —— `power` 那一对正是
            // `Falling` 的 `[Channel]` 在本内容里的处境（0 张 power 牌）。
            ("card_tag", "has", 0, "attack", true),
            ("card_tag", "has", 0, "power", false),
            ("card_tag", "lacks", 0, "power", true),
            ("card_tag", "lacks", 0, "attack", false),
            // 大小写与空名字都**不成立**（不是退回成 "any"）。
            ("card_tag", "has", 0, "Attack", false),
            ("card_tag", "has", 0, "", false),
        ];""")

    io.open(RUN_EXPR, 'w', encoding='utf-8', newline='\n').write(t)
    print('run_expr.rs patched')


main()
