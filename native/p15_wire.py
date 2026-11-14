"""把闸门 53（ui-serve-port）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[53/53] 端口（§375）：被占用时换端口并说清 + 起来之后自检"
# 用户实测：play.ps1 打印 127.0.0.1:8080，浏览器打开却是 **Steam**（它的 CEF 调试端口就是 8080）。
# 根因：Node 的 listen(8080) 绑 ::（双栈），Steam 绑 127.0.0.1:8080，两者能同时绑成功，
# 而浏览器连 127.0.0.1 时命中更具体的那个。修法：绑 127.0.0.1 + 占用回退 + 自检 #root。
$results += Invoke-Gate -Name 'ui-serve-port' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_serve_port_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SERVE_PORT PASS fallback=1 port=\\d+ selfcheck=ok' `
  -TimeoutSec 300

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/53]' % match.group(1)


t = re.sub(r'(\[\d+)/52\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §375 端口占用：回退 + 自检")
lines.insert(at + 2, "                     '(UI_SERVE_PORT PASS fallback=1 port=\\d+ selfcheck=ok)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 53 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
