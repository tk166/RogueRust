"""§325 修一个**潜伏 bug**：事件分支目标段的**进入效果**里的 `relic_random` 从来没被解析。

`rd-wasm` 只把**选中选项**效果里的 `GainRandomRelic` 换成 `GainRelic(id)`，而
`dead_adventurer.found.1.r.gn` 这一类的**进入效果**里也有 `relic_random` —— 于是它原样
交给运行层，运行层没有这条效果（它没有遗物池）⇒ `UnsupportedEventEffect`。

以前没撞上是因为内容里 Act 1 的事件池小、那个种子掷不到这条分支；§325 加了三条事件之后
掷骰换了结果，`web/map_test.mjs` 的第 8 层当场红。修法是**同一个解析**覆盖两张表
（选项效果 + 进入效果），并且只抽**一次**（同一段事件里的 `relic_random` 应当给同一件）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(WASM, encoding='utf-8').read()

# ① 把 `stable` 留到外层（进入效果那一趟要用），并记下"已经抽过"。
t = sub(t, """    if parsed[..specs.len()]
        .iter()
        .any(|(effect, _)| matches!(effect, rd_run::state::EventEffect::GainRandomRelic))
    {""",
        """    // §325：**一次事件只抽一次**。选项效果与进入效果都可能写 `relic_random`，而它们是同一段
    // 事件的同一件事 —— 各抽一次会给出两件不同的遗物（玩家只会看到两件里的一件）。
    let mut random_relic: Option<&'static str> = None;
    if parsed[..specs.len()]
        .iter()
        .any(|(effect, _)| matches!(effect, rd_run::state::EventEffect::GainRandomRelic))
    {""",
        'declare random_relic')

t = sub(t, """        for entry in parsed[..specs.len()].iter_mut() {
            if matches!(entry.0, rd_run::state::EventEffect::GainRandomRelic) {
                *entry = (rd_run::state::EventEffect::GainRelic, Some(stable));
            }
        }
    }""",
        """        random_relic = Some(stable);
        for entry in parsed[..specs.len()].iter_mut() {
            if matches!(entry.0, rd_run::state::EventEffect::GainRandomRelic) {
                *entry = (rd_run::state::EventEffect::GainRelic, Some(stable));
            }
        }
    }""",
        'remember stable')

# ② 进入效果那张表：同一件遗物（缺失时**响亮**失败，绝不静默留一条运行层不认识的效果）。
t = sub(t, """                let Some((effect, _payload)) = effect_from(spec.effect, i32::from(spec.amount))
                else {
                    return fail(session, "进入效果的词读不出来");
                };
                entry_pool[entry_count][index] = (effect, named);""",
        """                let Some((effect, _payload)) = effect_from(spec.effect, i32::from(spec.amount))
                else {
                    return fail(session, "进入效果的词读不出来");
                };
                // §325：进入效果里的 `relic_random` 与选项效果**同一件事** —— 用已经抽好的那件。
                if matches!(effect, rd_run::state::EventEffect::GainRandomRelic) {
                    let Some(stable) = random_relic else {
                        return fail(session, "进入效果要随机遗物，但这一段没有解析出的遗物");
                    };
                    entry_pool[entry_count][index] =
                        (rd_run::state::EventEffect::GainRelic, Some(stable));
                    continue;
                }
                entry_pool[entry_count][index] = (effect, named);""",
        'resolve entry relic_random')

io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('entry wow: relic_random resolved for entry effects too')
