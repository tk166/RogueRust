"""把证据数组的收尾 `)) {` 归位到**最后一条**（幂等）。

我这一轮已经两次把 `)) {` 插到数组中间（后面还有条目 ⇒ 语法错误）。所以写成脚本：
1. 在 `foreach ($pat in @(` 到 `    $m = [regex]::Match` 之间，把所有行尾的 `)) {` 摘掉（补逗号）；
2. 在**最后一条**（紧邻 `$m = [regex]::Match` 之前的那一行）末尾挂回 `)) {`。
"""

import io

PATH = 'tools/acceptance.ps1'
lines = io.open(PATH, encoding='utf-8').read().split('\n')

start = next(i for i, l in enumerate(lines) if 'foreach ($pat in @(' in l)
end = next(i for i, l in enumerate(lines) if '[regex]::Match($out, $pat)' in l)
assert start < end, (start, end)

TAIL = ')) {'
# 1) 摘掉所有错位的收尾
for i in range(start, end):
    stripped = lines[i].rstrip()
    if stripped.endswith(TAIL):
        body = stripped[: -len(TAIL)].rstrip()
        if not body.endswith(','):
            body += ','
        lines[i] = body

# 2) 找最后一条证据条目（从 end-1 往上，第一条"以 ' 或 , 结尾、且不是注释"的行）
last = end - 1
while last > start:
    stripped = lines[last].rstrip()
    if stripped.startswith('#') or stripped == '':
        last -= 1
        continue
    break
assert last > start, '找不到最后一条证据条目'
lines[last] = lines[last].rstrip().rstrip(',') + TAIL

io.open(PATH, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('array tail normalised at line %d' % (last + 1))
