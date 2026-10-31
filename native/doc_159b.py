"""Append §159.9 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 159.9 顺手补的守卫：池超容现在**拒绝**而不是截断

§158 删药水池的一半理由就是 `id_pool` 的 `.min(MAX_POOL_IDS)`：一条 33 项的清单会以"前 8 瓶能掉、
内容门还说 33 瓶都在"的形式上线。遭遇池/事件池走的还是那个 walker，而 `Weak` 已经是 8 格里的 7 格 ——
下一节加精英正会撞上它。

补了一条守护测试，而它**第一版不可能变红**：它数的是返回的 `[&str; MAX_POOL_IDS]` 里非空的格子，
而那个数组按构造最多 8 格 —— 于是清单里塞到 9 项它照样绿。**这是负控抓出来的**（不是读代码看出来的）。

修法是让守卫坐在**切口之前**：`id_pool` 遇到超容清单直接返回 `None`（"这个池没有了"是响亮的、
可观察的失败），测试则断言 9 个遭遇池 + 3 个事件池都 `is_some()`。负控（`Weak` 塞到 9 项）现在红，
报错原文是"`EncounterTables.Weak` is missing or holds more than 8 ids"。

顺带一条：改完 `content.rs` 之后**忘了重编 wasm**，`web-package` 当场红（"web/rd_wasm.wasm is NOT a
fresh build of this tree"，还给了 on-disk 与 fresh 两个 sha）—— 那道闸门的存在意义就是这一次。
"""

with io.open(PATH, "rb") as handle:
    raw = handle.read()
assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
text = raw.decode("utf-8")
assert "### 159.9" not in text, "already appended"
if not text.endswith("\n"):
    text += "\n"
text += SECTION
with io.open(PATH, "wb") as handle:
    handle.write(text.encode("utf-8"))
print("port-plan.md now", len(text.split("\n")), "lines")
