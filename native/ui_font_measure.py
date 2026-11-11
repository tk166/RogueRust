"""P1 可读性的另一半证据：**中文字形图集要多大**。

## 问题

plan §13 把"三维中文文字"列为"PoC 决定"。要决定它，得先知道代价：
3D 文字要一份中文字体，而这份字体（或它的 MSDF 图集）**必须跟着内容走** ——
每加一张牌、每改一句描述，字形集合就可能变，图集就得重建。这笔账必须量出来，不能猜。

## 做法

1. 只收集**面向玩家的字符串**：`sts/content/*.json` 的 name/desc 字段 + 新 UI 里
   真正显示给玩家的标签。⚠️ **不扫源码注释** —— 第一版把 `Stage.tsx` 的 340 个中文注释字
   也算进去了，把 883 个"字形"这个数字整个抬虚（那是我的注释，不是玩家的字）。
2. 用 fontTools 把 `msyh.ttc`（微软雅黑）与 `simhei.ttf` **子集化**到这个集合，
   输出 TTF 与 WOFF2，报字节数。
3. 报"完整字体有多大"作对照 —— 那才是"不子集化"的代价。

## 结论怎么用

DOM 覆盖层用系统字体 ⇒ 增量 **0 字节**。所以 P1 的选择是"3D 牌身 + DOM 文字"。
本脚本量出的子集体积是"如果将来真要做 3D 文字，最低要付多少"。
"""

import io
import json
import os
import re

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'ui-next-p1')
os.makedirs(OUT, exist_ok=True)

CJK = re.compile(r'[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]')

strings = []
per_file = {}

# ① 内容：只取 name / desc 一类字段（真实的卡名与规则文本）
for name in ('cards', 'enemies', 'statuses', 'relics'):
    path = os.path.join(ROOT, 'sts', 'content', '%s.json' % name)
    if not os.path.exists(path):
        continue
    data = json.load(io.open(path, encoding='utf-8'))
    collected = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('name', 'desc') and isinstance(value, str):
                    collected.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    per_file['sts/content/%s.json' % name] = len(set(CJK.findall(''.join(collected))))
    strings.extend(collected)

# ② 新 UI 里真正显示给玩家的标签（HUD 是拉丁字母，故只有这些中文）
UI_LABELS = [
    '设置', '关闭', '模态打开时，拖牌与目标高亮都被隔离（点空白处关闭）。',
    '费用', '铁甲战士',
]
strings.extend(UI_LABELS)

chars = set()
for text in strings:
    chars |= set(CJK.findall(text))

glyphs = ''.join(sorted(chars))
print('面向玩家的字符串：%d 条' % len(strings))
for name, count in sorted(per_file.items(), key=lambda kv: -kv[1]):
    print('  %-28s %4d' % (name, count))
print('不同中文字形（含标点）：%d' % len(glyphs))

FONTS = [
    ('msyh.ttc', 0, '微软雅黑'),
    ('simhei.ttf', None, '黑体'),
]
results = []
for filename, index, label in FONTS:
    path = os.path.join('C:/Windows/Fonts', filename)
    if not os.path.exists(path):
        print('  跳过（不存在）：%s' % path)
        continue
    full_bytes = os.path.getsize(path)
    for flavor, ext in ((None, 'ttf'), ('woff2', 'woff2')):
        options = subset.Options()
        options.desubroutinize = True
        options.notdef_outline = True
        options.recalc_bounds = True
        options.drop_tables += ['DSIG']
        font = TTFont(path, fontNumber=index if index is not None else -1)
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=glyphs)
        subsetter.subset(font)
        # ⚠️ flavor 要设在 **font 上**：只写 `options.flavor` 时输出仍是 TTF 字节
        # （第一版两种格式字节数一模一样，就是这个问题）。
        font.flavor = flavor
        target = os.path.join(OUT, 'subset-%s.%s' % (filename.split('.')[0], ext))
        font.save(target)
        font.close()
        magic = io.open(target, 'rb').read(4)
        results.append((label, ext, os.path.getsize(target), full_bytes, magic))

print('')
print('%-10s %-6s %10s %12s  %s' % ('字体', '格式', '子集字节', '完整字体', '魔数'))
for label, ext, size, full, magic in results:
    print('%-10s %-6s %10d %12d  %s' % (label, ext, size, full, magic))

report = {
    'playerStrings': len(strings),
    'distinctCjkGlyphs': len(glyphs),
    'perSource': dict(sorted(per_file.items(), key=lambda kv: -kv[1])),
    'subsets': [
        {
            'font': label,
            'format': ext,
            'bytes': size,
            'fullFontBytes': full,
            'magic': magic.decode('latin-1'),
        }
        for label, ext, size, full, magic in results
    ],
    'domOverlayBytes': 0,
}
with io.open(os.path.join(OUT, 'font-measure.json'), 'w', encoding='utf-8', newline='\n') as handle:
    json.dump(report, handle, ensure_ascii=False, indent=1)
    handle.write('\n')

# 判据：woff2 必须真的比 ttf 小（否则就是 flavor 没生效 —— 这条负控抓过一次）
woff2 = [row for row in results if row[1] == 'woff2']
ttf = [row for row in results if row[1] == 'ttf']
for (label, _, wsize, _, wmagic), (_, _, tsize, _, _) in zip(woff2, ttf):
    assert wmagic[:4] == b'wOF2', '%s 的 woff2 魔数不对：%r' % (label, wmagic)
    assert wsize < tsize, '%s 的 woff2 (%d) 没有比 ttf (%d) 小' % (label, wsize, tsize)

print('')
print('FONT_MEASURE PASS glyphs=%d subsets=%d -> %s'
      % (len(glyphs), len(results), os.path.relpath(os.path.join(OUT, 'font-measure.json'), ROOT)))
