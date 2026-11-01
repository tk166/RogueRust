"""§165: separate "the backdrop swallows a click" from "× closes the modal".

The gate found a real interaction: a real click at the map node's coordinates lands on the modal's
**backdrop**, and the backdrop closes the modal on click (that is one of §151's three ways out). So
the close button had no layout afterwards, and the test failed about half the time -- depending on
whether the map node's centre happened to fall inside the `.modal-box` (which does nothing) or
outside it (which closes the modal).

The fix is to stop deriving one claim from the other: back(pad)drop swallowing is asserted while the
modal is open; closing is asserted from a **deliberate second open**, where the modal is definitely up.
"""
import io

PATH = "web/browser_test.mjs"

OLD = """  const covered = await page.probe("#mapbox g.node.reachable", 0);
  pointer.mapCoveredHits = covered.hits;
  pointer.mapCover = covered.coverTag || (covered.missing ? "no reachable node" : null);
  pointer.mapCovered = covered.hits === false;
  // 同一坐标、真输入：弹窗必须把它吃掉（不是"等它可点"，那会变成另一条测试）。
  if (!covered.missing && !covered.empty) await page.clickAt(covered.x, covered.y);
  await settle();
  pointer.floorWhileModalUp = await page.evaluate("ex.rd_run_observe(0)");
  pointer.pendingWhileModalUp = await page.evaluate("ex.rd_run_pending()");
  const closed = await page.clickSelector("#modalClose");
  pointer.closeHits = closed.hits;"""

NEW = """  const covered = await page.probe("#mapbox g.node.reachable", 0);
  pointer.mapCoveredHits = covered.hits;
  pointer.mapCover = covered.coverTag || (covered.missing ? "no reachable node" : null);
  pointer.mapCovered = covered.hits === false;
  // 同一坐标、真输入：弹窗必须把它吃掉（不是"等它可点"，那会变成另一条测试）。
  if (!covered.missing && !covered.empty) await page.clickAt(covered.x, covered.y);
  await settle();
  pointer.floorWhileModalUp = await page.evaluate("ex.rd_run_observe(0)");
  pointer.pendingWhileModalUp = await page.evaluate("ex.rd_run_pending()");
  // ⚠️ 这一枪可能**落在背景上**，而背景点击正是 §151 的三种出口之一 ⇒ 弹窗自己关掉。
  // 所以"关掉了吗"不能当作 × 的证据：两条判据必须从各自确定的前提出发。
  pointer.modalStillOpen = !(await page.evaluate("document.getElementById('modal').hidden"));

  // 第二条判据：重新打开一次，让弹窗处于**确定打开**的状态，再真点 ×。
  await page.evaluate("RD_DEBUG.showDeckPicker ? (RD_DEBUG.showDeckPicker('close me', function () {}), 1) : 0");
  pointer.reopened = await waitFor("!document.getElementById('modal').hidden", true);
  const closed = await page.clickSelector("#modalClose");
  pointer.closeHits = closed.hits;"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("the two claims are independent now")


if __name__ == "__main__":
    main()
