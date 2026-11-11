"""修手牌夹具的竞态：`Page.navigate` 是异步的，不能拿旧页面的 `__p1` 当"就绪"。

上一版红在这里：`check(ready)` 只要 `window.__p1.ready` 为真就过，而导航还没提交时那是**旧页面**的
探针 —— 于是 `waitStable` 对着旧页面（10 张）立刻返回，随后按 slot 找牌就拿到 null。

修法：轮询到**期望的手牌数**且投影帧数足够，才算就绪。判据是"这一页真的换了"，
不是"有个探针在"。
"""

import io

PATH = 'native/ui_next_check.mjs'
t = io.open(PATH, encoding='utf-8').read()

old = '''  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    ready = await evaluate("Boolean(window.__p1 && window.__p1.ready)");
    if (ready) break;
    await sleep(100);
  }
  check(ready, `hand=${handCase.count}：页面重新就绪`);
  await waitStable(20);'''

new = '''  // ⚠️ 判据是"这一页真的换成 hand=N 了"，不是"有个探针在"：导航未提交时
  // `window.__p1` 还是**旧页面**的，照着它判断会对着旧布局断言。
  let ready = false;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    ready = await evaluate(
      `Boolean(window.__p1 && window.__p1.ready && window.__p1.hand().length === ${handCase.count}` +
        ` && window.__p1.layout().frames > 10)`
    );
    if (ready) break;
    await sleep(100);
  }
  check(ready, `hand=${handCase.count}：页面重新就绪（手牌数已切换）`);'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''  const pressedLast = await mousePress(lastPoint);'''
new = '''  check(Boolean(lastPoint), `${handCase.label}：拿到最右那张的命中点`);
  const pressedLast = lastPoint ? await mousePress(lastPoint) : { phase: "missing", handSlot: -1 };'''
assert t.count(old) == 1, 'mousePress 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

old = '''  await mouseRelease(lastPoint);
}'''
new = '''  if (lastPoint) await mouseRelease(lastPoint);
}'''
assert t.count(old) == 1, 'mouseRelease 锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('hand fixture race fixed')
