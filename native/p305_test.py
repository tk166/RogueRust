"""§305 判据：`frozen_eye` 只改**视图**。

三层：
* **rd-run**：`shows_draw_order()` 有/无遗物；
* **rd-wasm**：`rd_env_frozen_eye()` 0 → 1，而且**抽牌堆本身一个字节没动**
  （同一个 index 序列还是内核的顺序 —— 排序发生在页面，规则只允许发生在视图里）；
* **浏览器（进闸门）**：同一份状态两种视图 —— 没有遗物时列表**有序**、与内核顺序不同；
  有遗物时列表**等于**内核顺序。这条是这一轮真正要钉的：视图规则最容易"看起来对"。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
WEB = 'D:/Vibe/sts-tui/web/browser_test.mjs'

RUN_TEST = r'''
    /// §305：`frozen_eye` —— 抽牌堆视图按真实顺序显示。
    ///
    /// 两侧都要验：没有遗物时是 `false`（视图排序），有遗物时才是 `true`。只验"有遗物为真"的话，
    /// 一条永远返回 `true` 的实现也全绿 —— 而那正好等于"这件遗物不存在"。
    #[test]
    fn frozen_eye_decides_whether_the_draw_pile_is_shown_in_order() {
        let deck = ["strike", "defend"];
        let mut run = RunState::new(37, 80, 99, &deck).expect("a run");
        assert!(!run.shows_draw_order(), "no relic ⇒ the view is sorted");
        run.push_relic("frozen_eye", &[]).expect("frozen_eye");
        assert!(run.shows_draw_order(), "the relic turns the view into draw order");
    }
'''

WASM_TEST = r'''
    /// §305：`frozen_eye` —— 标志是 0/1，而**抽牌堆本身不变**。
    ///
    /// 后半句是这条判据的重点：排序若发生在内核里，"视图"就变成了状态 —— 之后任何一次
    /// `draw_cards` 都会按排序后的顺序发牌，而那是**改了规则**。所以这里逐张比对
    /// `rd_env_pile_card_id(0, i)` 在拿遗物前后的序列。
    #[test]
    fn frozen_eye_is_a_view_flag_and_never_reorders_the_pile() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(53, 80, 80, &deck);
        assert_eq!(rd_run_step(0), 0, "walk onto a node");
        assert_eq!(rd_run_fight_begin(), 0, "a fight begins");
        assert_eq!(crate::rd_env_frozen_eye(), 0, "no relic, sorted view");

        let before: Vec<std::string::String> = (0..crate::rd_env_pile_len(0))
            .map(|index| choice_option_title(0, index))
            .collect();

        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("frozen_eye", &[])
            .expect("frozen_eye");
        assert_eq!(crate::rd_env_frozen_eye(), 1, "the relic flips the flag");

        let after: Vec<std::string::String> = (0..crate::rd_env_pile_len(0))
            .map(|index| choice_option_title(0, index))
            .collect();
        assert_eq!(before, after, "the pile is not reordered by the flag");
        assert!(!before.is_empty(), "the draw pile has cards to look at");
    }
'''

BROWSER = r'''
  // (m) **§305: `frozen_eye` 是视图，不是状态。**
  // 同一份状态两种视图：没有遗物时抽牌堆面板**有序**（看得出有哪些牌、看不出顺序），
  // 有遗物时**等于**内核的顺序。两件事都要读 DOM —— 内核那侧只说明"标志是 0/1"，
  // 而"页面对标志做了什么"只有这里能钉。
  window.RD_DEBUG.startWithSeed(97, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  const litNodes = [...document.querySelectorAll("#mapbox g.node.reachable")];
  if (litNodes.length) {
    litNodes[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(40);
  }
  const fightButton = panel().querySelector("[data-panel-action]");
  if (fightButton) { fightButton.click(); await sleep(80); }
  out.eyeInFight = !document.getElementById("handPanel").hidden;

  // 内核的真顺序（页面的 `pileId(0, i)` 与它同源）。
  const kernelOrder = () => {
    const ids = [];
    for (let index = 0; index < ex.rd_env_pile_len(0); index++) {
      const len = ex.rd_env_pile_card_id_len(0, index);
      const at = ex.rd_env_scratch_buf();
      ex.rd_env_pile_card_id_into(0, index, at);
      ids.push(new TextDecoder().decode(new Uint8Array(ex.memory.buffer, at, len)));
    }
    return ids;
  };
  const shownOrder = () => {
    document.getElementById("drawBtn").onclick();
    const rows = [...document.querySelectorAll("#modalBody .card")].map((el) => text(el));
    document.getElementById("modalClose").click();
    return rows;
  };

  out.eyeFlagBefore = ex.rd_env_frozen_eye();
  out.eyeKernelBefore = kernelOrder();
  out.eyeShownBefore = shownOrder();
  // "有序"：按 id 排，与内核顺序**不同**（内核顺序是洗过的）。
  out.eyeSortedBefore = JSON.stringify(out.eyeShownBefore) ===
    JSON.stringify([...out.eyeKernelBefore].sort());
  out.eyeDiffersBefore = JSON.stringify(out.eyeShownBefore) !==
    JSON.stringify(out.eyeKernelBefore);
  out.eyeHint = /Frozen Eye/.test(text(document.getElementById("modalBody"))) ||
    true; // 提示读在关闭前，见 eyeHintText
  out.eyeGranted = window.RD_DEBUG.giveRelic("frozen_eye");
  out.eyeFlagAfter = ex.rd_env_frozen_eye();
  out.eyeKernelAfter = kernelOrder();
  out.eyeShownAfter = shownOrder();
  out.eyeMatchesAfter = JSON.stringify(out.eyeShownAfter) ===
    JSON.stringify(out.eyeKernelAfter);
  out.eyePileUnchanged = JSON.stringify(out.eyeKernelBefore) ===
    JSON.stringify(out.eyeKernelAfter);
'''

BROWSER_WANT = r'''
want(report.eyeInFight === true, "§305: the fight never started, so the draw pile was never shown");
want(report.eyeFlagBefore === 0 && report.eyeFlagAfter === 1,
  `§305: frozen_eye flag went ${report.eyeFlagBefore} -> ${report.eyeFlagAfter}`);
want(report.eyeDiffersBefore === true,
  "§305: without the relic the panel showed the kernel's draw order (it must NOT)");
want(report.eyeSortedBefore === true,
  "§305: without the relic the panel is not the sorted view");
want(report.eyeMatchesAfter === true,
  "§305: with the relic the panel must equal the kernel's draw order");
want(report.eyePileUnchanged === true,
  "§305: granting the relic reordered the draw pile itself (it is a view, not state)");
want(report.eyeShownAfter.length === report.eyeKernelAfter.length,
  `§305: the panel showed ${report.eyeShownAfter.length} of ` +
  `${report.eyeKernelAfter.length} card(s)`);
'''


def main():
    s = io.open(STATE, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s[:cut] + RUN_TEST + s[cut:])
    print('rd-run test')

    t = io.open(RUN, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t[:cut] + WASM_TEST + t[cut:])
    print('rd-wasm test')

    w = io.open(WEB, encoding='utf-8').read()
    # 场景插在 evaluate 结尾（`return out;` 之前）
    marker = '\n  return out;\n})()`);'
    assert w.count(marker) == 1, w.count(marker)
    w = w.replace(marker, BROWSER + marker)
    # 断言：插在 `console.log("BROWSER_TEST PASS");` 之前
    tail = '\nconsole.log("BROWSER_TEST PASS");'
    assert w.count(tail) == 1
    w = w.replace(tail, BROWSER_WANT + tail)
    io.open(WEB, 'w', encoding='utf-8', newline='\n').write(w)
    print('browser scenario + assertions')


main()
