"""§279：wasm 侧接上条件 —— 事实从 `RunState` 摊出来，`rd_run_choose` 拒绝不可选的选项。

三层各做各的：
* `rd-core::run_expr` 读内容（`Requires`）并求值，**不知道 `RunState` 长什么样**；
* `rd-wasm` 把 `RunState` 摊成 `RunFacts`（金币/HP/上限/等级/遗物 id/牌组 id）；
* `rd-run` 不知道"条件"这件事存在 —— 它只执行效果。

`rd_run_choose` 必须**自己**拒绝一个不可选的槽：页面可能还显示着上一次的快照（按钮没刷新、
或者有人直接调 ABI）。条件只在"点下去"和"画出来"两处判，判的是**同一个**函数。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ------------------------------------------------------- 事实 + 可用性
    s = patch(s, '''/// §278：打开的那一段（正文 + 按钮）。节点 id 来自**运行层**（`event_step`），不是页面猜的。''',
              '''/// §279：把局面摊成条件求值要的事实。
///
/// 为什么在这里摊而不是让 `run_expr` 拿 `&RunState`：`RunState` 住在 `rd-run`，而 `rd-run`
/// **不读内容**（§133）。条件是内容的一部分（它引用的 id 都是内容里的 id），所以"读内容"
/// 只能在有内容的那一层发生 —— 也就是这里。
fn run_facts(session: &RunSession, relics: &mut Vec<&'static str>,
             deck: &mut Vec<&'static str>) -> rd_core::run_expr::RunFacts<'static> {
    relics.clear();
    deck.clear();
    for slot in 0..session.state.relics().len() {
        // `relics()` 给的是 `&RunId`；`&str` 的生命周期跟 state 一样长（真静态由调用方的
        // `static` 会话槽保证 —— 这里只借到本次调用的栈帧，所以**不**把字符串塞进 `Vec`）。
        relics.push(session.state.relics()[slot].as_str());
    }
    for card in session.state.deck() {
        deck.push(card.as_str());
    }
    let _ = relics;
    let _ = deck;
    unreachable!("use run_facts_with_name instead")
}

/// §279：打开的那一段（正文 + 按钮）。节点 id 来自**运行层**（`event_step`），不是页面猜的。''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('placeholder written (will be replaced)')


main()
