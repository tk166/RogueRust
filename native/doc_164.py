"""Append §164 and §165 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 164. 页面上的回放：脚本成为玩家能用的东西

§163 的脚本只能从 ABI 取，`browser_test` 能用、玩家不能。这一节把它接到页面上，接法与 §161.9 的存档
**同一条纪律**：

* 脚本有**自己的**缓冲区（`MAX_SCRIPT` = 24 KiB），容量由 `rd_run_script_capacity()` 公布，
  `rd_run_script_fill()` 超了**拒**（`-2`）而不是截断 —— 一份被截断的脚本是"关于这一局的谎话"。
  借用存档那块 16 KiB 是错的：一个缓冲区一个契约。
* 一个元素一个写者：`#scriptBox` ← `setScript`，`#scriptNote` ← `scriptSay`；
  页面状态只由 `act`/`begin` 驱动。
* "战斗中不许"由**页面**判断（它知道自己处在什么模式）：一场战斗不是运行层的动作，只有它的**结果**进脚本，
  所以战中导出的脚本一定缺一段 —— 与其导出一份会分叉的脚本，不如拒绝并说明。

### 164.1 ★ 头部必须能携带**档案**，否则回档之后的续玩永远回放不了

第一版的头部是 `RDR1,seed,asc`。而**回档出来的局面不在这条时间线上**：它不是"从这个种子开局走过这些步"
的结果。于是回档之后接着打的那些步，写出来的脚本第一步就和局面矛盾。

两件事一起改：

1. `rd_run_restore_from` 成功时**清空日志**（回档 = 这条时间线的**起点**），并把头部改成
   `RDR1,A,<档案>`；
2. `rd_run_replay_from` 认两种头部：`S,seed,asc` → `rd_run_start`；`A,<档案>` → `rd_run_start(0,0)`
   要一个槽，再 `rd_run_restore_from`。

档案是 base64，不含 `,`/`;`，所以"头部一列、每条记录一列"的分列规则不用动。

⚠️ 回档之后、接着打之前导出的脚本是 **0 步** —— 那不是"通过"，是"这一局正是那份档案"。页面对 0 步
说"这一局正是头部的档案本身（0 步）"，因为「回放通过 · 0 步」读起来像某个闸门偷偷绿灯了。

### 164.2 判据：两条，都是反面的

`a_run_restored_from_an_archive_replays_from_its_archive`（`rd-wasm`）：

1. 一局走两步 → 存档 → **换一局完全不同**的（别的种子）→ 回档 → 导出：日志必须**只有头部**
   （不清理就失败）且头部是 `RDR1,A,RDA1-`；
2. 接着走两步 → 导出 → 回放 ⇒ `0`，步数全对，落到同一个种子；
3. 篡改第 2 步的哈希 ⇒ 返回 `2`，`checked == 1`。

页面侧（`browser_test`）：

* 一局走了两步之后按 **导出脚本** → 头部 `RDR1,S,43…`、步数 > 0、提示"已导出"；
* 按 **回放** → "回放通过 · N 步全部对上"，floor/seed 落回原处；
* 改掉第 2 步的哈希再按 **回放** → 提示里有"第 2 步"，`rd_run_replay_diverged() == 2`；
* 空框 ⇒ "框是空的"（不启动、不说通过）；
* 回档之后导出 → 头部 `RDR1,A,RDA1-`、**0 步**，回放通过。

### 164.3 ★ 浏览器闸门抓到的真 bug：回放没清 `in_fight`

`in_fight = false` 原来写在 `rd_run_fight_end` 里，而回放走 `replay_fight`（绕过那个导出）⇒ 回放一场
战斗之后运行层仍然"在战斗中"⇒ 玩家点"回档"被内核以「战斗中没有回档」拒掉，**而他不在战斗里**。

修法：把 `in_fight = false` 挪进 `apply_fight_outcome`（真打与回放共用的那一半）。
判据 `a_replayed_fight_does_not_leave_the_run_in_a_fight` 断言的是**页面会问的那个问题**
（`rd_run_restore_from` 被接受），不是"某个字段等于 false"。

---

## 165. 真指针点击：`dispatchEvent` 会替一个看不见的按钮说好话

之前所有页面场景都在页面里 `element.dispatchEvent(new MouseEvent("click"))`。它**完全不经过命中测试**：
被弹窗盖住的按钮、滚出视口的按钮、`pointer-events: none` 的按钮，在测试里都"点得动"。这正是页面测试
最不该瞎的那一类 bug。

`web/cdp.mjs` 新增两个真输入动作：

* `clickSelector(selector, index)`：`scrollIntoView` → 取中心 → **问 `document.elementFromPoint` 上面是谁**
  → 发 `Input.dispatchMouseEvent` 的 `mouseMoved`/`mousePressed`/`mouseReleased`。
  返回 `{ hits, coverTag, x, y }`：`hits === false` 就是"这个按钮被别的东西盖住了"。
* `typeInto(selector, text)`：真点击聚焦 + `Input.insertText`，再读回字段值（"输入框真的收到了字"）。

### 165.1 场景：一条玩家真会走的路径

`browser_test` 新增一段，全部用真指针：

1. 往 `#seedInput` 打字 → 值确实是 `777`；真点 `#newRunBtn` → 这一局的种子就是 777、`pending == 6`；
2. 祝福：`#nodePanel [data-panel-action]`（选一个祝福）→ `pending == 7` → 面板把"欠一张牌"变成一个按钮，
   点它才打开选牌弹窗 → `#modalBody [data-pick]`。**三次真点击**，中途没有任何 `evaluate` 代劳；
3. **反面判据**：用 `RD_DEBUG.showDeckPicker` 打开弹窗（弹窗本身怎么开不是被测对象），然后对**同一个**
   可达节点发真点击 —— `elementFromPoint` 命中的是 `#modalBody`，`hits === false`，floor **不动**；
   再真点 `#modalClose` → 弹窗关掉；**同一坐标、同一选择器**再点一次 → floor 变成 1。
   一次"不动"、一次"动了"，差别只在"弹窗在不在上面" —— 这就是 `dispatchEvent` 看不见的那件事；
4. 进战斗是**两次**真点击（地图节点 + 节点面板的"开打"）：只点一次会以为没进战斗，从而**悄悄跳过**
   出牌那一半（这一段第一次就这么跳过了，所以专门记下来）；
5. 真点手牌 → 能量 3 → 2；真点 `#endTurn` → 回合 2。

⚠️ 首个可达节点是不是战斗**由种子决定**，所以这一段按种子表（777…784）逐个真点开局，直到某个种子的
第一层可达节点里出现 `combat`；表用完了就如实报告"这一半没跑"。种子 777 一次就中。

### 165.2 数字

- `rd-wasm` 52 → 55（档案头回放 + 回放不留 `in_fight`），合计 800 → **802**。
- 页面导出 +3（`rd_run_script_fill/buf/capacity`），`smoke.mjs` 对账 **150** 条。
- 聚合验收 **19/19**。

### 165.3 下一节

内容版本指纹（现在内容变了只会在进战斗时以 `UnknownCard` 报错）；`in_fight` 这类"宿主字段"要不要一并进
`run_hash`（今天不进：它属于会话而不是局面 —— 但 §164.3 说明它**会被内核读到**，所以至少要有一条测试
钉住"回放之后它是干净的"）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 164." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
