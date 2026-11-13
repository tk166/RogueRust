"""把闸门 43（ui-freeze）接进验收。

锚点用**搜索**（含 `UI_DEPLOY PASS entry=run` 且不是 `-MustMatch` 的那一行），
不手抄长串 —— 手抄两次都因为转义抄错。
"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, '表格锚点 %d' % t.count(ANCHOR)

BLOCK = '''Write-Output "`n[43/43] 冻结边界：契约违约之后**所有**操作入口都动不了（含战斗与旧 fallback）"
# 第十五轮 Review §2：横幅写着"界面已冻结"，而 CombatScreen 直接调 GameStore.dispatch
# 完全绕过；祝福/奖励屏连 busy 都没收到。现在判据只有一份（RunStore.frozenReason ->
# canMutate / GameStore.dispatchGuard），并且是**粘性**的（只有重开一局能解）。
$results += Invoke-Gate -Name 'ui-freeze' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_freeze_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_FREEZE PASS entries=\\d+ refused=\\d+ sticky=1' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/43]' % match.group(1)


t = re.sub(r'(\[\d+)/42\]', bump, t)

lines = t.split('\n')
deploy = [i for i, line in enumerate(lines)
          if 'UI_DEPLOY PASS entry=run' in line and 'MustMatch' not in line]
assert len(deploy) == 1, '证据锚点 %d 行' % len(deploy)
at = deploy[0]
lines[at] = lines[at].rstrip() + ',' if not lines[at].rstrip().endswith(',') else lines[at].rstrip()
lines.insert(at + 1, "                     # 第十五轮 Review §2：冻结边界")
lines.insert(at + 2, "                     '(UI_FREEZE PASS entries=\\d+ refused=\\d+ sticky=1)')) {")

# 收尾：原来数组的 `)) {` 可能还在最后一条上（UI_SOAK_P6）—— 把它去掉，收尾挪到新插入的这一行。
for index in range(len(lines) - 1, -1, -1):
    if 'UI_SOAK_P6 PASS restarts=' in lines[index] and 'MustMatch' not in lines[index]:
        if lines[index].rstrip().endswith(')) {'):
            lines[index] = lines[index].rstrip()[:-len(')) {')].rstrip()
            if not lines[index].endswith(','):
                lines[index] += ','
        break

t = '\n'.join(lines)
temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 43 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
