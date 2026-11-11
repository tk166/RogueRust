"""修掉被 bash 吃掉反引号的那条注释（FACT §2 复发：`python -c` 里带反引号的文本会被 shell 执行）。"""

import io

p = 'web-next/src/stage/Stage.tsx'
t = io.open(p, encoding='utf-8').read()
old = '''          {/* 手牌是 **UI**： +  让牌永远画在世界之上。
              否则地台（水平面，一直延伸到相机前）会挡住牌的下半截 —— 截图里"牌只剩一条"。 */}'''
new = '''          {/* 手牌是 **UI**：depthTest=false + renderOrder 让牌永远画在世界之上。
              否则地台（水平面，一直延伸到相机前）会挡住牌的下半截 —— 截图里"牌只剩一条"。 */}'''
assert t.count(old) == 1
io.open(p, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))
print('comment restored')
