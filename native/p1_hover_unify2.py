"""收尾：删掉 `onHover` / `onRelease` 与它们的 prop（已被 window 监听取代）。

上一个脚本在"找 `// 点按语义`"那步失败（合并参考包之后那段注释已经不存在），
但前面的编辑已经落盘 —— 属于 §3 ⑥ 的"半改的文件"。这里按实际内容精确切除，
并保留 `onCardHover` 的删除（Stage 已不再需要它）。
"""

import io

APP = 'web-next/src/App.tsx'
t = io.open(APP, encoding='utf-8').read()

start = t.index('  const onHover = useCallback(')
end = t.index('  // [P1-UX] 全局指针跟踪')
block = t[start:end]
assert 'const onRelease = useCallback(' in block, '切除范围不含 onRelease'
assert len(block) < 1200, '切除范围过大（%d 字符）' % len(block)
t = t[:start] + t[end:]

old = '''          onCardDown={onCardDown}
          onCardHover={setHoverCardSlot}
          onHover={onHover}
          onRelease={onRelease}
        />'''
new = '''          onCardDown={onCardDown}
        />'''
assert t.count(old) == 1, 'Stage props 命中 %d 次' % t.count(old)
t = t.replace(old, new)

# hoverRef 现在只被 onMove 写、没人读（落点统一由 currentTarget 算）——去掉，别留死状态。
old = '''  // 上一帧的 hover 槽位：`pointerup` 落空时用它兜底（R3F 的 onPointerUp 只对命中的对象触发）。
  const hoverRef = useRef(-1);
'''
assert t.count(old) == 1, 'hoverRef 声明命中 %d 次' % t.count(old)
t = t.replace(old, '')
old = '''      const target = currentTarget(event.clientX, event.clientY);
      hoverRef.current = target;
      store.send({ type: "move", hoverSlot: target, distance });'''
new = '''      store.send({
        type: "move",
        hoverSlot: currentTarget(event.clientX, event.clientY),
        distance,
      });'''
assert t.count(old) == 1, 'hoverRef 写入命中 %d 次' % t.count(old)
t = t.replace(old, new)

assert 'hoverRef' not in t, '还有 hoverRef 残留'
io.open(APP, 'w', encoding='utf-8', newline='\n').write(t)
print('onHover/onRelease/hoverRef removed')
