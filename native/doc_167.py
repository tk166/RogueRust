"""Append §167 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 167. 关键表版本：`parse` 现在会问"这个内核读得懂这份文档吗"

REVIEW §六 最后一件的中间那一半（"内容指纹 + **关键表版本** + 存档/回放里的引用"）。§166 做了指纹，
这一节做表版本。

### 167.1 与 §166 是两个问题

| 问题 | 谁回答 | 拒在哪 |
|---|---|---|
| **是不是同一份**内容（加一张牌、改一句描述） | §166 的指纹 | 回档 / 回放 |
| **形状**能不能读（一行的格数、格的含义） | 本节 | `Content::parse`，一进门 |

前者必须严（内容变了旧档案就作废），后者必须**具体**（要说出是哪张表、哪个版本）。一条错误信息如果
只说"内容不同"，玩家与下次的我都不知道是"牌少了一张"还是"这张表多了一列"。

### 167.2 ★ 先修掉三处"少报"

这一节真正的发现不是"缺一个检查"，而是**同一件事被抄了三四份，其中几份已经不全**：

1. `Table::ALL` 是**五**张（漏 `Event`、`Potion`）。`for table in Table::ALL` 只是少走两圈 ——
   于是"每张表都检查过"这句话在两张上是假的，而**没有任何闸门会红**。
2. `section_stride()` 是表宽的**第二份抄写**，同样漏 `EV`/`POT`，落到 `_ => 1` ⇒ `validate()` 对这两张
   表的 `count × stride` **恒真**。
3. `tools/rdcf_verify.py` 的 `STRIDED` 也是五张 ⇒ 闸门报 "5/5 tables" —— 一句关于**残缺清单**的真话。
   `manifest.tables` 里其实一直有 `events` / `potions`。

修法都是"只留一处定义 + 加一条守卫"：

* `Table::ALL` 七张；`every_table_is_in_all` 用**穷尽 `match`** 钉住 —— 加变体不加进 `ALL`，测试编译不过。
* `section_stride()` 对七张关键表**转发**给 `Table::stride()`（`entity_row!` 的格数算出），不再手抄。
* `rdcf_verify.py` 补齐七张，并加 `assert_strided_is_complete()`：清单宽度与 `ROW_SCHEMAS` 不一致就
  退 2 并打印两边名字。**反证做过**：把清单砍回五张 ⇒ 立刻红并指出缺 `EV`/`POT`。
* 新增 `Content::tables_present()`：`ALL` 是"**内核**认识哪些表"，`tables_present()` 是"**这份镜像**
  有哪几张"。混为一谈的后果是 `content.core.rdcf`（早于 EV/POT）让 `for table in ALL { …unwrap() }` 崩，
  而且崩点看起来像"镜像坏了"。三个测试因此改用它（`seen` 也从"按位置"改成"按实体类别"）。

### 167.3 两条检查，放在 `parse` 而不是 `validate`

`parse` 现在保证"**这个内核读得懂这份文档**"：

* 头部 `schema_version`（offset 18）必须等于 `SUPPORTED_SCHEMA_VERSION`，否则
  `UnsupportedSchema { found, supported }`；
* 七张关键表里每个非空段的字节数必须**精确等于** `count × stride`，否则
  `TableShape { table, count, bytes, stride }`。

为什么在 `parse`：生产路径上**没有人调 `validate()`** —— 只有测试调。一个没人调用的检查等于一句注释。
为什么"精确相等"而不是"至少装得下"：`Content::rows` 用 `min(count, data.len() / stride)` 收尾，
行宽变宽只会**少读几行**，一句话都不说；多出来的字节同样说明行宽不是我以为的那个。

界线：这两条只看**长度**，不看格里的值 —— 所以它们不是"段内语义"，而是"能不能读"。

### 167.4 ★ 判据：第二条**不依赖版本号**

`a_key_table_with_the_wrong_row_count_is_refused_without_a_version_bump`：只把段目录里的 `count`
改一行，**`schema_version` 一个字都不动的**，然后断言 `parse` 拒、断言那个字还是 1。
判据从镜像里**读**数字（不抄 36/62），所以换镜像（sts 36 行 / core 62 行）仍然成立，并且遍历
`Table::ALL` 把每张表的 count 各加一，逐张断言。

这条是本节的核心：**版本号要靠人记得改，行宽是读得出来的事实。** 只信版本号，编译器哪天忘了 bump，
文档就被当成功读进来、读成 62 张牌。

其余：`a_schema_version_this_kernel_does_not_know_is_refused`（含"支持的那个版本必须照常通过"，
否则"永远拒绝"也能满足前半条）；`every_table_is_in_all`；`rdcf-verify` 的 7/7 与清单守卫。

⚠️ 三个探针原来**故意**写 `schema_version = 7`（`content.rs` 的小镜像、`host.rs` 的手搓镜像）：
那时 `parse` 不查这一格，于是它们顺带证明了"内核什么版本都收"。现在写 `SUPPORTED_SCHEMA_VERSION`，
"7 会被拒"搬进了它自己的测试。`validate_catches_every_structural_fault` 里 `CARD` 的 count 病例也
被 `parse` 更早接管 —— 那条臂改走**非关键表** `IDX`，两条臂都要有活着的判据，否则其中一条迟早变成
永远不执行的死代码。

### 167.5 页面上看得见

`rd_content_check()`（`0` 懂 / `-1` 读不懂 + 理由）：页面启动时问一次，读不懂就把理由写进
`#contentPin`（红字）。没有它，`content()` 里那条 `panic!` 在浏览器里是一个**没有任何理由的死按钮**
（wasm trap）。

### 167.6 ★ 闸门抓到的第三个真 bug：测试自己"派生"出来的假失败

加入 §165 的真指针点击之后，`#modalClose` 偶发"被盖住"（约一半）。dump 出来是
`[0,0,0,0]`、`modalHidden: true` —— 因为**背景点击本身就是 §151 的三种出口之一**：真点击落在
map 节点的坐标上时，可能落在 `.modal-box` 外面 ⇒ 背景被点 ⇒ 页面**正当地**关掉了弹窗。
是**测试前提错了**，不是页面错了。

修法：两条判据从各自确定的前提出发 —— "背景吞掉点击"在弹窗打开时断言，"× 能关掉"重新打开一次再断言。
顺带把 `cdp.mjs` 拆成 `probe()`（只测不点）/ `clickAt()`（**就在这个坐标**按下，不等待、不做命中测试）/
`clickSelector()`（等到真的可点再点，然后**报告最后一次探测**，被盖住仍然是 `hits:false`）；
`browser_test` 里五处固定 `settle()` 换成轮询状态的 `waitFor()`。5/5 次连跑稳定。

### 167.7 数字

- `rd-core` 649 → **652**，合计 803 → **806**。`rdcf-verify` **7/7 tables**（14 次 count×stride，
  1,274 行）。导出 +1（`rd_content_check`），`smoke.mjs` 对账 148 → **149** 条。
- 聚合验收 **19/19**；`-UnitsFloor` 803 → **806**。

### 167.8 下一节

REVIEW §六 只剩最后一件：**像素级 UI 判据**（现在整套验收里唯一还没有判据的地方 ——
`web-ui`/`web-map` 只验布局与 SVG 结构，不验"看起来对不对"）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 167." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
