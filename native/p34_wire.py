"""接闸门 56（ui-layout-words）。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert 'ui-layout-words' not in t, '闸门 56 已经接过了'

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[56/56] 布局宽度与词表（§381–§383）：地图/面板不再抖 + 定向牌 + 效果人话"
# 玩家第二轮报的四条：① 地图宽度塌了；② 悬浮窗宽度不定、卡牌一列/两列来回跳
# （`.scene` 的 fit-content + sticky 面板在流内 ⇒ 死循环抖动）；
# ③ `观察弱点` 不选敌人就结算；④ 事件「翅膀雕像 · 祈祷」显示"未知效果 6（0）"。
# 判据：布局用**自比**（无面板/指三张牌四种状态下的场景宽、面板宽、行数都不许变），
# 语义用**穷尽遍历**（295 张牌的定向性、内核效果闭集 1..16 的人话）。
$results += Invoke-Gate -Name 'ui-layout-words' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_layout_words_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_LAYOUT_WORDS PASS cards=\\d+ effects=\\d+ scene-widths=\\d+ row-counts=\\d+' `
  -TimeoutSec 420

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/56]' % match.group(1)


t = re.sub(r'(\[\d+)/55\]', bump, t)
assert count == 55, count

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §381-§383 布局宽度 + 定向牌 + 效果词表")
lines.insert(at + 2, "                     '(UI_LAYOUT_WORDS PASS cards=\\d+ effects=\\d+ scene-widths=\\d+ row-counts=\\d+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 56 wired, %d bytes' % os.path.getsize(PATH))
