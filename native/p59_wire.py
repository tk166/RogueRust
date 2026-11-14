"""接闸门 58（mechanics-audit）。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert 'mechanics-audit' not in t, '闸门 58 已经接过了'

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1

BLOCK = '''Write-Output "`n[58/58] 机制审计（§410）：状态期限 / 意图规则 / 意图种类 / 触发器事件"
# 玩家说"数量众多一个个试不现实" —— 这一轮踩过的四类 bug 变成可重跑的静态扫描：
# A 状态该过期却永不过期、B 意图规则的条件永远为真（Guardian 卡防御态）、
# C 意图种类与节目不一致（Deca 打 10x2 却标"减益"）、A3 触发器事件内核从不派发。
# 行为层面的两条（怪物不卡死 / 拾取遗物兑现）在 rust-units 的 wasm 测试里。
$results += Invoke-Gate -Name 'mechanics-audit' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'native\\audit_mechanics.py') -Workdir $ROOT `
  -MustMatch 'MECHANICS_AUDIT PASS' `
  -TimeoutSec 300

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/58]' % match.group(1)


t = re.sub(r'(\[\d+)/57\]', bump, t)
assert count == 57, count

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §410 机制审计")
lines.insert(at + 2, "                     '(MECHANICS_AUDIT PASS)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 58 wired, %d bytes' % os.path.getsize(PATH))
