"""删掉 `p15_wire.py` 重复插入的闸门 53 块，并接上闸门 54。

教训（写进 §376）：`p15_wire.py` 用 `re.sub(r'(\[\d+)/52\]')` 判断"是不是已经接过"，
第二次跑时 `/52]` 已经不存在 ⇒ **bump 计数 0，但块照样插入** ⇒ 闸门 53 出现两次。
幂等性判据必须是"**块在不在**"（按标题 grep），不是"计数器还能不能加"。
"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

# ── 1. 去重：闸门 53 的块（标题 + 调用 + 注释）只能出现一次 ──────────────────
HEAD53 = 'Write-Output "`n[53/53] 端口（§375）'
assert t.count(HEAD53) == 2, t.count(HEAD53)
first = t.index(HEAD53)
second = t.index(HEAD53, first + 1)
# 第二份从它的标题行开始，到下一个 `$results += Invoke-Gate` 块的末尾（含尾随空行）。
tail = t[second:]
marker = '-TimeoutSec 300\n\n'
assert tail.count(marker) >= 1
end = second + tail.index(marker) + len(marker)
t = t[:second] + t[end:]
assert t.count(HEAD53) == 1, t.count(HEAD53)
assert t.count("ui-serve-port") == 1, t.count("ui-serve-port")

# ── 2. 接闸门 54 ───────────────────────────────────────────────────────────
assert 'ui-map-align' not in t, '闸门 54 已经接过了'
ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[54/54] 看得见的错（§376）：地图连线与节点对不上 + 死掉的敌人还站在场上"
# 两条都是玩家实机报的：模型对、画出来错 ⇒ 断言必须在**像素/DOM** 上（模型断言永远不会红）。
# ① 节点与 `<line>` 必须落在同一批坐标上（曾经 CSS column-reverse 与 SVG 的 y 互为镜像，
#    外加 SVG 是替换元素、`inset` + `width:auto` 退回了 145×145 的正方形）；
# ② 真打一场直到有敌人死掉，死者的标签必须消失（不是压暗的尸体）。
$results += Invoke-Gate -Name 'ui-map-align' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_map_align_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_MAP_ALIGN PASS edges=\\d+ worst=[\\d.]+px live=\\d+ killed=\\d+' `
  -TimeoutSec 420

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/54]' % match.group(1)


t = re.sub(r'(\[\d+)/53\]', bump, t)
assert count == 53, count  # 53 个旧标题 + 新的 [54/54]

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §376 地图/战场：像素级对账")
lines.insert(at + 2, "                     '(UI_MAP_ALIGN PASS edges=\\d+ worst=[\\d.]+px live=\\d+ killed=\\d+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 54 wired, %d bytes, bumped %d titles' % (os.path.getsize(PATH), count))
