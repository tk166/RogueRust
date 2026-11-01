"""Append §169 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 169. 文档补课：README 与缺口清单，以及"抄下来的数字会腐烂"

这一节没有新功能。做的是两件遗留账：`README.md` 落后了 154 个提交（还写着 §43、9 道闸门），
`docs/sts-wiki-gap.md` 里有一半的"没有"已经做完、另一些"缺 13 瓶药水"变成 7 瓶。重写的过程中
**又抓到三处"注释里抄了计算值"**，值得单独记一笔。

### 169.1 README：交代"现在是什么样"

旧 README 描述的是一个只有 `rd-core` + 9 道闸门的仓库。现在是四个层（内核 / 运行层 / ABI + 前端 /
RL 环境）、内容编译器、20 道闸门、四条手工对拍。新 README 的每一条都能对上：

* 文件数/行数：`rd-core` 21 个源文件 55.8k 行、`rd-run` 6 个 8.8k 行、`rd-wasm` 2 个 10.2k 行；
* 内容数字取自 `manifest.json` 与 `native/sts_content_check.py` 的输出（36 条卡行 = 19 基础 + 17 `+`）；
* 20 道闸门逐个点名 + 各自的证据串；
* **能力边界照实写**：Boss 只有三只、精英池 4 个遭遇、药水 26/33、A 规则 9/20。

### 169.2 ★ 三处"注释抄了计算值"，全部已经过期

1. `rd-wasm/src/lib.rs`：`OFF_ENEMY_STATUS` 等五处尾注写着 `// 49`、`// 69`、`// 109`、`// 114`、
   `// 122` —— 全是 `MAX_ENEMY_SLOTS = 4` 时代的产物。它涨到 6 之后**表达式仍然正确，只有尾注在说谎**，
   `rd_env_observe_len()` 实际是 **148**。而"哪一格是几号"正是页面唯一关心的事。
   修法：**删掉尾注**，在块首说明守卫在哪（`smoke.mjs` 把页面声明的偏移与导出长度对起来）。
2. `web/README.md` 三处把观察向量写成"122 个 i32" —— 改成"读 `rd_env_observe_len()`，本次构建 148"。
3. `tools/acceptance.ps1` 的横幅写着 `[1/9]`…`[9/9]` 再 `[+1]`…`[+7]`，而**最后四道闸门连横幅都没有**。
   一次运行打印 20 行、标题说 9 —— 与陈旧注释同一类谎。改成连续的 `[1/20]`…`[20/20]`，四道补上横幅，
   `[+2]` 里的"5 张定长表"也改成 7（§167）。

**共性**：一个数字如果在两处存在（一处计算、一处抄写），抄写的那一处迟早是错的，而**没有闸门会红** ——
除非像 `smoke.mjs` 那样把两边对起来跑。这三处都不是"忘了更新"，是"本来就不该有第二份"。

### 169.3 缺口清单：数字交给脚本，正文只留结论

旧文档的问题不是写错，是**没法保持对**：它把"26 瓶药水""17 个状态"写进正文，而内容每加一条，
正文就旧一点，且没有任何闸门会红。

新增 `native/gap_check.py`：从内容 JSON 与代码里**重算**文档引用的每个数字并打印 ——
状态表、卡牌 tag 计数、遗物/药水/事件清单与效果词表、每幕遭遇数、Ascension 规则（含"声明了但没人读"
的检查）、闸门清单。正文改成"见脚本"，只在需要结论的地方写结论。

写这个脚本本身又踩了两个坑，都记在脚本注释里：

* 第一版用 `at_least(A_NAME)` 字面匹配判断"规则有没有被应用"，把 A7/A8/A9（经
  `enemy_health_percent(kind)` 传**变量**）和 A6（在 `rd-wasm` 里应用）报成"声明但从未读取" ——
  **度量在往"我们做得比实际少"的方向说谎**。改成扫全 kernel、按出现次数判断，并注明这是近似。
* 读 `is_declared_inert()` 的名单时，正则读到了 `matches!` 旁边**注释里的** `"empty"` 这个词，
  于是报出一个叫 "empty" 的状态。先剥 `//` 注释再提取。

### 169.4 缺口清单本身：两份来源，逐条比对

wiki 侧重新取（本次核对）：`Module:Potions/data`、`Module:Ascension`、`Keywords`、`Rest Sites`、
`Relics`、`Acts`。实现侧全部落到文件与 §号。几处被这次核对**改掉**的旧结论：

* "Ascension 没有" → **9 条已实现**，并逐条列出 20 条里哪 11 条缺、为什么缺（需要第二套招式表/伤害表）。
* "药水 20/33、差 13 瓶" → **26/33、差 7 瓶**，七瓶各自要的机制逐条点名。
* "X 费是唯一内核不许出现的 tag，内容门会拒" → §146 已删掉 `reject_x_cost_deck`，内容检查反过来要求
  印刷费用为 0。
* "0 张 `power` 牌" → 内容里有 6 条 `power` 行（`inflame` / `metallicize` / `combust` 与它们的 `+`），
  所以 Power Potion 不是"缺机制"，它已经在 26 瓶里。
* 精英池"只有 2 个遭遇" → **4 个**（第一幕两个、二三幕各一个）。
* 状态"已有 17 个" → **24 个，且没有一个是 knowingly inert**（`is_declared_inert()` 的名单是空的）。

### 169.5 数字

代码没有行为变化（单测仍 806），20/20 闸门仍全绿。文档侧：`README.md` 重写（66 → 约 150 行）、
`docs/sts-wiki-gap.md` 重写（带方法与重算脚本）、`web/README.md` 的陈旧数字改掉、
`native/gap_check.py` 新增。

### 169.6 下一节

`docs/spec/` 的 19 份规格书还没做过同样的体检：它们描述的是"冻结的语义"，但 `run-layer.md` /
`ui-plan.md` 这类会随实现漂。做法可以直接照这一节：**能重算的数字交给脚本**。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 169." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
