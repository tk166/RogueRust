"""把闸门 52（ui-cardface）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[52/52] 卡面（§374）：文字层真的样式化 + 卡面落在牌心上 + 徽章用内容 id"
# 用户报"卡面是空的"。根因有两层：run.html 没加载 styles.css（文字层是 static，飘在屏幕外），
# 以及徽章从没接到手牌/详情；更深一层：ViewCard/ViewEnemy 的 id 是合成 id（hand-0-1 / enemy-0），
# 拿它查素材表会走降级（每只怪随机一个原型）。之前的闸门断言文本内容，抓不到几何与样式。
$results += Invoke-Gate -Name 'ui-cardface' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_cardface_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_CARDFACE PASS cards=\\d+ offset=\\d+px letters=[A-Z,]+' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/52]' % match.group(1)


t = re.sub(r'(\[\d+)/51\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §374 卡面：样式化 + 位置 + 内容 id")
lines.insert(at + 2, "                     '(UI_CARDFACE PASS cards=\\d+ offset=\\d+px letters=[A-Z,]+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 52 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
