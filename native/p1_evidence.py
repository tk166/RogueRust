"""修 `ui-next` 闸门证据列为空。

## 形状

`Invoke-Gate` 用 `-MustMatch` 判断"真的跑了"，但**证据列**是另一张硬编码的 pattern 表
（`'(\d+) passed'`、`'(\d+/\d+ images)'` …）。新闸门不在表里 ⇒ 闸门是绿的，证据列是空的。
这正是 §4.20 的形状：**同一个词表被两处认识就一定漂**。

## 修法

① 表里加上新闸门的证据；
② 加兜底：`MustMatch` 匹配上了却一条证据都没抓到 ⇒ 用匹配文本的首行顶上去（截断）。
   这样"证据列为空"这件事不会再悄悄发生 —— 空列本身就是上一轮闸门 24 漏掉的症状。
"""

import io
import os

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert len(t) > 15000, 'acceptance.ps1 不完整（%d 字符）' % len(t)

old = """                     '(rows=\\d+, tests=\\d+)', '(\\d+ fields)', '(exports=\\d+ mentioned=\\d+)', '(exports \\d+, runObs 19)',
                     '(\\d+/\\d+ card\\(s\\) painted)')) {"""
new = """                     '(rows=\\d+, tests=\\d+)', '(\\d+ fields)', '(exports=\\d+ mentioned=\\d+)', '(exports \\d+, runObs 19)',
                     '(\\d+/\\d+ card\\(s\\) painted)',
                     # P1 的 R3F PoC：真提交数 / 真回弹数 / 触摸与模态隔离 / 最小字号
                     '(cards=10 enemies=2 commits=\\d+ rebound=\\d+ touch=1 modal-isolation=1 minTitle=\\d+px)')) {"""
assert t.count(old) == 1, 'pattern 表锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = """  $evidence = ''
  foreach ($pat in @("""
new = """  $evidence = ''
  $matchLine = ''
  if ($MustMatch -and ($out -match $MustMatch)) { $matchLine = $matches[0] }
  foreach ($pat in @("""
assert t.count(old) == 1, 'evidence 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = """    $m = [regex]::Match($out, $pat)
    if ($m.Success) { $evidence = $m.Value; break }
  }"""
new = """    $m = [regex]::Match($out, $pat)
    if ($m.Success) { $evidence = $m.Value; break }
  }
  # 兜底：MustMatch 匹配上了但表里没有对应 pattern ⇒ 用匹配文本的首行顶上。
  # **证据列为空本身就是一个症状**（上一轮闸门 24 就是这么漏的），不能让它是默认状态。
  if (-not $evidence -and $matchLine) {
    $firstLine = ($matchLine -split "`r?`n")[0]
    if ($firstLine.Length -gt 26) { $firstLine = $firstLine.Substring(0, 26) }
    $evidence = $firstLine
  }"""
assert t.count(old) == 1, 'evidence tail 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 24000, '写出后大小异常'
os.replace(temp, PATH)
print('evidence column fixed, %d bytes' % os.path.getsize(PATH))
