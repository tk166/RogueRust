"""§330 文档对账（第三半）：§H 的 Boss 差异表 + §3 建议顺序 + §4 工具清单。"""

import io

PATH = 'docs/sts-wiki-gap.md'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── §H 的六行"剩余差异"逐条重写 ───────────────────────────────────────────────
rows = [
    ("""| The Champ | 420 HP；**45/25/15/15 带权抽签** + 任何一招不能连续两次 + 每 4 回合 Taunt；≤50% 后 Anger → Execute | A19 的 "Gloat 换成 Defensive Stance" 未实现；Anger 按名清 debuff；第二阶段只做第一次 Execute |""",
     """| The Champ | 420 HP；**45/25/15/15 带权抽签** + 任何一招不能连续两次 + 每 4 回合 Taunt；≤50% 后 Anger（清三种 Debuff + 力量）→ Execute；二阶段按 **随机 / 随机 / Execute** 循环（`champ_exec` 计数器）；A19 把 Gloat 换成 Defensive Stance 且连用则回退 | **Taunt 在二阶段仍每 4 回合触发**（wiki 的 "Random Move (Same chances as Phase One)" 措辞含糊，我们按"包含 Taunt"实现） |"""),
    ("""| The Collector | 282 HP；第 1 回合 **真召唤 2 Torch Head**；70/30 带权 + 不能连 Buff + 不能三次 Fireball；第 4 回合 Mega Debuff | 25/45/30（0-1 只 Torch Head 时的权重）未分档 |""",
     """| The Collector | 282 HP；第 1 回合 **真召唤**（**up to 2**：两只都在时不加、只剩一只时补一只）；第 4 回合 Mega Debuff；两条分支的权重 **25/45/30**（0-1 只）与 **70/30**（两只都在）；不能连 Buff、不能三次 Fireball | 无（§329 收口） |"""),
    ("""| Time Eater | 456 HP；45/35/20 带权 + 三次/两次的排除规则；≤50% 的 Haste 回血一次 | Haste 不清 debuff（没有"清空状态"节点）；`Draw Reduction` 已实现但 wiki 的"A19 另加 2 Slimed"没做 |""",
     """| Time Eater | 456 HP；45/35/20 带权 + 三次/两次的排除规则；≤50% 的 Haste **回 50% 血 + 清所有 Debuff**（一次性，A19 另加 32 Block）；A19 的 Head Slam 另塞 2 张 Slimed、Ripple 另加 1 Frail | 无（§329 收口） |"""),
    ("""| Awakened One | 300 HP；`DeathPrevention` 真复活；一阶段 75/25 + Slash 不能三次；二阶段 Dark Echo 一次后 50/50；**带两只 Cultist，主人倒下时逃跑** | 二阶段"不能连续三次 Tackle/Sludge"未做（规则预算 8 条已满）；Regenerate/Curiosity 层数不随 A19 变 |""",
     """| Awakened One | 300 HP；`DeathPrevention` 真复活 → **Rebirth（回满血 + 清所有 Debuff + 失 Curiosity）**；一阶段 75/25 + Slash 不能三次；二阶段 Dark Echo 一次后 50/50 + Tackle/Sludge 不能三次；**带两只 Cultist，主人倒下时逃跑**；Regenerate/Curiosity 的 A19 层数已钉（15/2） | ⚠️ `Curiosity` 的触发器（`card.hasTag.power`）在**本内容里永不触发** —— 因为卡池 0 张 `power` 牌（§A.1 的观者缺口） |"""),
    ("""| Donu & Deca | 一对（250 HP 各 + Artifact 2）；Donu 交替 Circle / Beam；Deca 交替 Beam / Square | Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） |""",
     """| Donu & Deca | 一对（250 HP 各 + Artifact 2，**A19 变 3**）；Donu 交替 Circle / Beam；Deca 交替 Beam / Square | 无 |"""),
    ("""| Bronze Automaton | 300 HP + Artifact 3；第 1 回合 **真召唤 2 Orb**（`Spawn: false`）；6 招循环；A19 用 Boost 顶替 Stunned | Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 |""",
     """| Bronze Automaton | 300 HP + Artifact 3；第 1 回合 **真召唤 2 Orb**（`Spawn: false`）；6 招循环；A19 用 Boost 顶替 Stunned；Orb 的 `Stasis` 按"最高稀有度"抓牌 | 无 |"""),
]
for old, new in rows:
    t = sub(t, old, new, old[:40])

# §H 的引言也要改：这张表现在几乎全空。
t = sub(t, """数字全部来自 `native/wiki_asc/<boss>.txt`（`action=raw`）。这一张表**只写现在的差异**，
历史降级（"Guardian 只按 HP 切形态""Awakened One 没有死亡拦截 / 没有 Cultist""Bronze Orb 没有
Stasis""小兵预置"）已在 §195.1–§195.8 逐条修掉，过程见 `port-plan.md` 那几节。""",
        """数字全部来自 `native/wiki_asc/<boss>.txt`（`action=raw`）。这一张表**只写现在的差异** ——
§328–§330 逐条对过之后，"剩余差异"那一列基本是空的（这就是它该有的样子）。

历史降级（"Guardian 只按 HP 切形态""Awakened One 没有死亡拦截 / 没有 Cultist""Bronze Orb 没有
Stasis""小兵预置""Collector 死光后不再召唤""Champ 二阶段每回合 Execute"）都在
§195.1–§195.8 与 §329–§330 逐条修掉了，过程见 `port-plan.md` 那几节。""",
        'section H intro')

# ── §3 建议顺序：清掉已完成项 ─────────────────────────────────────────────────
old_5 = """5. **篝火选项**（运行层 + 内容，§233 之后的第一件事）：`Lift` / `Toke` / `Dig` + 开它们的
   `girya` / `peace_pipe` / `shovel` 三件遗物，外加 `coffee_dripper` / `fusion_hammer` /
   `dream_catcher` 三个"关闭/追加选项"的遗物。**`Recall` 与红钥匙**属于第四幕，跟着第 7 条。
   *成本*：`toke`/`dig` 是既有能力的复用（删牌、抽遗物），`lift` 要多一条"每场战斗开始加力量"的
   跨层传递 —— 那是这个包里唯一的新东西。"""
new_5 = """5. ~~**篝火选项**~~ ✅ **已完成**（§259：六个选项全通 + `Dream Catcher`）。**`Recall` 与红钥匙**
   本身也做了，缺的是第四幕（第 7 条）。"""
t = sub(t, old_5, new_5, 'order 5')

old_6 = """6. **卡池规模**（§A.1 的 35 张红卡 + 31 张商店无色牌）—— 纯量，不阻塞机制；**不要**当 P1
   （见审阅报告 §10.4 的反对意见）。但**无色货架**（商店里那一排）是内核的小改动 + 那 31 张的内容，
   可以整批做。"""
new_6 = """6. **卡池规模**：红卡与无色都**齐了**（`audit_card_gap.py`：Red 75/75、Colorless 70/70），
   剩下的 **73 张全是观者**（§A.1），它们成堆挂在姿态 / Mantra / Scry / Retain / `Alpha`→`Omega` 上，
   所以下一批要按**基建**聚类做。**无色货架**（商店里那一排）仍然没有 —— 那是内核的小改动
   （`stock_shop` 加一排），内容侧已经就绪。"""
t = sub(t, old_6, new_6, 'order 6')

# ── §4 工具清单：补两道新闸门与 §330 的修复 ──────────────────────────────────
t = sub(t, """* 数字：`python -X utf8 native/gap_check.py`（内容/规则）与
  `python -X utf8 native/sts_content_check.py`（内容自洽）。""",
        """* 数字：`python -X utf8 native/gap_check.py`（内容/规则）与
  `python -X utf8 native/sts_content_check.py`（内容自洽）。
* **新增的两道闸门**（都在 `sts_content_check.py` 里，验收时自动跑）：
  * `[7b]`（§328）：读 `native/wiki_asc/*.txt` 的意图行，要求内容的 `ProgramAsc` **覆盖** wiki 的
    `{{Asc|N|` —— "别的机制表达"的那几条走 `native/asc_other_means.py`（**只此一份**，审计脚本也读它）；
  * `[7g]`（§330）：**段内 id 不许重复**。它是被一条真 bug 逼出来的：`Relics` 里
    `mutagenic_strength` 重复了一行，22 道闸门一条都没红（`SEC_IDX` 照样索引得到、audit 用 `set`
    自动吃掉重复），只有把 `gap_check` 的 153 与 audit 的 152 放在一起读才看得出来。
* **工具自身也会说谎**（§330）：`audit_asc_gap.py` 的 `ROW` 正则非贪婪，遇到 `{{Asc|2|4}}` 的 `}}`
  就截断，于是每行只读到第一个档位 —— 它报了 18 条假 MISMATCH / 3 条假 MISSING。修好之后
  MISSING/MISMATCH 都是 0。**改工具时先问"它凭什么知道"**，别拿它的输出当证据。""",
        'tools list')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gap doc part 2 updated')
