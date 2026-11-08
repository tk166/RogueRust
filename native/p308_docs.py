"""§308 的文档与参数：闸门从 21 道变 22 道，测试数下限抬到实测值。"""
import io

ROOT = 'D:/Vibe/sts-tui/'
README = ROOT + 'README.md'
ACCEPT = ROOT + 'tools/acceptance.ps1'

PATCHES = [
    (README, '| *（可选）Node.js* | 18+ | 只有 21 道闸门里的浏览器测试需要 | <https://nodejs.org> |',
     '| *（可选）Node.js* | 18+ | 只有 22 道闸门里的浏览器测试需要 | <https://nodejs.org> |'),
    (README, '| `tools/acceptance.ps1` | **聚合验收**：21 道闸门（含 `coverage-matrix`），一道红就整体红 |',
     '| `tools/acceptance.ps1` | **聚合验收**：22 道闸门（含 `coverage-matrix` 与 `state-fields`），一道红就整体红 |'),
    (README, '& .\\tools\\acceptance.ps1                                               # 21 道闸门，约 5 分钟',
     '& .\\tools\\acceptance.ps1                                               # 22 道闸门，约 5 分钟'),
    (README, '### 5.2 21 道闸门', '### 5.2 22 道闸门'),
    (README, '与 C# 参考实现逐字节比状态。它们**不进那 21 道闸门**，因为需要那份约 111 MB 的第三方克隆和一份 NativeAOT 构建：',
     '与 C# 参考实现逐字节比状态。它们**不进那 22 道闸门**，因为需要那份约 111 MB 的第三方克隆和一份 NativeAOT 构建：'),
    (ACCEPT, '  [int]$UnitsFloor = 813', '  [int]$UnitsFloor = 1150'),
]

GATE_ROW = '''| 21 | `coverage-matrix` | `COVERAGE_MATRIX PASS (rows=N, tests=N, fresh)` + `SELFTEST PASS (5 fixtures)`（生成物必须与盘上一致；孤儿行 / 偏差表漂移 / 扫描器自坏都是红） |'''

NEW_ROW = GATE_ROW + '''
| 22 | `state-fields` | `STATE_FIELDS PASS (63 fields, …)`（穷尽读 `RunState` 的字段表：每个字段必须出现在存档的写侧与指纹里；豁免必须带理由，豁免的字段被删也是红） |'''


def main():
    for path, old, new in PATCHES:
        text = io.open(path, encoding='utf-8').read()
        assert text.count(old) == 1, (path, text.count(old), old[:70])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    text = io.open(README, encoding='utf-8').read()
    assert text.count(GATE_ROW) == 1
    io.open(README, 'w', encoding='utf-8', newline='\n').write(text.replace(GATE_ROW, NEW_ROW))
    print('README + UnitsFloor updated')


main()
