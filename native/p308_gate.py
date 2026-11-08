"""§308：把字段清点加成闸门 22，并把 21 个 `[k/21]` 标签改成 `[k/22]`。

为什么值得多一道闸门（审阅报告 §8 说"不必把统计门禁继续扩"）：
这一道**不是统计**，它读的是"`RunState` 的字段表 ↔ 存档 ↔ 指纹"这三处的一致性，
也就是审阅报告 §2 那 18 个漏网字段的**根因**。没有它，下一轮再加一个字段仍然只会绿。
"""
import io
import re

PATH = 'D:/Vibe/sts-tui/tools/acceptance.ps1'


def main():
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count('/21]') == 21, text.count('/21]')
    text = re.sub(r'\[(\d+)/21\]', r'[\1/22]', text)

    anchor = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
    assert text.count(anchor) == 1

    gate = '''# 门 22：**`RunState` 的字段必须同时进存档与指纹**（§308，审阅报告 §2）。
# 为什么这句必须是一道闸门而不是一条注释：`archive.rs` 的 round-trip 判据是
# `assert_eq!(restored, run)`，看着最硬，但它的夹具曾经只设了六个字段 —— 于是 18 个新字段
# 全在默认值，"漏还原一个字段就红"这句话是假的（实测：漏 18 个，它照样绿）。
# 这一道做两件机器能做的事：穷尽读 `pub struct RunState` 的字段表，逐个要求它出现在
# `write_payload` 与 `hash.rs` 里；豁免必须写下理由，且豁免表里的字段一旦被删就红。
# 它证明的只是"点过名"（编译才证明"打得开"），但"没点名"这一半正是漏的 18 个。
Write-Output "`n[22/22] RunState 字段清点：每一个字段都进存档、都进指纹"
$results += Invoke-Gate -Name 'state-fields' -Exe $PY `
  -ArgLine ((Join-Path $ROOT 'native\check_state_fields.py') + ' --check') -Workdir $ROOT `
  -MustMatch 'STATE_FIELDS PASS' -TimeoutSec 120

''' + anchor
    text = text.replace(anchor, gate, 1)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)
    print('gate 22 added; labels renumbered')


main()
