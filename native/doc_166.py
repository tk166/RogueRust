"""Append §166 to docs/port-plan.md (UTF-8, no BOM, LF)."""
import io

PATH = "docs/port-plan.md"

SECTION = """
---

## 166. 内容版本指纹：把"这份存档/脚本属于哪份内容"变成可核对的数字

REVIEW §六 的最后一条：**"内容版本三件套：内容指纹 + 关键表版本 + 存档/回放里的引用"**。前两件在本节，
第三件（存档与脚本里的引用）在这里落地。

### 166.1 先纠正一条**旧决定**

`rd-run/src/state/archive.rs` 的文件头原来写着：

> **内容版本**。存档里只有 id：id 变了就是"这张牌不存在"，在进战斗时响亮报错（`UnknownCard`），
> 而不是在回档时假装成功。

这句话对了一半，错的正是最值钱的那一半。`UnknownCard` 确实响亮，但它：

* **迟到** —— 回档成功、玩两步、进战斗才炸；
* **只覆盖一种变化** —— id 消失了。**id 还在、数值变了**（`strike` 从 6 改成 7）会安静地变成另一局
  游戏，一句提示都没有。

所以现在 payload 里带**内容指纹**，回档时**先比对**，不同就**在这里**拒绝并说出两边的值。旧注释已按新的
事实改写，不留一句已经过时的说明。

### 166.2 指纹是什么，一处定义

`sha256(整个镜像)[0..4]`，即 `content.sts.rdcf` 的 SHA-256 前四字节，读作一个 `u32`，印成八位十六进制。
本机是 **`f39a1d78`** —— 与 `tools/contentc/packages/sts/out/build.json` 里 `images.full.sha256` 的
前八位同源，这就是判据能成立的原因（见 166.4）。

按**整个镜像**算，而不是按某几张关键表：描述文本改一个字也会让旧存档被拒。这是**故意要的假阳性** ——
"重建了内容，旧档案作废"是可接受且可解释的；反过来"某个成本悄悄改了而存档照收"是不可接受的。
这条取舍写在 `content_fingerprint()` 的注释里。

`OnceLock` 缓存：镜像 38 KB，每次进战斗重算一遍是白烧 CPU，而它在一个进程里是常量。

### 166.3 三处引用，各存**一份**

| 位置 | 形态 | 由谁校验 |
|---|---|---|
| 存档 payload | 紧跟 `VERSION` 的 varint（`VERSION` 1 → **2**） | `archive::restore(text, expected, state)` |
| 脚本头部（`S` 形态） | `RDR1,S,seed,asc,pin` | `rd_run_replay_from`，**第一条记录之前** |
| 脚本头部（`A` 形态） | 不带 pin —— 档案自己带着 | 回放调用的 `restore` |

`A` 形态**故意不带**：一份东西存两份就一定会漂（FACT §4.20）。所以"档案形态的脚本"里内容指纹只存在于
档案中，回放时由 `restore` 校验，而不是在头部再抄一遍。

`rd-run` 仍然**不认识内容**：`write(state, content, out)` / `restore(text, content, state)` 里的
`content` 是宿主给的 `i32`。层次没破，而"存档属于哪份内容"与"字节没被改过"由同一个 CRC 尾巴见证。

### 166.4 判据四条，其中两条是**反证**

1. `an_archive_from_another_content_build_is_refused_before_it_touches_anything`（`rd-run`）：
   写入 `CONTENT`，用 `CONTENT ^ 0x1` 还原 ⇒ `ContentMismatch{archive, build}`，**且整局一个字节都不改**
   （判据是"整个结构体相等"，不是"没崩"）；再用 `CONTENT` 还原 ⇒ 通过。后半条是必须的，否则
   "永远拒绝"也能让前半条绿。
2. 回放测试里加一段：头部 pin 改成 `deadbeef` ⇒ 返回 `-2`，**`replay_checked == 0`**，
   错误信息里同时出现 `deadbeef` 与本机 pin。判据是"一步都没应用"，不是"返回了非零" ——
   一个走到第 5 步才分叉的脚本也返回非零，可那时局面已经被改了一半。
3. `smoke.mjs`：`rd_content_fingerprint()` 必须等于 `build.json` 的 `images.full.sha256[0..8]`，
   **并且**磁盘上那份 `content.sts.rdcf` 的 sha256 必须等于 `build.json` 里写的那一个。
   两条都要：第一条说"wasm 是对着这份内容编的"（pin 编译进 wasm），第二条说"磁盘上的镜像没被换掉"。
4. 页面：`#contentPin` 显示 `内容 f39a1d78`，与导出脚本头部的字段一致；把头部 pin 改成 `deadbeef`
   再按回放 ⇒ 提示里有"内容版本不同"、两个值、且 `replay_checked == 0`。

**反证**（手工做过一次并记录在案）：把 `content.sts.rdcf` 中间一个字节翻转 ⇒ smoke 立即
`content.sts.rdcf does not hash to build.json's ...`；字节还原 ⇒ 绿。

### 166.5 ★ 顺手修掉的一个"度量报陈旧数字"

`rd_run_replay_checked/diverged` 原来只在**走过若干步之后**才被写。于是内容不同/解析失败这些**早退**路径
会留下上一次回放的"13 步全部对上"，页面一边报错一边显示绿灯。现在 `rd_run_replay_from` **进门先清零**。
这条是被上面第 2 条判据逼出来的（它断言 `checked == 0`，第一次跑就红了）。

### 166.6 数字

- `rd-run` 98 → **99**，合计 802 → **803**；`rd-wasm` 仍 55（新判据并进了已有的回放测试）。
- 导出 +1（`rd_content_fingerprint`），`smoke.mjs` 对账 147 → **148** 条。
- 存档 payload `VERSION` 1 → 2（多一个 varint，实测存档长度不变档位）。
- 聚合验收 **19/19**。

### 166.7 下一节

关键表版本（`关键表版本` 三件套里的第二件：`STR/STRO` 的行数或 `SEC_ORDER` 指纹不必等于镜像指纹 ——
它要回答的是"这张表能不能被这个内核读"，与"内容是不是同一份"是两件事）；像素级 UI 判据
（评审里唯一还没有判据的一项）。
"""


def main():
    with io.open(PATH, "rb") as handle:
        raw = handle.read()
    assert raw[:3] != b"\xef\xbb\xbf", "the plan is UTF-8 without BOM"
    text = raw.decode("utf-8")
    assert "## 166." not in text, "already appended"
    if not text.endswith("\n"):
        text += "\n"
    text += SECTION
    with io.open(PATH, "wb") as handle:
        handle.write(text.encode("utf-8"))
    print("port-plan.md now", len(text.split("\n")), "lines")


if __name__ == "__main__":
    main()
