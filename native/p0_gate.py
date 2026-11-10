"""把 P0 的 ABI 契约检查装成第 24 道闸门。

## 为什么是 `--check` 而不是 `--report`

* `--check` **与内容无关**（只断言导出存在、长度、哨兵、`i32::MIN` 是合法 seed、18 场景 parity）
  ⇒ 内容扩充不会让它变红，可以当闸门。
* `--report` 的产物**与内容有关**（商店价目、遭遇 id…）⇒ 改内容后必须重跑，
  否则 `docs/ui-abi-audit.md` 引用的数字过期。它只做手动/按需，不进闸门。

改三处：23 处 `[N/23]` → `[N/24]`；在第 23 道之后插入第 24 道；总结区用 `$results.Count` 自动变。
"""

import io

PATH = 'tools/acceptance.ps1'

GATE = '''
Write-Output "`n[24/24] UI ABI 契约：新 UI 依赖的导出/长度/哨兵/场景 parity（P0 基线）"
# 为什么这条必须是一道闸门：`docs/ui-abi-audit.md` 是新 UI 的**契约基线**，而它引用的每条
# 行为都只在一个地方被机器验证 —— `native/ui_abi_dump.mjs --check`。少了它，那些结论就只是
# 文档里的散文：删掉一个导出、改掉一个哨兵、把 `i32::MIN` 当成"没有局"，都不会有闸门红。
#
# 它**与内容无关**（不读具体价目/id），所以内容扩充不会让它变红；真实场景的 dump 走
# `--report`（手动/按需），那份产物与内容有关，改内容后必须重跑。
#
# 判据里包含三条"曾经搞错过"的哨兵：`i32::MIN` 是合法 seed（§348）、Boss 未定时给空串（§349）、
# 没有战斗会话时 `active_slot` 是 -3（查询不创建会话）。
$results += Invoke-Gate -Name 'ui-abi' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine ((Join-Path $ROOT 'native\\ui_abi_dump.mjs') + ' --check') -Workdir $ROOT `
  -MustMatch 'UI_ABI_CHECK PASS \\(exports \\d+, runObs 19, combatObs 148, content 0x[0-9a-f]{8}, scenes 18\\)' `
  -TimeoutSec 180
'''

t = io.open(PATH, encoding='utf-8').read()

n = t.count('/23]')
assert n == 23, n
t = t.replace('/23]', '/24]')

anchor = """  -MustMatch 'NEGCTL1 RED[\s\S]*NEGCTL2 RED[\s\S]*UI_STATE_CHECK PASS' `
  -TimeoutSec 120
"""
assert t.count(anchor) == 1, t.count(anchor)
t = t.replace(anchor, anchor + GATE)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate 24 added; denominators bumped')
