"""§279：把 `atom_holds` 拆成"读字段" + "纯判定"，并加逐条覆盖的判据。

为什么拆：逐条的广度判据需要**每一条 kind/op 两侧都验**，而镜像里只有一条真实的
`Requires`（`relic has golden_idol`）。如果判定只能从镜像里读，那七种没被内容用到的 kind
就永远没人测 —— 而"某个 kind 永远返回 true"正是最安静的坏实现。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/run_expr.rs'

OLD_START = '''    if numeric {
        let amount = node
            .int_field("Amount")
            .map_err(|_| RequirementError::Malformed)?
            .ok_or(RequirementError::MissingAmount)?;'''

OLD_END = '''/// 数值型 kind（`Amount` 是数字，不是 id）。'''

NEW = '''    if numeric {
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
        let value = match kind {
            "gold" => facts.gold,
            "health" => facts.health,
            "max_health" => facts.health_max,
            "ascension" => i32::from(facts.ascension),
            "deck_count" => i32::try_from(facts.deck.len()).unwrap_or(i32::MAX),
            // `floor(max HP × n / 100)`，与 §278 的百分比效果**同一个取整**（两处漂了就会
            // 出现"条件说 50% 血以下、按钮出现了，但效果算出另一个数"的错位）。
            "health_percent" => percent_of(facts.health_max, amount),
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

/// 数值型 kind（`Amount` 是数字，不是 id）。'''

TESTS = r'''
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
'''

def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END, start)
    s = s[:start] + NEW + s[end + len(OLD_END):]
    # 新判据插到 tests 模块的最前面（`fn facts` 之前）
    anchor = '''    fn facts<'a>(relics: &'a [&'a str], deck: &'a [&'a str]) -> RunFacts<'a> {'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, TESTS.lstrip('\n') + '\n' + anchor)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('decide() extracted + per-kind tests')


main()
