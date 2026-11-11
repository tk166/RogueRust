"""修 P2 适配器的类型错误。

## 三处

1. `crypto.subtle.digest` 在 TS 5.9 下不接受 `Uint8Array<ArrayBufferLike>`（可能是 SharedArrayBuffer）
   ⇒ 传 `bytes.buffer` 并显式收窄。
2. 两个常量没用上（`noUnusedLocals`）。其中 `H_ENEMY_COUNT` **不该删**：它是向量自报的敌人数量，
   与"扫 6 个槽位、跳过 -1"得到的结果应当一致 —— 用它做一致性断言比删掉更有价值。
3. `decodeCombat` 的参数写成 `Int32Array | readonly number[]`，而内部函数只接受 `Int32Array`
   ⇒ 统一成 `ArrayLike<number>`。
"""

import io

HOST = 'web-next/src/wasm/host.ts'
SNAP = 'web-next/src/wasm/snapshot.ts'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


edit(
    HOST,
    '''async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);''',
    '''async function sha256Hex(bytes: Uint8Array): Promise<string> {
  // TS 5.9 的 `Uint8Array` 泛型允许 `SharedArrayBuffer`，而 `digest` 只收 `ArrayBuffer`
  // ⇒ 显式取出 buffer（这里的 bytes 来自 `arrayBuffer()`，一定不是共享内存）。
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer as ArrayBuffer);''',
    'sha256 buffer',
)

edit(
    SNAP,
    '''function readStatuses(obs: Int32Array, base: number): Statuses {''',
    '''function readStatuses(obs: ArrayLike<number>, base: number): Statuses {''',
    'readStatuses arg',
)

edit(
    SNAP,
    '''const H_HERO_BLOCK = 6;
const H_HERO_WARD = 7;
const H_ENERGY = 8;''',
    '''const H_HERO_BLOCK = 6;
// 7 = `ward`：这一版内容不产生它（恒 `-1`），故意不解码，所以这里不留常量。
const H_ENERGY = 8;''',
    'H_HERO_WARD',
)

edit(
    SNAP,
    '''export function decodeCombat(obs: Int32Array | readonly number[], actions: readonly CombatAction[]): CombatSnapshot {''',
    '''export function decodeCombat(
  obs: ArrayLike<number>,
  actions: readonly CombatAction[]
): CombatSnapshot {''',
    'decodeCombat arg',
)

edit(
    SNAP,
    '''  const handCount = obs[H_HAND_COUNT];''',
    '''  // 向量自报的敌人数量必须与"扫槽位、跳过 -1"的结果一致 —— 不一致说明布局或哨兵语义漂了，
  // 与其渲染出"少一个敌人"，不如当场炸。
  const declaredEnemies = obs[H_ENEMY_COUNT];
  if (declaredEnemies !== enemies.length) {
    throw new RangeError(
      `header says ${declaredEnemies} enemies, layout says ${enemies.length}`
    );
  }

  const handCount = obs[H_HAND_COUNT];''',
    'enemy count check',
)
print('type errors fixed')
