"""§330：升档"由别的机制表达"的那几条 —— **只此一份**。

为什么要单独一个文件：这张表有两个消费者，而它们的口径必须一致：

* `native/sts_content_check.py` 的 `check_wiki_asc_levels`（`[7b]`，闸门：wiki 写了 A 档就必须有）；
* `native/audit_asc_gap.py`（人跑的审计：MISSING / MISMATCH 清单）。

§328 第一次写它时放在检查器里，紧接着审计脚本又要一份 —— "同一个词表被两处认识就一定漂"
（`FACT.md` §4.20 的原话）。所以挪到这里，两边都 import。

**每一条都必须写清"哪一档由什么机制表达"**，空理由就是拿白名单当静音开关。
"""

BY_OTHER_MEANS = {
    'darkling.nip':
        "A2 lives in the encounter's `Rolls` (`roll.nip` 9-13), not in a `ProgramAsc` row",
    'book_of_stabbing.multi_stab':
        "A18 is the `book_stab_single_bump` counter on the encounter, not a `ProgramAsc` row",
    'the_guardian.twin_slam':
        "A9/A19 are the `mode_shift_budget` counter rows on the encounter, not `ProgramAsc`",
    'louse_red.bite':
        "A2 lives in the encounter's `Rolls` (`roll.bite` 6-8), not in a `ProgramAsc` row",
    'louse_green.bite':
        "A2 lives in the encounter's `Rolls` (`roll.bite` 6-8), not in a `ProgramAsc` row",
}
