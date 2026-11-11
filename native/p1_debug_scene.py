"""修 `?debug&hand=N` 不生效：它被 `enemies` 的早退守卫挡住了。

## 症状

URL 是 `?debug&still&hand=1`，但 `hand()` 仍然返回 10 张。

## 原因

初始化写成了"先看 `enemies`，没有就 `return base`"，而 `hand` 的处理放在那个早退**之后** ——
于是只要不带 `enemies`，`hand` 永远执行不到。典型的"守卫装在切口下游"（§4.19）。

## 修法

两个调试参数各自独立判断：`hand` 先处理，`enemies` 再处理；两者都只认 `debug` 开关。
顺手把这段从 `useState` 初始化器里抽成一个纯函数 `debugScene(search)` —— 这样"URL 怎么解释"
可以被单测，而不是藏在组件的初始化闭包里。
"""

import io

PATH = 'web-next/src/App.tsx'
t = io.open(PATH, encoding='utf-8').read()

old = '''  const [scene, setScene] = useState<MockScene>(() => {
    let base = initialScene();
    // [P1-LAYOUT] ?debug&enemies=N 下制造 1~6 敌人的测试局面，默认不改变游戏。
    const query = new URLSearchParams(window.location.search);
    const raw = query.get("enemies");
    if (!query.has("debug") || raw === null) return base;
    // [P1-LAYOUT] ?debug&hand=N：手牌数量会改变扇形宽度与紧凑态判定，1..12 都要能看。
    const handRaw = query.get("hand");
    if (handRaw !== null) {
      const handCount = Number(handRaw);
      if (Number.isInteger(handCount) && handCount >= 1 && handCount <= 12) {
        base = {
          ...base,
          hand: Array.from({ length: handCount }, (_, i) => base.hand[i % base.hand.length]),
        };
      }
    }
    const count = Number(raw);
    if (!Number.isInteger(count) || count < 1 || count > 6) return base;
    return {
      ...base,
      enemies: Array.from({ length: count }, (_, i) => ({
        ...base.enemies[i % base.enemies.length], slot: i,
        id: `debug_enemy_${i}`, name: `演示敌人 ${i + 1}`,
        hp: 25 + i * 4, maxHp: 25 + i * 4, intent: `攻击 ${6 + i}`,
      })),
    };
  });'''

new = '''  const [scene, setScene] = useState<MockScene>(() => debugScene(window.location.search));'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

# 纯函数放在组件之前
anchor = '''export interface CommitLogEntry {'''
pure = '''/**
 * `?debug` 下的测试局面：`enemies=N`（1..6）与 `hand=N`（1..12）。
 *
 * ⚠️ 两个参数**各自独立**判断。第一版写成"先看 enemies，没有就 return"，而 hand 的处理在
 * 那个早退之后 —— 于是 `?debug&hand=12`（不带 enemies）永远执行不到（§4.19 的
 * "守卫装在切口下游"）。抽成纯函数也是为了能单测"URL 怎么解释"。
 *
 * 只在 `?debug` 存在时生效；正式路径不暴露造怪/造牌。
 */
export function debugScene(search: string): MockScene {
  const base = initialScene();
  const query = new URLSearchParams(search);
  if (!query.has("debug")) return base;

  let scene = base;
  const handRaw = query.get("hand");
  if (handRaw !== null) {
    const handCount = Number(handRaw);
    if (Number.isInteger(handCount) && handCount >= 1 && handCount <= 12) {
      scene = {
        ...scene,
        hand: Array.from({ length: handCount }, (_, i) => scene.hand[i % scene.hand.length]),
      };
    }
  }
  const enemyRaw = query.get("enemies");
  if (enemyRaw !== null) {
    const count = Number(enemyRaw);
    if (Number.isInteger(count) && count >= 1 && count <= 6) {
      scene = {
        ...scene,
        enemies: Array.from({ length: count }, (_, i) => ({
          ...scene.enemies[i % scene.enemies.length],
          slot: i,
          id: `debug_enemy_${i}`,
          name: `演示敌人 ${i + 1}`,
          hp: 25 + i * 4,
          maxHp: 25 + i * 4,
          intent: `攻击 ${6 + i}`,
        })),
      };
    }
  }
  return scene;
}

export interface CommitLogEntry {'''
assert t.count(anchor) == 1, 'CommitLogEntry 锚点命中 %d 次' % t.count(anchor)
t = t.replace(anchor, pure)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('debugScene extracted')
