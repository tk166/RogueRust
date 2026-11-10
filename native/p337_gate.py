"""把 `docs/ui-state-model.md` 的防腐检查装成第 23 道闸门（`port-plan.md` §337）。

改三处：
1. 22 处 `[N/22]` → `[N/23]`（分母是硬编码的，加一道就得全改，否则输出在说谎）；
2. 在第 22 道之后插入第 23 道；
3. 不动总结区（它用 `$results.Count`，自动变成 23）。

判据用 `--negative`：检查器自带两条反证（塞假名字 / 删真名字），两条都必须红。
所以闸门的 `-MustMatch` 钉的是 `UI_STATE_CHECK PASS`，而负控在**同一次运行**里跑 ——
如果负控不红了，输出里就不会出现两行"RED（正确）"，`MustMatch` 就该把这两行也钉住。
"""

import io

PATH = 'tools/acceptance.ps1'

GATE = '''
Write-Output "`n[23/23] UI 状态模型：文档点名的每个导出都存在，每个导出都被登记"
# 为什么这条必须是一道闸门：`docs/ui-state-model.md` 是"3D 重写要读什么"的现场清单，而它的
# 每一行都在声称"这个字段从 rd_xxx 读"。文档只有一种腐烂方式：名字不再存在，或者新导出
# 没人登记 —— 两种都长得像"文档看起来挺好"，没有任何编译器或测试会碰到它。
# 第一版按 `_len`/`_into` 前缀整片豁免，于是 **72 条导出**"存在但文档没写"却报绿；
# 现在只允许 `X_into` 在 `X_len` 已登记时才算登记（§8 的名字表把 41 对全列了出来）。
# 同一次运行里跑两条反证（塞一个假名字 / 删掉一个真名字的提及），两条都必须红 ——
# 没有反证过的下限等于没有下限（§161.5）。
$results += Invoke-Gate -Name 'ui-state' -Exe $PY `
  -ArgLine ((Join-Path $ROOT 'native\\ui_state_check.py') + ' --negative') -Workdir $ROOT `
  -MustMatch 'UI_STATE_CHECK PASS[\\s\\S]*负控① RED（正确）[\\s\\S]*负控② RED（正确）' `
  -TimeoutSec 120
'''

t = io.open(PATH, encoding='utf-8').read()

# ① 分母：22 → 23
n = t.count('/22]')
assert n == 22, n
t = t.replace('/22]', '/23]')

# ② 插在第 22 道之后（`state-fields` 那个 Invoke-Gate 块的结尾）
anchor = """  -MustMatch 'STATE_FIELDS PASS' -TimeoutSec 120
"""
assert t.count(anchor) == 1
t = t.replace(anchor, anchor + GATE)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('gate 23 added; denominators bumped')
