"""把闸门 44（ui-archive）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, '表格锚点 %d' % t.count(ANCHOR)

BLOCK = '''Write-Output "`n[44/44] 存档 / 回档：导出 → 刷新 → 导入逐字段相同；坏档案被拒且局面不动"
# 第十五轮 Review §6：默认入口切到新 UI 之后，"刷新就丢局"从"可以没有"变成"必须有"。
# 内核早有可信档案（MAGIC-base64-校验和，含内容指纹），这一版把它接到设置面板上。
$results += Invoke-Gate -Name 'ui-archive' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_archive_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ARCHIVE PASS bytes=\\d+ refused=\\d+ roundtrip=1' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/44]' % match.group(1)


t = re.sub(r'(\[\d+)/43\]', bump, t)

lines = t.split('\n')
freeze = [i for i, line in enumerate(lines)
          if 'UI_FREEZE PASS entries=' in line and 'MustMatch' not in line]
assert len(freeze) == 1, '证据锚点 %d 行' % len(freeze)
at = freeze[0]
# 数组收尾 `)) {` 现在挂在这一行上：先摘掉，把新条目接上，再把收尾放回最后一条。
had_tail = lines[at].rstrip().endswith(')) {')
if had_tail:
    lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # 第十五轮 Review §6：存档 / 回档")
lines.insert(at + 2, "                     '(UI_ARCHIVE PASS bytes=\\d+ refused=\\d+ roundtrip=1)')) {")

t = '\n'.join(lines)
temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 44 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
