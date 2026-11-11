"""修 JSX：把说明注释从 `<group>` 的**属性列表**里挪到元素外面。"""

import io

PATH = 'web-next/src/stage/Stage.tsx'
t = io.open(PATH, encoding='utf-8').read()

old = '''        return (
          <group
            key={`${enemy.id}-${enemy.slot}`}
            ref={(node) => {
              enemyRefs.current[index] = node;
            }}
            {/* ⚠️ 敌人身上**不再挂** onPointerMove / onPointerUp：hover 与落点都由
                `App` 的 window 监听经 `hitTest`（屏幕命中）统一算。
                这里再挂一份就是"同一个事实两个来源"—— 两者几何不同（真 mesh vs 半径+14px），
                边缘会出现"绿环亮着但没有 hover 高亮"。 */}
          >'''
new = '''        // ⚠️ 敌人身上**不再挂** onPointerMove / onPointerUp：hover 与落点都由 `App` 的
        // window 监听经 `hitTest`（屏幕命中）统一算。这里再挂一份就是"同一个事实两个来源"
        // —— 两者几何不同（真 mesh vs 半径+14px），边缘会出现"绿环亮着但没有 hover 高亮"。
        return (
          <group
            key={`${enemy.id}-${enemy.slot}`}
            ref={(node) => {
              enemyRefs.current[index] = node;
            }}
          >'''
assert t.count(old) == 1, '命中 %d 次' % t.count(old)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('JSX comment moved out')
