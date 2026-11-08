"""§287 任务①：条件 `card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"。

## wiki 的要求

`Wing Statue` 的 `[Destroy]`："Shown only if your deck holds a card dealing **10 or more damage
per hit**." 我们的条件词表只有"有没有这张牌"（`card has <id>`），问不了"某张牌打多少"。

## 为什么是"从程序里读"，不是"从描述里猜"

打多少写在卡的效果程序里（`node.dealDamage` 的 `const` Amount），描述文本只是它的印刷版。
所以判据读**程序**，与执行器读的是同一份数据。

* `Ir::max_hit_damage(root)`：遍历程序，取 `dealDamage` 的 `const` Amount 的**最大值**。
  `None` = 静态答不出（Amount 依赖状态、或藏在 `conditional`/`forEach*` 后面）—— 那种牌
  按 0 计，**不猜**。
* `Content::max_deck_hit_damage(deck)`：牌组里每一张查 `SEC_IDX`（`lookup_in(id, EK_CARD)`），
  取最大值。

⚠️ 与 `rd-wasm::program_damage` 的分工：那个求的是**一次动作的伤害总和**（`EACT` 预览），
这里求的是**单次命中的最大值**（条件）。两件事，两个函数；判据里有一条交叉检查
（单个 `dealDamage` 的程序：两者必须相等）。
"""
import io

IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'
CONTENT = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
EXPR = 'D:/Vibe/sts-tui/kernel/rd-core/src/run_expr.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


WALKER = '''/// §287：程序里**单次**伤害的最大值（`dealDamage` 的 `const` Amount）。
///
/// `None` = 静态答不出：Amount 不是 `const`（依赖状态），或者伤害藏在
/// `conditional` / `forEachTarget` / `forEachCardInZone` 后面 —— 那些要状态才能求值，
/// 猜一个数会让"牌组里有一张 ≥10 伤害的牌"变成一句随实现而变的话。
///
/// 与 `rd-wasm::program_damage` 的区别：那个求**一次动作的伤害总和**（给 `EACT` 预览用），
/// 这个求**单次命中的最大值**（给 `Wing Statue` 那种"per hit"的条件用）。两个问题，两个函数 ——
/// 把它们合成一个"伤害"会让其中一边悄悄变成错的。
#[must_use]
pub fn max_hit_damage(root: NodeRef<'_>) -> Option<i32> {
    let mut best = 0i32;
    if walk_max_hit(root, 0, &mut best) {
        Some(best)
    } else {
        None
    }
}

/// [`max_hit_damage`] 的深度优先遍历；`false` = "答不出"。
fn walk_max_hit(node: NodeRef<'_>, depth: usize, best: &mut i32) -> bool {
    const MAX_DEPTH: usize = 8;
    const MAX_CHILDREN: usize = 32;
    if depth > MAX_DEPTH {
        return false;
    }
    let Ok(kind) = node.kind_str() else {
        return false;
    };
    match kind {
        "node.dealDamage" => {
            let Some(amount) = node.node_field("Amount").ok().flatten() else {
                return false;
            };
            if amount.kind_str() != Ok("const") {
                return false; // 依赖状态 ⇒ 不猜
            }
            let Ok(Some(value)) = amount.int_field("Value") else {
                return false;
            };
            if value > *best {
                *best = value;
            }
            true
        }
        "node.sequence" => {
            let mut ids = [0u16; 32];
            let Ok(count) = node.term_list_field("Children", &mut ids) else {
                return false;
            };
            if count > MAX_CHILDREN {
                return false;
            }
            for id in ids.iter().take(count) {
                if !walk_max_hit(node.child(*id), depth + 1, best) {
                    return false;
                }
            }
            true
        }
        // 伤害可能藏在这三种后面 ⇒ 不静态回答。
        "node.conditional" | "node.forEachTarget" | "node.forEachCardInZone" => false,
        // 其余节点不会造成伤害（`applyStatus` / `gainBlock` / `heal` / `drawCards` …）：
        // 贡献 0，这是**确定的**，不是猜。
        _ => true,
    }
}

'''


def main():
    ir = io.open(IR, encoding='utf-8').read()
    anchor = '''/// 内容镜像 + IR 读取的入口。'''
    assert ir.count(anchor) == 1
    ir = ir.replace(anchor, WALKER + anchor)
    io.open(IR, 'w', encoding='utf-8', newline='\n').write(ir)

    c = io.open(CONTENT, encoding='utf-8').read()
    anchor = '''    /// The `?`-room event ids of one act (`port-plan.md` §133).'''
    helper = '''    /// §287：牌组里**单次**伤害的最高值（`Wing Statue` 的 `[Destroy]` 要 "10 or more per hit"）。
    ///
    /// 读的是每张牌的**效果程序**（与执行器同一份数据），不是描述文本。
    /// 静态答不出的牌按 0 计（见 [`crate::ir::max_hit_damage`]）—— 宁可少点亮一个按钮，
    /// 也不要让一条条件凭"看着像"成立。
    #[must_use]
    pub fn max_deck_hit_damage(&self, deck: &[&str]) -> i32 {
        let ir = crate::ir::Ir::new(self);
        let mut best = 0i32;
        for id in deck {
            let Some(entry) = self.lookup_in(id, EK_CARD) else {
                continue;
            };
            let Ok(root) = ir.card_program_root(entry.index) else {
                continue;
            };
            if let Some(amount) = crate::ir::max_hit_damage(root) {
                if amount > best {
                    best = amount;
                }
            }
        }
        best
    }

''' + anchor
    assert c.count(anchor) == 1
    c = c.replace(anchor, helper)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(c)

    # ── run_expr：RunFacts 多一格 + 新 kind
    e = io.open(EXPR, encoding='utf-8').read()
    e = patch(e, '''    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
}''',
'''    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
    /// §287：牌组里**单次**伤害的最高值（由调用方从卡的效果程序里读出来，
    /// 见 [`crate::content::Content::max_deck_hit_damage`]）。
    ///
    /// 为什么由调用方给：`run_expr` 只做**判定**，而"某张牌打多少"要读内容 —— 这一层
    /// 不该为了一个数字把整个内容表拖进来。
    pub max_hit_damage: i32,
}''')
    e = patch(e, '''    "relic",
    "card",
];''','''    "relic",
    "card",
    // §287：`card_damage` —— "牌组里有一张**单次** ≥ N 伤害的牌"（`Wing Statue` 的 `[Destroy]`）。
    "card_damage",
];''')
    e = patch(e, '''const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension"];''',
'''const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension", "card_damage"];''')
    e = patch(e, '''            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),''',
'''            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),
            // §287：单次最高伤害。阈值 `at_least 10` 就是 wiki 的 "10 or more damage per hit"。
            "card_damage" => facts.max_hit_damage,''')
    io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(e)
    print('§287: ir walker + content helper + run_expr kind')
    print('NEXT: 所有 RunFacts 字面量要补 max_hit_damage')


main()
