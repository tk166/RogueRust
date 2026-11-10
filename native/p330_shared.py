"""§330：把白名单挪到 `native/asc_other_means.py`，两个消费者 import 同一份。

同时给 `audit_asc_gap.py` 加一类 `EXTRA`（内容有、wiki 这一行没写）—— 那是"要么我们发明的、
要么 wiki 没写全"，必须**人看**，不该混进 MISMATCH 里假装是 bug。
"""

import io

CHECKER = 'native/sts_content_check.py'
AUDIT = 'native/audit_asc_gap.py'


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


# ── 1. 检查器：删掉内联的那份，改成 import ─────────────────────────────────────
t = io.open(CHECKER, encoding='utf-8').read()
old_block = '''# §328: 升档等级**由 wiki 快照驱动**的那一份（`INV_ASC_VARIANTS` 是人抄的清单，这一份读 dump）。
#
# 键是动作 id，值是**理由**（空字符串不允许：白名单条目必须解释"哪一档由什么机制表达"）。
INV_ASC_LEVELS_BY_OTHER_MEANS = {
    'darkling.nip':
        "A2 lives in the encounter's `Rolls` (`roll.nip` 9-13), not in a `ProgramAsc` row",
    'book_of_stabbing.multi_stab':
        "A18 is the `book_stab_single_bump` counter on the encounter, not a `ProgramAsc` row",
    'the_guardian.twin_slam':
        "A9/A19 are the `mode_shift_budget` counter rows on the encounter, not `ProgramAsc`",
}'''
new_block = '''# §328: 升档等级**由 wiki 快照驱动**的那一份（`INV_ASC_VARIANTS` 是人抄的清单，这一份读 dump）。
#
# §330：白名单（"这一档由别的机制表达"）挪到 `native/asc_other_means.py` —— 因为
# `native/audit_asc_gap.py` 也要读同一张表，而"同一个词表被两处认识就一定漂"。
from asc_other_means import BY_OTHER_MEANS as INV_ASC_LEVELS_BY_OTHER_MEANS  # noqa: E402'''
t = sub(t, old_block, new_block, 'checker allowlist')
io.open(CHECKER, 'w', encoding='utf-8', newline='\n').write(t)
print('checker: allowlist imported')

# ── 2. 审计脚本：白名单 + EXTRA 分类 ──────────────────────────────────────────
a = io.open(AUDIT, encoding='utf-8').read()
a = sub(a, '''def main():
    rows = wiki_rows()''',
        '''from asc_other_means import BY_OTHER_MEANS  # noqa: E402  (§330: 与闸门 `[7b]` 同一份)


def main():
    rows = wiki_rows()''',
        'audit import')
a = sub(a, '''        if not have:
            # §330：骰子范围（`Rolls`）是**另一条载体** —— 那一档已经表达了，不是缺口。
            if set(thresholds) <= rolls.get(monster, set()):
                via_rolls.append((row['Id'], thresholds))
                continue
            missing.append((row['Id'], thresholds))
        elif sorted(have) != thresholds:
            mismatch.append((row['Id'], thresholds, sorted(have)))''',
        '''        if row['Id'] in BY_OTHER_MEANS:
            via_other.append((row['Id'], thresholds, BY_OTHER_MEANS[row['Id']]))
            continue
        if not have:
            # §330：骰子范围（`Rolls`）是**另一条载体** —— 那一档已经表达了，不是缺口。
            if set(thresholds) <= rolls.get(monster, set()):
                via_rolls.append((row['Id'], thresholds))
                continue
            missing.append((row['Id'], thresholds))
        elif sorted(have) != thresholds:
            # 内容比 wiki 这一行**多**一档 ⇒ EXTRA（人看）；少一档 ⇒ MISMATCH（真缺口）。
            if set(thresholds) <= set(have):
                extra.append((row['Id'], thresholds, sorted(have)))
            else:
                mismatch.append((row['Id'], thresholds, sorted(have)))''',
        'audit verdict')
a = sub(a, '''    missing, mismatch, extra, unresolved, via_rolls = [], [], [], [], []''',
        '''    missing, mismatch, extra, unresolved, via_rolls = [], [], [], [], []
    via_other = []''',
        'audit lists')
a = sub(a, '''    print('MISMATCH (阈值不一致): %d' % len(mismatch))''',
        '''    if via_other:
        print('VIA_OTHER_MEANS (档位由别的机制表达，见 native/asc_other_means.py): %d'
              % len(via_other))
        for action_id, thresholds, why in via_other:
            print('   %-34s wiki=%-8s %s' % (action_id, thresholds, why[:60]))
    if extra:
        print('EXTRA (内容有、wiki 这一行没写 —— 要么是我们发明的，要么 wiki 没写全): %d'
              % len(extra))
        for action_id, wiki, have in extra:
            print('   %-34s wiki=%s ours=%s' % (action_id, wiki, have))
    print('MISMATCH (阈值不一致): %d' % len(mismatch))''',
        'audit report')
io.open(AUDIT, 'w', encoding='utf-8', newline='\n').write(a)
print('audit: allowlist imported + EXTRA category')
