"""把闸门 41（ui-parity）与 42（ui-deploy）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[41/42] P7 对等：新旧入口同一个 wasm 字节 + 内核侧脚本与新入口逐字段一致"
# 参照物是 **wasm 本身**（Node 里直接跑原始导出），不是旧页面 —— 界面是"被验收的对象"，
# 拿它验另一个界面就是自己验自己。
$results += Invoke-Gate -Name 'ui-parity' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_parity_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_PARITY PASS checkpoints=\\d+ fields=\\d+ sha=match old=alive' `
  -TimeoutSec 600

Write-Output "`n[42/42] P7 部署：wasm MIME / 缓存策略 / 版本一致性 / 两个入口都可起"
$results += Invoke-Gate -Name 'ui-deploy' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_deploy_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_DEPLOY PASS entry=(legacy|run) assets=\\d+ wasm=application/wasm cache=immutable-for-hashed version=match' `
  -TimeoutSec 300

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/42]' % match.group(1)


t = re.sub(r'(\[\d+)/40\]', bump, t)

MARKER = ("                     '(UI_SOAK_P6 PASS restarts=\\d+ steps=\\d+ heap=\\d+KB->\\d+KB "
          "context-lost=\\d motion-persisted=\\d)')) {")
assert t.count(MARKER) == 1, t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_SOAK_P6 PASS restarts=\\d+ steps=\\d+ heap=\\d+KB->\\d+KB context-lost=\\d "
    "motion-persisted=\\d)'," + chr(10) +
    "                     # P7：对等 + 部署" + chr(10) +
    "                     '(UI_PARITY PASS checkpoints=\\d+ fields=\\d+ sha=match old=alive)'," + chr(10) +
    "                     '(UI_DEPLOY PASS entry=(legacy|run) assets=\\d+ wasm=application/wasm "
    "cache=immutable-for-hashed version=match)')) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gates 41/42 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
