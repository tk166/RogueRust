"""修 #1（续）：把冻结传到**所有**场景与战斗屏，并在战斗屏上如实显示。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── RunState 暴露 frozen（界面要能说出"为什么冻结"）────────────────────────
# ── RunApp：blocked 合并 frozen，并传给所有场景 ─────────────────────────────
patch(
    'web-next/src/run/RunApp.tsx',
    [
        (
            'blocked includes frozen',
            '''  const blocked = state?.violations.length ? true : false;''',
            '''  // ⚠️ 冻结是**粘性**的：`violations` 可能变空，但 `frozen` 一旦置位就不解（见 RunStore）。
  const blocked = Boolean(state?.violations.length) || Boolean(state?.frozen);''',
        ),
        (
            'blessing busy',
            '''          <BlessingScene blessings={state.blessings} onChoose={(slot) => store.chooseBlessing(slot)} />''',
            '''          <BlessingScene
            blessings={state.blessings}
            busy={blocked}
            onChoose={(slot) => store.chooseBlessing(slot)}
          />''',
        ),
        (
            'reward busy',
            '''            deckSize={run.deckSize}
            onTakeCard={(slot) => store.takeRewardCard(slot)}''',
            '''            deckSize={run.deckSize}
            busy={blocked}
            onTakeCard={(slot) => store.takeRewardCard(slot)}''',
        ),
        (
            'end busy',
            '''            ascension={state.ascension}
            onRestart={() => {''',
            '''            ascension={state.ascension}
            busy={blocked}
            onRestart={() => {''',
        ),
        (
            'combat frozen',
            '''            host={store.hostForCombat}
            game={store.combat}
            onFinish={() => store.fightEnd()}
          />''',
            '''            host={store.hostForCombat}
            game={store.combat}
            frozen={blocked}
            onFinish={() => store.fightEnd()}
          />''',
        ),
    ],
)

# ── BlessingScene：busy ────────────────────────────────────────────────────
patch(
    'web-next/src/run/scenes/BlessingScene.tsx',
    [
        (
            'props busy',
            '''export interface BlessingSceneProps {
  readonly blessings: readonly Blessing[];
  readonly onChoose: (slot: number) => void;
}''',
            '''export interface BlessingSceneProps {
  readonly blessings: readonly Blessing[];
  readonly onChoose: (slot: number) => void;
  /** 对账失败/冻结时禁用（第十五轮 Review §2：这一屏以前没有 busy）。 */
  readonly busy?: boolean;
}''',
        ),
        (
            'signature',
            '''export function BlessingScene({ blessings, onChoose }: BlessingSceneProps) {''',
            '''export function BlessingScene({ blessings, onChoose, busy = false }: BlessingSceneProps) {''',
        ),
        (
            'button disabled',
            '''              data-blessing-id={blessing.id}
              onClick={() => onChoose(blessing.slot)}''',
            '''              data-blessing-id={blessing.id}
              disabled={busy}
              onClick={() => onChoose(blessing.slot)}''',
        ),
    ],
)

# ── RewardScene：busy ──────────────────────────────────────────────────────
patch(
    'web-next/src/run/scenes/RewardScene.tsx',
    [
        (
            'props busy',
            '''  readonly deckSize: number;
  readonly onTakeCard: (slot: number) => void;''',
            '''  readonly deckSize: number;
  /** 对账失败/冻结时禁用（第十五轮 Review §2：这一屏以前没有 busy）。 */
  readonly busy?: boolean;
  readonly onTakeCard: (slot: number) => void;''',
        ),
        (
            'signature',
            '''  deckSize,
  onTakeCard,''',
            '''  deckSize,
  busy = false,
  onTakeCard,''',
        ),
        (
            'buttons disabled',
            '''            <button type="button" data-take-potion onClick={onTakePotion}>
              收下
            </button>''',
            '''            <button type="button" data-take-potion disabled={busy} onClick={onTakePotion}>
              收下
            </button>''',
        ),
        (
            'relic disabled',
            '''            <button type="button" data-take-relic onClick={onTakeRelic}>
              收下
            </button>''',
            '''            <button type="button" data-take-relic disabled={busy} onClick={onTakeRelic}>
              收下
            </button>''',
        ),
        (
            'card disabled',
            '''            data-reward-card-id={card.id}
            onClick={() => onTakeCard(card.slot)}''',
            '''            data-reward-card-id={card.id}
            disabled={busy}
            onClick={() => onTakeCard(card.slot)}''',
        ),
        (
            'skip disabled',
            '''      <button type="button" className="primary" data-reward-skip onClick={onSkip}>''',
            '''      <button type="button" className="primary" data-reward-skip disabled={busy} onClick={onSkip}>''',
        ),
    ],
)

# ── EndScene：busy ─────────────────────────────────────────────────────────
patch(
    'web-next/src/run/scenes/EndScene.tsx',
    [
        (
            'props busy',
            '''  readonly onRestart: () => void;
  readonly onContinue?: () => void;''',
            '''  /** 对账失败/冻结时禁用（第十五轮 Review §2）。 */
  readonly busy?: boolean;
  readonly onRestart: () => void;
  readonly onContinue?: () => void;''',
        ),
        (
            'signature',
            '''export function EndScene({ kind, run, overWhy, ascension, onRestart, onContinue }: EndSceneProps) {''',
            '''export function EndScene({
  kind,
  run,
  overWhy,
  ascension,
  busy = false,
  onRestart,
  onContinue,
}: EndSceneProps) {''',
        ),
        (
            'restart disabled',
            '''        <button type="button" className="primary" data-restart onClick={onRestart}>''',
            '''        <button type="button" className="primary" data-restart disabled={busy} onClick={onRestart}>''',
        ),
        (
            'continue disabled',
            '''          <button type="button" className="primary" data-act-continue onClick={onContinue}>''',
            '''          <button type="button" className="primary" data-act-continue disabled={busy} onClick={onContinue}>''',
        ),
    ],
)
print('done')
