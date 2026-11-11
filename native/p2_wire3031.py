"""把闸门 30（`ui-wasm-choice`）与 31（`ui-wasm-fixtures`）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
assert os.path.getsize(PATH) > 28000, 'acceptance.ps1 不完整'
t = io.open(PATH, encoding='utf-8').read()

old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
new = '''Write-Output "`n[30/31] P2 待决选牌（PendingChoice）+ 演出 beat：真问句、真消耗、真 beat"
# 会问句的牌（armaments/warcry/headbutt/exhume/dual_wield/nightmare/true_grit+）都不在起手牌里，
# 而起手牌是随机的 ⇒ "打几把看看能不能碰到"不是夹具。所以用 rd_run_grant_potion + rd_env_use_potion：
# Elixir 一喝就问"要消耗哪几张"，局面确定、可复现，而且走的是真内核。
$results += Invoke-Gate -Name 'ui-wasm-choice' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_wasm_choice_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_CHOICE PASS source=\\d+ kind=\\d+ options=\\d+ exhaust=\\d+->\\d+ beats=ok' `
  -TimeoutSec 300

Write-Output "`n[31/31] P2 定向夹具：同名卡 / 0 能量 / 敌人槽位稳定（X 费不可达，见文档）"
# 这三条是 plan P2 点名的夹具。同名卡那条尤其重要：手牌槽位是**位置**（打出后压实），
# 不是身份 —— UI 若把"第 3 张 strike"当成"strike"去查，就会打错副本（Review P2-A）。
$results += Invoke-Gate -Name 'ui-wasm-fixtures' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_wasm_fixtures_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_FIXTURES PASS duplicate=\\d+ zero-energy=1 slot-stable=1' `
  -TimeoutSec 300

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
assert t.count(old) == 1, '锚点 %d' % t.count(old)
t = t.replace(old, new)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/31]' % match.group(1)


t = re.sub(r'(\[\d+)/29\]', bump, t)

# 闸门 27 的证据串加 choice=6
t = t.replace(
    'UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+ decode=\\d+',
    'UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+ decode=\\d+ choice=\\d+',
)

marker = "'(UI_WASM_UI PASS mode=wasm hand=\\d+ energy=\\d+ enemy0=\\d+->\\d+)'" + ")) {"
assert t.count(marker) == 1, 'evidence 锚点 %d' % t.count(marker)
t = t.replace(
    marker,
    "'(UI_WASM_UI PASS mode=wasm hand=\\d+ energy=\\d+ enemy0=\\d+->\\d+)'," + chr(10) +
    "                     # P2：待决选牌与 beat" + chr(10) +
    "                     '(UI_WASM_CHOICE PASS source=\\d+ kind=\\d+ options=\\d+)'," + chr(10) +
    "                     # P2：定向夹具" + chr(10) +
    "                     '(UI_WASM_FIXTURES PASS duplicate=\\d+ zero-energy=1 slot-stable=1)'" + ")) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常 %d' % os.path.getsize(temp)
os.replace(temp, PATH)
print('gates 30/31 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
