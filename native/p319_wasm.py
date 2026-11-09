"""§319：`rd-wasm` 两处补丁 —— `deck_tags` 的生命周期（由调用方持有）与效果码表。

`run_facts` 原来在函数内部建 `Vec<&str>` 然后返回一个借用它的 `RunFacts`：
`E0515: cannot return value referencing local variable`。修法是把"建表"挪到调用方，
`run_facts` 只拿切片 —— 这也是它原本的形状（`relics` / `deck` 都是这样进来的）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'


def sub_once(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d occurrences' % (label, n)
    return t.replace(old, new)


t = io.open(WASM, encoding='utf-8').read()

t = sub_once(t, """fn run_facts<'a>(
    session: &'a RunSession,
    relics: &'a [&'a str],
    deck: &'a [&'a str],
) -> rd_core::run_expr::RunFacts<'a> {
    // §319：与 `deck` 逐位对应的类型名。来源是 `card_kind`（tag 位图的唯一读者）+
    // `CardKind::wire_name`（拼写的唯一一份），所以这里不再有第三份类型词表。
    let deck_tags: Vec<&str> = deck
        .iter()
        .map(|id| card_kind(content(), id).wire_name())
        .collect();
    rd_core::run_expr::RunFacts {""",
              """fn run_facts<'a>(
    session: &'a RunSession,
    relics: &'a [&'a str],
    deck: &'a [&'a str],
    // §319：与 `deck` 逐位对应的类型名（条件原子 `card_tag` 要它）。**由调用方持有** ——
    // 在这里建的 `Vec` 不能穿过返回值（`E0515`），与 `relics`/`deck` 同一条规矩。
    deck_tags: &'a [&'a str],
) -> rd_core::run_expr::RunFacts<'a> {
    rd_core::run_expr::RunFacts {""", 'run_facts signature')

t = sub_once(t, """    let deck: Vec<&str> = session.state.deck().iter().map(|id| id.as_str()).collect();
    let facts = run_facts(session, &relics, &deck);""",
              """    let deck: Vec<&str> = session.state.deck().iter().map(|id| id.as_str()).collect();
    // §319：类型名的来源只有两处 —— `card_kind`（tag 位图的唯一读者）与
    // `CardKind::wire_name`（拼写的唯一一份）。这里不再有第三份类型词表。
    let deck_tags: Vec<&str> = deck
        .iter()
        .map(|id| card_kind(content(), id).wire_name())
        .collect();
    let facts = run_facts(session, &relics, &deck, &deck_tags);""", 'option_available deck_tags')

t = sub_once(t, """        // §290：`gold_all` 与 `card:<id>` 的落点是"金币清零 / 牌组加一张"，
        // 页面上没有一条"效果码"能画它们（`-1` 与 `relic_random` 同一条规矩）。
        | EventEffect::LoseAllGold
        | EventEffect::GainCard => -1,""",
              """        // §290：`gold_all` 与 `card:<id>` 的落点是"金币清零 / 牌组加一张"，
        // 页面上没有一条"效果码"能画它们（`-1` 与 `relic_random` 同一条规矩）。
        | EventEffect::LoseAllGold
        | EventEffect::GainCard
        // §319：`remove_card_random:<kind>` 也一样 —— 类型名在**内容字符串**里（`Land` /
        // `Channel` / `Strike` 三个按钮的名字已经把它写在脸上了），枚举这边只剩下一个类。
        | EventEffect::RemoveCardRandom(_) => -1,""", 'effect_code_of')

t = sub_once(t, """        | EventEffect::GainRandomRelic
        | EventEffect::HealFull => 0,""",
              """        | EventEffect::GainRandomRelic
        // §319：类型不是"数量"。
        | EventEffect::RemoveCardRandom(_)
        | EventEffect::HealFull => 0,""", 'effect_amount')

io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm patched')
