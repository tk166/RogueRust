"""§325 收尾：把"抽一件随机遗物"抽成一个函数，按需调用。

上一版把 `stable` 绑在"选项效果里出现 `GainRandomRelic`"这个条件上 —— 而 `dead_adventurer`
的 `Search` 选项本身是 `nothing`，`relic_random` 在**分支目标的进入效果**里。于是进入那一趟
没有可取的值，我加的那句守卫把它变成了一个响亮失败（好在是响亮的：屏幕上会是"点了没反应"）。

修法：`pick_event_relic(session)` 一个函数，两处都调；仍然是**一次事件只抽一次**。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(WASM, encoding='utf-8').read()

# ① 辅助函数：放在 `event_choice` 之前（同一个模块作用域）。
t = sub(t, """fn event_choice(slot: i32) -> Option<rd_core::content::EventOption<'static>> {""",
        """/// §285/§325：抽一件"随机遗物"，并把 id 借成 `'static`。
///
/// 池子在**内容**里（运行层没有遗物池），抽样走 `pick_relic`：按稀有度权重、跳过已持有的 ——
/// 与宝箱/精英同一套。事件里 `relic_random` 可能出现两次（选项效果一次、分支目标的进入效果
/// 一次），两次必须给**同一件**，所以调用方负责只在第一次调用它。
fn pick_event_relic(
    session: &mut RunSession,
) -> Result<&'static str, std::string::String> {
    let relics = relic_pool(content());
    let picked = session
        .state
        .pick_relic(rd_run::streams::RunStream::Event, &relics)
        .map_err(|error| describe(&error))?;
    relics
        .iter()
        .find(|entry| entry.id == picked.as_str())
        .map(|entry| entry.id)
        .ok_or_else(|| {
            if picked.as_str().is_empty() {
                std::string::String::from("没有可给的遗物（池子空或全已持有）")
            } else {
                std::string::String::from("抽到的遗物不在池子里")
            }
        })
}

fn event_choice(slot: i32) -> Option<rd_core::content::EventOption<'static>> {""",
        'helper fn')

# ② 原来的内联块改成调用它（少一份"抽遗物"的实现）。
t = sub(t, """        let relics = relic_pool(content());
        let picked = match session
            .state
            .pick_relic(rd_run::streams::RunStream::Event, &relics)
        {
            Ok(picked) => picked,
            Err(error) => {
                let message = describe(&error);
                return fail(session, &message);
            }
        };
        // id 必须借到 `'static`：`relics` 的元素来自镜像的字符串池（`Box::leak`）。
        let stable = relics
            .iter()
            .find(|entry| entry.id == picked.as_str())
            .map(|entry| entry.id);
        let Some(stable) = stable else {
            // 抽到了池子外的东西，或者池子里一件都没有（全持有）—— 两种都不该静默。
            if picked.as_str().is_empty() {
                return fail(session, "没有可给的遗物（池子空或全已持有）");
            }
            return fail(session, "抽到的遗物不在池子里");
        };""",
        """        let stable = match pick_event_relic(session) {
            Ok(stable) => stable,
            Err(message) => return fail(session, &message),
        };""",
        'use helper in options')

# ③ 进入效果那一趟：缺就**当场抽**（而不是报错）。
t = sub(t, """                if matches!(effect, rd_run::state::EventEffect::GainRandomRelic) {
                    let Some(stable) = random_relic else {
                        return fail(session, "进入效果要随机遗物，但这一段没有解析出的遗物");
                    };""",
        """                if matches!(effect, rd_run::state::EventEffect::GainRandomRelic) {
                    // §325：`Search` 这类选项本身是 `nothing`，`relic_random` 在**分支目标的
                    // 进入效果**里 —— 所以这里要能当场抽（同一段事件仍然只抽一次）。
                    if random_relic.is_none() {
                        match pick_event_relic(session) {
                            Ok(stable) => random_relic = Some(stable),
                            Err(message) => return fail(session, &message),
                        }
                    }
                    let Some(stable) = random_relic else {
                        return fail(session, "进入效果要随机遗物，但抽不出来");
                    };""",
        'lazy pick in entries')

io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('pick_event_relic extracted and used on both paths')
