"""把闸门 45/46（素材流水线）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, '表格锚点 %d' % t.count(ANCHOR)

BLOCK = '''Write-Output "`n[45/46] 素材清单：内容 id 逐个覆盖 / 字母规则 / 16 种几何原型（纯函数）"
# 清单是**生成**的（native/build_assets.py）：内容加了东西而美术没跟上，会在生成时就暴露。
# 这一道还量了"两位字母的碰撞数"——这一版接受碰撞，但必须是个**数字**而不是感觉。
$results += Invoke-Gate -Name 'ui-assets' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_assets_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ASSETS PASS enemies=\\d+ cards=\\d+ relics=\\d+ potions=\\d+ statuses=\\d+ archetypes=\\d+ collisions=\\d+' `
  -TimeoutSec 300

Write-Output "`n[46/46] 素材渲染：素材库页面真的画出来 + 产品界面（奖励/商店/牌组/药水）也用了徽章"
# 三维那一条用 CDP **截图**统计彩色像素（`gl.readPixels` 在合成之后读不到 —— 那是"读晚了"）。
$results += Invoke-Gate -Name 'ui-assets-render' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_assets_render_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ASSETS_RENDER PASS archetypes=\\d+ enemies=\\d+ cards=\\d+ badges=4tables lit=\\d+' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/46]' % match.group(1)


t = re.sub(r'(\[\d+)/44\]', bump, t)

lines = t.split('\n')
# 收尾行要**同时**落在证据数组里：限定在 `foreach ($pat in @(` 到 `[regex]::Match($out, $pat)` 之间。
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, '收尾行 %d 条（范围 %d..%d）' % (len(close), start, end)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # 素材流水线：清单覆盖 + 渲染")
lines.insert(at + 2, "                     '(UI_ASSETS PASS enemies=\\d+ cards=\\d+ relics=\\d+ potions=\\d+ statuses=\\d+ archetypes=\\d+ collisions=\\d+)',")
lines.insert(at + 3, "                     '(UI_ASSETS_RENDER PASS archetypes=\\d+ enemies=\\d+ cards=\\d+ badges=4tables lit=\\d+)')) {")

t = '\n'.join(lines)
temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gates 45/46 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
