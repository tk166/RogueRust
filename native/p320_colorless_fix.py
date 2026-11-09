"""修 `p320_colorless.py` 单行分支留下的两处形状问题：

1. `upgraded: None\n    colorless: false, }` —— 前一个字段后面少一个逗号；
2. `PoolCard {  id:` —— 多出一个空格（无害但难看）。
记忆点：**变换之后的文本必须用编译器验一遍**，不能只看"插了几处"。
"""

import io
import re

PATH = 'kernel/rd-run/src/state.rs'

t = io.open(PATH, encoding='utf-8').read()
before = t
t = re.sub(r'upgraded: (None|Some\("[^"]*"\))\n(\s*)colorless: false, \}',
           r'upgraded: \1,\n\2colorless: false }', t)
t = t.replace('PoolCard {  id:', 'PoolCard { id:')
assert t != before, 'nothing to repair'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('repaired %d single-line literal(s)' % len(re.findall(r'colorless: false \}', t)))
