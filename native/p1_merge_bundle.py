"""把第十三轮参考包（`RogueRust_P1_LeftRight_Layout_Gestures_Example.zip`）合并进来。

## 为什么不逐条手抄

参考包带 47 条锚点 + 2 个新纯函数文件 + 3 份纯函数测试。逐条手抄等于把它再实现一遍，
而"实现两遍"必然漂。所以：**照它的锚点应用**，只修一处不兼容的锚点（见下），
然后把本地已有的修复/纪律套在新结构上。

## 唯一的锚点适配

`Stage.props` 在参考包里写成 `}` 紧跟 `export function Stage(`，而本仓库这两行之间有一个空行
（`native/p1_review13_anchor_probe.py` 报的就是这一条：46/47）。这里只在**这一条**上做容差，
不做全局模糊匹配 —— 全局容差会把"锚点对不上"这种真信号吃掉。

## 顺序

1. 预检**所有**文件（任何一条锚点对不上就整体中止，不写盘）；
2. 全绿才写盘（先写 `.tmp` 再 `replace`，原子替换）；
3. 打印每个文件的字符数变化，便于复核。
"""

import importlib.util
import io
import os
import sys
import tempfile
import zipfile

ROOT = 'D:/Vibe/sts-tui'
ZIP = os.path.join(ROOT, 'docs/vibe/RogueRust_13/RogueRust_P1_LeftRight_Layout_Gestures_Example.zip')
TARGET = os.path.join(ROOT, 'web-next/src')

tmp = tempfile.mkdtemp(prefix='rr13-')
zipfile.ZipFile(ZIP).extractall(tmp)
BUNDLE = os.path.join(tmp, 'roguerust_p1_ui_sample')

spec = importlib.util.spec_from_file_location('bundle', os.path.join(BUNDLE, 'apply_p1_ui_example.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_original = mod.replace_once
adaptations = []


def tolerant(text, old, new, label):
    """只对 `Stage.props` 放宽：允许 `}` 与 `export function` 之间有一个空行。"""
    if label == 'Stage.props' and text.count(old) == 0:
        relaxed = old.replace('}\nexport function Stage(', '}\n\nexport function Stage(')
        if text.count(relaxed) == 1:
            adaptations.append(label)
            return _original(text, relaxed, new, label)
    return _original(text, old, new, label)


mod.replace_once = tolerant

PATCHES = [
    ('input/pointerMachine.ts', mod.patch_pointer),
    ('stage/Stage.tsx', mod.patch_stage),
    ('overlay/TextOverlay.tsx', mod.patch_overlay),
    ('App.tsx', mod.patch_app),
    ('styles.css', mod.patch_css),
]

staged = {}
summary = []
for rel, fn in PATCHES:
    path = os.path.join(TARGET, rel)
    old = io.open(path, encoding='utf-8').read()
    new = fn(old)
    assert new != old, '%s 没有任何改动' % rel
    staged[path] = new
    summary.append((rel, len(old), len(new)))

for rel in ('stage/formation.ts', 'input/hitTest.ts'):
    path = os.path.join(TARGET, rel)
    if os.path.exists(path):
        print('已存在，拒绝覆盖：%s' % rel)
        sys.exit(2)
    staged[path] = io.open(os.path.join(BUNDLE, 'files', os.path.basename(rel)), encoding='utf-8').read()
    summary.append((rel, 0, len(staged[path])))

print('PREFLIGHT OK：所有锚点命中（适配 %d 条：%s）' % (len(adaptations), ', '.join(adaptations) or '无'))
for rel, before, after in summary:
    print('  %-26s %6d -> %6d 字符' % (rel, before, after))

for path, content in staged.items():
    temp = path + '.merge-tmp'
    io.open(temp, 'w', encoding='utf-8', newline='\n').write(content)
    assert os.path.getsize(temp) > 0
    os.replace(temp, path)
print('已写入 %d 个文件' % len(staged))
