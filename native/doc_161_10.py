"""Append §161.10 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
### 161.10 回应第二份外部评审（`RougeRust_Code_Review_033eeed_cb08b96.md`）

评审声明"未独立构建、运行或复验"。所以每一条都先**在源码上核对**，核对结果决定它进不进这一节。
**五条成立（含一条 P0），两条我不同意，还有一条只同意一半。**

#### P0 —— 存档缓冲区与 WASM scratch 容量不匹配：**成立，而且我把它量出来了**

`rd_run_archive_into(ptr)` 接收任意指针、写最多 16 KiB，而页面给的是 `rd_env_scratch_buf()`
—— 一个 **1024 字节**的通用 scratch。评审说"现有短存档恰好不超过 1024 字节，不代表未来合法存档
仍然安全"。实测（新测试 `a_full_deck_archive_is_bigger_than_the_generic_scratch`）：

```text
60-card archive: 1628 bytes
```

⇒ 一个**后期牌组**的存档往 `SCRATCH` 后面写了约 600 字节，落进线性内存里紧跟着的那几个 static。
反方向同样开着：回档时页面把用户粘贴的文本也写进那 1 KiB。

修法不是"把 SCRATCH 调大"（它被所有 `*_into` 导出共用，那边的契约是"`*_len()` 说多长就多长"），
而是**让存档拥有自己的缓冲区，并把容量写进 ABI**：

| 旧的 | 新的 |
|---|---|
| `rd_run_archive_len()` + `rd_run_archive_into(ptr)` | `rd_run_archive_fill() -> 长度`（写进自己的缓冲） |
| —— | `rd_run_archive_buf() -> 地址` + `rd_run_archive_capacity() -> 16384` |
| `rd_run_restore_from(ptr, len)` 无长度上限 | 多了 `len > MAX_ARCHIVE ⇒ -3`（**强制**，不是假设） |

页面侧按**UTF-8 字节数**检查（`if (bytes.length > capacity)`），不是 `text.length` —— 评审点出的
这一条是对的：一个中文字符是 3 个字节。负控式的判据在测试里：`capacity + 1` 字节的输入被拒，
而**60 张牌的存档（1628 B > 1024 B）能存能读**。

#### P1 —— 删卡后存档 round-trip 有盲区：**成立，一个字节的错**

`remove_card` 把牌组左移、`deck_len -= 1`，**没清尾槽**；而存档只写前 `deck_len` 项 ⇒ 删过牌的局
回档后 `restored != run`。`drop_potion` 早就是对的（`self.potions[last] = EMPTY`）—— 又是"两个兄弟，
一个漏了"的形状。

修法：`remove_card` 补上 `self.deck[deck_len - 1] = EMPTY`，让 `len` 之后恒为空（与 `Bounded`
的不变式同一条）。新测试 `a_run_that_lost_a_card_still_round_trips` 先删一张牌再存档，
**在旧实现上会红**（负控已验证）。

#### P1 —— 存档合法性不能只由浏览器 UI 判断：**成立，但我第一次修错了**

我先按评审"用 `fight_active`"的方向修了一半：`rd_run_start` 清掉战斗会话，ABI 用"会话存在"判定。
结果 `archive_fill` 对**一个根本没打起来的局**返回 -2 —— 因为**页面在启动时就创建了一个战斗会话**
（`rd_env_reset`，战斗视图要有东西可画）。所以"会话存在"从来就不等于"正在打"。

评审的原话是"应在拥有权威状态的层明确表示 `Idle / Fighting / Finished`"。照做：`RunSession`
加一个 **`in_fight: bool`**，由三个真正拥有生命周期的调用维护 —— `rd_run_fight_begin` 置真，
`rd_run_fight_end` 与 `rd_run_start` 置假。存档与回档都问**这个**，页面的 `mode` 只作交互反馈。

判据按评审的完成标准写：**绕过 UI 直接调 ABI**，`rd_run_fight_begin()` 之后
`archive_fill() == -2` 且 `restore_from(...) == -2`。

#### P1 —— 选牌可能部分提交：**成立，而且负控证明它真的会搬走一张牌**

`resolve_choice` 的预校验覆盖了牌区容量与卡池容量，**没覆盖"那张牌自己的计数器表满了"** —— 而
`write_price` 发生在 `move_card` **之后**。负控（删掉预检）的报错原文就是证据：

```text
left:  hand=card_000002 … hand=card_000001 mc:filler_0=0 …
right: hand=card_000001 mc:filler_0=0 … hand=card_000002 …
```

**被拒绝的选牌把一张牌挪到了手牌尾部**，而问句还开着。修法：搬牌之前先问每张牌"还能不能再吃一个
`card_cost_delta`"（字典语义：有键就是覆盖，否则要空槽），不够就 `Full(MarkCounters)`。

#### P1/P2 —— `DiscardThenDraw` 的容量判定过于保守：**成立，而且它不是"保守"，是"错"**

先丢 `picked` 张再抽 `picked` 张，手牌最终回到原样 ⇒ 这个判据**永远不该触发**。原来的
`hand + picked > MAX ⇒ 拒绝` 会把"手牌 90、选 10 张"这种**明明做得成**的操作拒掉。已删除，
新测试 `discarding_before_drawing_does_not_need_extra_hand_room` 把手牌摆到**距上限只剩 2 格**、
选 2 张丢弃，断言它成功。

#### P1 —— 回档缺少完整的状态语义验证：**同意一半**

同意"CRC 不是合法性证明"，同意加 `validate`。**这一节没做**：它是一整套不变量（血/幕/楼层/游标/
`pending` 与房间自洽/id 是否存在），值得单独一节，而这一节已经在修 P0 与三条 P1。已列进下一节。

**不同意的一点**：`serde`。这个 crate 是 `no_std` + 零依赖，而手写 payload 的全部风险（漏字段、
尾槽、长度）现在由**一条判据**（`restore(write(run)) == run`）和一个容量测试覆盖住了；换成 serde 是
把"我控制字节"换成"我信任 derive"，并不会让"漏一个字段"更容易被发现。评审自己也说不要求立刻推翻。

#### P2 —— 切片用合成事件而不是真实指针：**同意，记为已知缺口**

`dispatchEvent(new MouseEvent("click"))` 与 `el.onclick()` 不能证明元素**可被点到**（遮挡、
`pointer-events`、命中区域）。关键路径改用 CDP `Input.dispatchMouseEvent` 值得做，但它是独立的一件。

#### 数字

- `rd-run` +3（满牌组存档尺寸 / 删牌后 round-trip / 信封）；`rd-core` +2（价格写不进去时不搬牌 /
  丢牌腾位不额外要容量）；`rd-wasm` +1（容量 + 生命周期，**绕 UI 直接调 ABI**）。
- 两条负控（临时回退 `remove_card` 的尾槽清理、删掉价格预检）都**红在预期的位置**。
- 聚合验收 **19/19**；单测 788 → **793**；导出 3 → 4（`archive_fill` / `archive_buf` /
  `archive_capacity` / `restore_from`），`smoke.mjs` 对账 **142** 条。

#### 下一节（按评审的清单，顺序照它的）

1. 回档的 `RunState::validate_invariants()`（血/幕/楼层/游标/`pending`/id 全部在提交前查）。
2. 回放：动作序列 + 每步哈希。
3. 关键路径的真实指针点击（CDP `Input.dispatchMouseEvent`）。
4. 内容版本指纹（现在只会在进战斗时以 `UnknownCard` 报错）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "### 161.10" not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
