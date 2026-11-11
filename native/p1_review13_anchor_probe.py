"""探针：把第十三轮补丁包的**每一个锚点**逐条试一遍，报告哪几条对不上当前源码。

## 为什么值得做

补丁包自称"基线 bf7c7f5"，但 `Stage.props` 一条就 0 命中（我的 `}` 与 `export function Stage`
之间有一个空行，补丁里没有）。一条对不上就会 abort，所以我看不到"到底差多远"。
这里把 `replace_once` 换成一个**收集而不抛**的版本，于是能一次列出全部失败锚点 ——
这决定了"照单套用"还是"照意图自己实现"。
"""

import importlib.util
import io
import sys

BUNDLE = 'D:/Vibe/sts-tui/.tmp-rr13/roguerust_p1_ui_sample/apply_p1_ui_example.py'
ROOT = 'D:/Vibe/sts-tui/web-next/src'

spec = importlib.util.spec_from_file_location('bundle', BUNDLE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

failures = []
applied = []


def collecting(text, old, new, label):
    """收集版 replace_once：命中就替换，没命中就记一笔并原样返回。"""
    count = text.count(old)
    if count == 1:
        applied.append(label)
        return text.replace(old, new)
    failures.append((label, count, old.splitlines()[0][:70] if old.splitlines() else ''))
    return text


mod.replace_once = collecting

targets = [
    ('input/pointerMachine.ts', mod.patch_pointer),
    ('stage/Stage.tsx', mod.patch_stage),
    ('overlay/TextOverlay.tsx', mod.patch_overlay),
    ('App.tsx', mod.patch_app),
    ('styles.css', mod.patch_css),
]

for rel, fn in targets:
    path = '%s/%s' % (ROOT, rel)
    src = io.open(path, encoding='utf-8').read()
    before = len(failures)
    fn(src)
    print('%-26s 锚点失败 %d 条' % (rel, len(failures) - before))

print('')
print('命中 %d 条，失败 %d 条' % (len(applied), len(failures)))
print('')
if failures:
    print('失败锚点（label / 命中次数 / 首行）：')
    for label, count, head in failures:
        print('  %-34s count=%d  %s' % (label, count, head))
