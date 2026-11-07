//! §279：事件选项的**条件**（`EVND.Options[i].Requires`）。
//!
//! 为什么需要：真实 StS 的事件里有些选项**只在某种局面下出现**。`Forgotten Altar` 的第一个选项
//! 是 `[Offer: Golden Idol]`，wiki 明写"if the player does not have Golden Idol, this option is
//! replaced with `[Locked] Requires: Golden Idol`"。没有载体时，内容只能把它压成"一个按钮，
//! 点了什么也没有"，或者干脆删掉 —— 两种都不对。
//!
//! # 为什么不复用 `expr`
//!
//! 写方案时以为 `expr` 的词汇表"已经够"（金币/牌组/遗物/HP 都读得到）。**检查之后是错的**：
//! `expr` 的每一个 kind 都挂在**战斗状态**上（`currentHealth` 是某个战斗员的血、
//! `combatantZoneCount` 是战斗中的牌区、`hand.hasCardWithTag` 是手牌），而
//! `ExprContext` 拿的是 `&CombatState`。run 层没有 `CombatState`，也没有"回合"。
//! 硬塞会让 `expr` 变成一个既读战斗又读运行的两栖求值器，而那份词汇表的每一行都要重新问
//! "这个 kind 在 run 层是什么意思"。
//!
//! 所以这里是**第二份、封闭的**词汇表 —— 它读的是 [`RunFacts`]（运行层的十来个数字），
//! 与 `expr` 的共享只有"term 怎么解"这件事（`ir::NodeRef`）。
//!
//! # 形态：**一串原子**，全部成立才成立（AND）
//!
//! ```json
//! "Requires": [ {"Kind": "relic", "Op": "has", "Id": "golden_idol"} ]
//! "Requires": [ {"Kind": "gold", "Op": "at_least", "Amount": 150} ]
//! ```
//!
//! 为什么不是布尔树（`and`/`or`/`not`）：真实内容里的条件**全都是单条**（wiki 的
//! `Requires:` 行只有一句），而一棵树要一套解析器、一套求值器、一套"这张表里有但没实现"
//! 的判据。一串原子两个循环就够了，而且**闭集**意味着内容门可以逐条判。
//!
//! 缺 `or` 是**已知的表达力缺口**，不是遗漏：真出现"要么有 X 要么有 Y"的选项时再加一棵树，
//! 那时它值一次单独一节（与 §278 的 `EVND` 同一档）。

use crate::content::Content;
use crate::ir::{IrError, NodeRef, Value};

/// 条件的求值事实 —— **运行层**的数字，事件层不猜。
///
/// 每一项都是"读出来就有"的：`gold`/`health`/`health_max`/`ascension` 是标量，`relics`/`deck`
/// 是**卡片 id**的切片（不是 `RunId`，因为调用方要按 id 比，而 `RunId` 是布局）。
#[derive(Debug, Clone, Copy)]
pub struct RunFacts<'a> {
    /// 金币。
    pub gold: i32,
    /// 当前 HP。
    pub health: i32,
    /// 最大 HP。
    pub health_max: i32,
    /// Ascension 等级（0..=20）。
    pub ascension: u8,
    /// 手上的遗物 id。
    pub relics: &'a [&'a str],
    /// 牌组里的卡 id（重复的算多次：`deck_count` 数的是**张数**）。
    pub deck: &'a [&'a str],
}

/// 一个条件原子的 kind（`Requires[i].Kind`）。**闭集**，认不出的响亮失败。
const KINDS: &[&str] = &[
    "gold",
    "health",
    "max_health",
    "health_percent",
    "deck_count",
    "ascension",
    "relic",
    "card",
];

/// 数值型 kind 允许的比较（`AtLeast` = `x >= n`，`AtMost` = `x <= n`）。
const NUMERIC_OPS: &[&str] = &["at_least", "at_most"];

/// 存在型 kind 允许的比较。
const PRESENCE_OPS: &[&str] = &["has", "lacks"];

/// 求值一个条件时的错误。**每一条都是"内容或镜像坏了"，没有一条是"条件不成立"** ——
/// 不成立就是 `Ok(false)`，不是错误（否则"缺一张遗物"会被当成故障）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RequirementError {
    /// 这个选项没有 `Requires` 格（调用方不该求值它）。
    NoRequires,
    /// `Requires` 不是列表。
    NotAList,
    /// 没有 `Kind` 格。
    MissingKind,
    /// kind 不在闭集里。
    UnknownKind,
    /// 没有 `Op` 格（数值型默认 `at_least` 是**故意的**：大多数 `Requires` 是"至少 N"）。
    MissingOp,
    /// op 与 kind 不配套（`relic` 没有 `at_least`）。
    WrongOp,
    /// 数值型缺 `Amount`。
    MissingAmount,
    /// 存在型缺 `Id`。
    MissingId,
    /// `health_percent` 的百分比不在 1..=100。
    BadPercent,
    /// 原子超过 [`MAX_REQUIREMENTS`]。
    TooMany,
    /// 镜像里的 term 形状不对。
    Malformed,
}

/// A15（"事件变糟"）的阈值 —— `rd-run::state::A_EVENTS_WORSE` 的同一个数。
///
/// 为什么在 `rd-core` 里再写一份：`rd-core` 不能依赖 `rd-run`（那是运行层）。漂移由
/// `rd-wasm` 的一条判据钉住（两条常量相等），这比让 `rd-core` 认识"事件"这个概念要好。
pub const A15: u8 = 15;

/// 一条选项最多几个条件原子。
///
/// 四条是**容量**，不是规则：真实内容里每条 `Requires` 只有一句。超了报错，不截断。
pub const MAX_REQUIREMENTS: usize = 4;

/// 求值一个**选项**的全部条件（AND）。没有 `Requires` ⇒ `Ok(true)`（无条件 = 永远可选）。
///
/// `option` 是 `EVND.Options[i]` 的 term（[`crate::content::EventOption::term`]）。
pub fn option_is_available<'a>(
    content: &'a Content<'a>,
    option: u16,
    facts: &RunFacts<'_>,
) -> Result<bool, RequirementError> {
    let node = NodeRef::new(content, option);
    if node.id() == crate::content::ABSENT16 {
        return Ok(true);
    }
    // ⚠️ `Requires` 在镜像里是 **`F_TERMLIST`**（kind 5：起点 + 条数），不是 `F_TERM`
    // —— 与 §278 的 `Effects` 是同一个形状。用 `field()` 读它只会得到 `Malformed`
    // （或者更糟：把"一个节点"当成"一张列表"，于是条件永远是"无条件"）。
    // 解包交给 `term_list_field_or_empty`：它把**缺席**当空列表（绝大多数选项本来就没有条件）。
    // §280：A15 的价目常常不同（`The Cleric` 的 Purify 50 → 75），于是**条件**也要有
    // `RequiresAsc`：它只在 A15 起生效，并且**取代**基础那一串（与 `EffectsAsc` 的语义相同）。
    let key = if facts.ascension >= A15
        && node.term_list_field_or_empty("RequiresAsc", &mut [0u16; MAX_REQUIREMENTS + 1])
            .map(|count| count > 0)
            .unwrap_or(false)
    {
        "RequiresAsc"
    } else {
        "Requires"
    };
    let mut terms = [0u16; MAX_REQUIREMENTS + 1];
    let count = node
        .term_list_field_or_empty(key, &mut terms)
        .map_err(|error| match error {
            // 列表比缓冲还长 ⇒ 超容量（不是"形状坏了"）。
            IrError::List => RequirementError::TooMany,
            _ => RequirementError::Malformed,
        })?;
    if count > MAX_REQUIREMENTS {
        return Err(RequirementError::TooMany);
    }
    for term in terms.iter().take(count) {
        let atom = NodeRef::new(content, *term);
        if !atom_holds(content, atom, facts)? {
            return Ok(false);
        }
    }
    Ok(true)
}

/// 一条原子。`Kind` 必须在 [`KINDS`] 里；`Op` 必须与 kind 配套。
fn atom_holds<'a>(
    content: &'a Content<'a>,
    node: NodeRef<'a>,
    facts: &RunFacts<'_>,
) -> Result<bool, RequirementError> {
    let kind = node
        .str_field("Kind")
        .map_err(|_| RequirementError::Malformed)?
        .ok_or(RequirementError::MissingKind)?;
    if !KINDS.contains(&kind) {
        return Err(RequirementError::UnknownKind);
    }
    let numeric = NUMERIC_KINDS.contains(&kind);
    let op = node
        .str_field("Op")
        .map_err(|_| RequirementError::Malformed)?
        .unwrap_or(if numeric { "at_least" } else { "has" });
    let allowed = if numeric { NUMERIC_OPS } else { PRESENCE_OPS };
    if !allowed.contains(&op) {
        return Err(RequirementError::WrongOp);
    }
    let at_least = op == "at_least" || op == "has";

    if numeric {
        let amount = node
            .int_field("Amount")
            .map_err(|_| RequirementError::Malformed)?
            .ok_or(RequirementError::MissingAmount)?;
        return decide(kind, op, amount, "", facts);
    }

    let id = node
        .str_field("Id")
        .map_err(|_| RequirementError::Malformed)?
        .filter(|id| !id.is_empty())
        .ok_or(RequirementError::MissingId)?;
    decide(kind, op, 0, id, facts)
}

/// **纯判定**：给定 kind/op/参数与事实，条件成立吗？
///
/// 拆出来的理由写在模块头：判定是这条机制的全部**行为**，而"读字段"只是取参数。
/// 拆开之后每一条 kind/op 都能在没有镜像的情况下两侧验（见下面的 `tests`）。
pub fn decide(
    kind: &str,
    op: &str,
    amount: i32,
    id: &str,
    facts: &RunFacts<'_>,
) -> Result<bool, RequirementError> {
    if !KINDS.contains(&kind) {
        return Err(RequirementError::UnknownKind);
    }
    let numeric = NUMERIC_KINDS.contains(&kind);
    let allowed = if numeric { NUMERIC_OPS } else { PRESENCE_OPS };
    if !allowed.contains(&op) {
        return Err(RequirementError::WrongOp);
    }
    let at_least = op == "at_least" || op == "has";
    if numeric {
        // `health_percent` 是**唯一**把 Amount 当百分比读的 kind，所以它的范围要单独验：
        // 150% 的阈值永远成立（于是那条条件变成装饰），0% 永远不成立（于是那个按钮永远消失），
        // 两种都是"看起来在跑"的死内容。
        if kind == "health_percent" && !(1..=100).contains(&amount) {
            return Err(RequirementError::BadPercent);
        }
        // ⚠️ `health_percent` 不是"某个值 vs amount"：它的 amount 是**百分比**，
        // 阈值要先用最大 HP 换算成血量。第一版把它写成 `value = percent_of(max, amount)`
        // 然后拿它跟 amount 比 —— 那是在比"N% 的血"和 "N"，两个方向都错，
        // 而判据恰好只有"两侧"才能抓住这种反向（单侧永远看着对）。
        if kind == "health_percent" {
            let threshold = percent_of(facts.health_max, amount);
            return Ok(if at_least {
                facts.health >= threshold
            } else {
                facts.health <= threshold
            });
        }
        let value = match kind {
            "gold" => facts.gold,
            "health" => facts.health,
            "max_health" => facts.health_max,
            "ascension" => i32::from(facts.ascension),
            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),
            _ => return Err(RequirementError::UnknownKind),
        };
        return Ok(if at_least { value >= amount } else { value <= amount });
    }
    if id.is_empty() {
        return Err(RequirementError::MissingId);
    }
    let present = match kind {
        "relic" => facts.relics.contains(&id),
        "card" => facts.deck.contains(&id),
        _ => return Err(RequirementError::UnknownKind),
    };
    Ok(if at_least { present } else { !present })
}

/// 数值型 kind（`Amount` 是数字，不是 id）。
const NUMERIC_KINDS: &[&str] = &["gold", "health", "max_health", "health_percent", "deck_count",
                                "ascension"];

/// 与 §278 的 `percent_of` 同一个取整：`floor(base × percent / 100)`。
fn percent_of(base: i32, percent: i32) -> i32 {
    base.saturating_mul(percent) / 100
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::content::Content;

    const IMAGE: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
    );

    fn image() -> std::vec::Vec<u8> {
        std::fs::read(IMAGE).expect("the sts image")
    }

    /// `forgotten_altar` 的第一个选项 —— 唯一一条**真的在镜像里**的条件。
    fn conditional_option(content: &Content<'_>) -> u16 {
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|event| event.0) == Some("forgotten_altar"))
            .expect("forgotten_altar in the image");
        let (_, _, entry) = content.event(index).expect("the row");
        let step = content.event_step(entry).expect("its first step");
        step.options()[0].term
    }

    /// ★ 逐条广度：**每一种 kind / op 的两侧**。
    ///
    /// 为什么必须有这一条：镜像里只有一条真实的 `Requires`（`relic has golden_idol`），
    /// 而另外七种 kind 没有内容在用 —— "某个 kind 永远返回 true"在真内容上**永远不会红**。
    /// 判据用同一组事实、只换 kind/op，因此任何一个 kind 退化成常量都会在这里被两侧夹住。
    #[test]
    fn every_kind_answers_both_sides() {
        let deck = ["strike", "defend", "strike", "regret"];
        let relics = ["golden_idol"];
        let facts = RunFacts {
            gold: 100,
            health: 40,
            health_max: 80,
            ascension: 10,
            relics: &relics,
            deck: &deck,
        };
        // (kind, op, amount, id) —— 每一条都成对出现（成立 / 不成立）。
        let cases: &[(&str, &str, i32, &str, bool)] = &[
            ("gold", "at_least", 100, "", true),
            ("gold", "at_least", 101, "", false),
            ("gold", "at_most", 100, "", true),
            ("gold", "at_most", 99, "", false),
            ("health", "at_least", 40, "", true),
            ("health", "at_least", 41, "", false),
            ("max_health", "at_most", 80, "", true),
            ("max_health", "at_most", 79, "", false),
            // 40/80 = 50% ⇒ `at_most 50` 成立、`at_most 49` 不成立。
            ("health_percent", "at_most", 50, "", true),
            ("health_percent", "at_most", 49, "", false),
            // 牌组里 4 张（`strike` 两次 —— 数的是**张数**，不是"有没有"）。
            ("deck_count", "at_least", 4, "", true),
            ("deck_count", "at_least", 5, "", false),
            ("ascension", "at_least", 10, "", true),
            ("ascension", "at_least", 11, "", false),
            ("ascension", "at_most", 10, "", true),
            ("ascension", "at_most", 9, "", false),
            ("relic", "has", 0, "golden_idol", true),
            ("relic", "has", 0, "bloody_idol", false),
            ("relic", "lacks", 0, "bloody_idol", true),
            ("relic", "lacks", 0, "golden_idol", false),
            ("card", "has", 0, "strike", true),
            ("card", "has", 0, "injury", false),
            ("card", "lacks", 0, "injury", true),
            ("card", "lacks", 0, "strike", false),
        ];
        for (kind, op, amount, id, want) in cases {
            assert_eq!(
                decide(kind, op, *amount, id, &facts),
                Ok(*want),
                "{kind} {op} {amount} {id:?} -- each case must answer on both sides"
            );
        }
    }

    /// 认不出的东西**必须报错**，绝不能默认成立。
    ///
    /// "条件坏了 ⇒ 按钮全亮"比"按钮全灭"更难发现：屏幕上一片正常，取消了一条真实限制。
    #[test]
    fn unknown_kinds_and_ops_are_errors_not_defaults() {
        let facts = RunFacts {
            gold: 0,
            health: 1,
            health_max: 1,
            ascension: 0,
            relics: &[],
            deck: &[],
        };
        assert_eq!(
            decide("no_such_kind", "at_least", 1, "", &facts),
            Err(RequirementError::UnknownKind)
        );
        // op 与 kind 不配套：`relic` 没有 `at_least`。
        assert_eq!(
            decide("relic", "at_least", 1, "golden_idol", &facts),
            Err(RequirementError::WrongOp)
        );
        // 数值型 kind 配 `has`。
        assert_eq!(
            decide("gold", "has", 1, "", &facts),
            Err(RequirementError::WrongOp)
        );
        // 存在型 kind 没有 id。
        assert_eq!(
            decide("relic", "has", 0, "", &facts),
            Err(RequirementError::MissingId)
        );
        // 百分比越界：0% 永远不成立、150% 永远成立 —— 两种都是"看起来在跑"的装饰。
        for bad in [0, 101, -5] {
            assert_eq!(
                decide("health_percent", "at_least", bad, "", &facts),
                Err(RequirementError::BadPercent),
                "{bad}% must be refused"
            );
        }
    }

    fn facts<'a>(relics: &'a [&'a str], deck: &'a [&'a str]) -> RunFacts<'a> {
        RunFacts {
            gold: 0,
            health: 80,
            health_max: 80,
            ascension: 0,
            relics,
            deck,
        }
    }

    /// 镜像里的那条 `Requires`（`relic has golden_idol`）**两侧**都要对。
    #[test]
    fn the_image_carries_a_real_requirement() {
        let bytes = image();
        let content = Content::parse(&bytes).expect("parses");
        let option = conditional_option(&content);
        let with = facts(&["golden_idol"], &["strike"]);
        let without = facts(&[], &["strike"]);
        assert_eq!(option_is_available(&content, option, &with), Ok(true));
        assert_eq!(option_is_available(&content, option, &without), Ok(false));
    }

    /// 没有 `Requires` 的选项**永远可选** —— 这是"缺席 ≠ 不成立"的判据。
    ///
    /// 反过来写（缺席 ⇒ `MissingKind` 错误）会让每一条普通选项都要写 `"Requires": []`，
    /// 而"忘了写"就会变成一个**永远不出现**的按钮：屏幕正常、玩家少一条路。
    #[test]
    fn an_option_without_requires_is_always_available() {
        let bytes = image();
        let content = Content::parse(&bytes).expect("parses");
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|event| event.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, entry) = content.event(index).expect("the row");
        let step = content.event_step(entry).expect("its first step");
        for option in step.options() {
            assert_eq!(
                option_is_available(&content, option.term, &facts(&[], &[])),
                Ok(true),
                "`{}` has no Requires -- it must be offered unconditionally",
                option.label
            );
        }
        // 哨兵：`ABSENT16`（没有 term）也是"无条件"，不是错误。
        assert_eq!(
            option_is_available(&content, crate::content::ABSENT16, &facts(&[], &[])),
            Ok(true)
        );
    }
}
