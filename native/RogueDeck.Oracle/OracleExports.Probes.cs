using System.Runtime.InteropServices;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// One export per spec vector that the wide runner cannot express: the vectors that are about a MECHANISM
/// (the shuffle, an expression's arithmetic, a loop's limits, a decree, a trigger's firing order, a
/// snapshot's round trip) rather than about a row of numbers.
///
/// Every probe drives the real engine. Some go through the authoring layer like rd_oracle_run_ex; the ones
/// that must set up a state the blueprints cannot reach (a minimal registry, a directly ended turn) build
/// the CombatState by hand exactly as the cited C# test does.
/// </summary>
public static partial class OracleExports
{
    /// <summary>1 = the probe's own invariant held (e.g. every snapshot round trip hashed the same).</summary>
    private static int _probeOk;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_ok")]
    public static int ProbeOk() => _probeOk;

    private static ScenarioReport? RunFight(ScenarioBlueprint fight, IReadOnlyList<ScenarioStep> script, int seed)
    {
        try
        {
            return new ScenarioRunner()
                .Run(new Playthrough(fight, script, combatId: "oracle_probe", randomSeed: seed));
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return null;
        }
    }

    private static ScenarioBlueprint NewFight(
        int heroHp, int enemyHp, int enemyCount, int cardCount, int drawPerTurn,
        IEffectNode<CardPlayContext> program, int cardCost, bool shuffle, int energy = 3)
    {
        var fight = new ScenarioBlueprint
        {
            CardsDrawnPerTurn = Math.Max(1, drawPerTurn),
            ShuffleDrawPileOnStart = shuffle,
        };
        fight.Cards.Add(new CardBlueprint(CardId) { Program = new EffectProgram<CardPlayContext>(program) }
            .Cost(StandardCombatIds.EnergyResource, cardCost));
        fight.Hero = new HeroBlueprint(HeroId) { MaxHealth = Math.Max(1, heroHp) };
        fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(CardId), Count: Math.Max(1, cardCount)));
        fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, Current: energy, Max: energy));
        for (var i = 0; i < enemyCount; i++)
            fight.Enemies.Add(new EnemyBlueprint(EnemyId(i)) { MaxHealth = Math.Max(1, enemyHp) });
        return fight;
    }

    private static IReadOnlyList<ScenarioStep> PlayOnce() =>
        new ScenarioScript().HeroPlays(CardId, EnemyId(0)).Build();

    // ── 1. the shuffle, as the engine actually performs it ──────────────────────────────────────────────

    /// <summary>
    /// Builds a fight with <paramref name="deckSize"/> DISTINCT cards and ShuffleDrawPileOnStart on, runs an
    /// EMPTY script (so no turn ever starts and nothing is drawn), and dumps the draw pile in order.
    ///
    /// This is the ground truth for <c>rd_oracle_shuffle</c>: the pile is dealt c0..cN-1 and then reordered by
    /// the engine's own CombatRandom call, so the dumped order must equal CreateShuffledIndexes(N, seed, 0)
    /// applied as ReorderDrawPile does it (new[i] = old[order[i]]). RandomStep must come out 1: exactly one
    /// step is consumed by the combat-start shuffle and none by anything else.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_shuffle_pile")]
    public static int ProbeShufflePile(int deckSize, int seed)
    {
        try
        {
            if (deckSize < 1 || deckSize > 64)
                throw new ArgumentOutOfRangeException(nameof(deckSize), "deckSize must be 1..64.");

            var fight = new ScenarioBlueprint { ShuffleDrawPileOnStart = true };
            for (var i = 0; i < deckSize; i++)
            {
                var id = "c" + i;
                fight.Cards.Add(new CardBlueprint(id)
                {
                    Program = new EffectProgram<CardPlayContext>(new NoOpEffectNode<CardPlayContext>()),
                });
                fight.Hero ??= new HeroBlueprint(HeroId) { MaxHealth = 20 };
                fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(id)));
            }
            fight.Enemies.Add(new EnemyBlueprint(EnemyId(0)) { MaxHealth = 12 });

            var report = RunFight(fight, new ScenarioScript().Build(), seed);
            if (report is null)
                return -1;

            CaptureState(report.FinalState, [], 0, playedSomething: false);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 2. expression arithmetic, through a real card program ───────────────────────────────────────────

    /// <summary>
    /// Plays a card whose damage AMOUNT is the expression under test, so the enemy's remaining HP reveals the
    /// expression's value (12 - value). op: 0 Abs(a), 1 Divide(a,b,policy c), 2 Remainder(a,b,policy c),
    /// 3 Clamp(a,b,c), 4 Add(a,b). c: 0 = ReturnZero, 1 = Fault.
    /// A Fault shows up as a reported problem with the enemy at full HP, which is why the caller must read
    /// rd_oracle_problems() as well as the HP.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_expr")]
    public static int ProbeExpr(int op, int a, int b, int c)
    {
        try
        {
            ICombatExpression<CardPlayContext, int> expression = op switch
            {
                0 => new AbsExpression<CardPlayContext>(Effects.Const(a)),
                1 => new DivideExpression<CardPlayContext>(Effects.Const(a), Effects.Const(b), Policy(c)),
                2 => new RemainderExpression<CardPlayContext>(Effects.Const(a), Effects.Const(b), Policy(c)),
                3 => new ClampExpression<CardPlayContext>(Effects.Const(a), Effects.Const(b), Effects.Const(c)),
                4 => new AddExpression<CardPlayContext>(Effects.Const(a), Effects.Const(b)),
                _ => throw new ArgumentOutOfRangeException(nameof(op)),
            };

            var fight = NewFight(20, 12, 1, 3, 5,
                new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, expression),
                cardCost: 0, shuffle: false);
            var report = RunFight(fight, PlayOnce(), 12345);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    private static DivideByZeroPolicy Policy(int c) =>
        c == 1 ? DivideByZeroPolicy.Fault : DivideByZeroPolicy.ReturnZero;

    // ── 3. conditional branch selection ────────────────────────────────────────────────────────────────

    /// <summary>
    /// A card that runs Conditional(constant condition, then, else?). elseDamage &lt; 0 means "no else branch".
    /// The enemy's HP says which branch ran: 12-then, 12-else, or 12 when neither did.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_conditional")]
    public static int ProbeConditional(int condition, int thenDamage, int elseDamage)
    {
        try
        {
            IEffectNode<CardPlayContext> then =
                new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, Effects.Const(thenDamage));
            IEffectNode<CardPlayContext>? otherwise =
                elseDamage < 0
                    ? null
                    : new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, Effects.Const(elseDamage));

            var fight = NewFight(20, 12, 1, 3, 5,
                new ConditionalEffectNode<CardPlayContext>(new BoolConst(condition != 0), then, otherwise),
                cardCost: 0, shuffle: false);
            var report = RunFight(fight, PlayOnce(), 12345);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    private sealed class BoolConst(bool value) : ICombatExpression<CardPlayContext, bool>
    {
        public bool Evaluate(EffectExecutionContext<CardPlayContext> context, CombatState combat) => value;
    }

    // ── 4. loops and their limits ──────────────────────────────────────────────────────────────────────

    /// <summary>
    /// A card whose program is Repeat(count, DealDamage(amount)), with the node's own maxCount. count = -1 or
    /// count &gt; maxCount must be reported as a fault by the runner, not silently clamped.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_repeat")]
    public static int ProbeRepeat(int count, int maxCount, int damage)
    {
        try
        {
            var fight = NewFight(20, 12, 1, 3, 5,
                new RepeatEffectNode<CardPlayContext>(
                    Effects.Const(count),
                    new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, Effects.Const(damage)),
                    maxCount: maxCount),
                cardCost: 0, shuffle: false);
            var report = RunFight(fight, PlayOnce(), 12345);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    /// <summary>
    /// The program-step ceiling. shape 0 = Repeat(4, Repeat(4, NoOp)); shape 1 = Repeat(3, NoOp) - the case the
    /// cited test says costs exactly 4 steps and therefore must NOT fault at maxProgramSteps 4. Only "did it
    /// throw" is observable from here: the step counter itself lives on the execution context, which card
    /// play constructs internally (so the exact ProgramStepCount value is out of this ABI's reach).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_program_steps")]
    public static int ProbeProgramSteps(int shape, int maxProgramSteps)
    {
        try
        {
            IEffectNode<CardPlayContext> root = shape == 0
                ? new RepeatEffectNode<CardPlayContext>(
                    Effects.Const(4),
                    new RepeatEffectNode<CardPlayContext>(Effects.Const(4), new NoOpEffectNode<CardPlayContext>()))
                : new RepeatEffectNode<CardPlayContext>(Effects.Const(3), new NoOpEffectNode<CardPlayContext>());

            var fight = NewFight(20, 12, 1, 3, 5,
                new NoOpEffectNode<CardPlayContext>(), cardCost: 0, shuffle: false);
            // The card's program is the loop under test, not the placeholder above.
            fight.Cards.Clear();
            fight.Cards.Add(new CardBlueprint(CardId)
            {
                Program = new EffectProgram<CardPlayContext>(root, maxProgramSteps: maxProgramSteps),
            });

            var report = RunFight(fight, PlayOnce(), 12345);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 5. ForEach over enemies, reading each target's own status ──────────────────────────────────────

    /// <summary>
    /// Three enemies with per-enemy HP and Poison stacks, and a card that walks every enemy and deals each
    /// POISONED one damage equal to its own stacks. One case pins three things at once: the loop reads each
    /// iteration target's state, the loop order is stable, and a target dying mid-iteration does not stop the
    /// ones behind it.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_for_each")]
    public static int ProbeForEach(int poison0, int poison1, int poison2,
                                   int hp0, int hp1, int hp2, int seed)
    {
        try
        {
            var program = new ForEachTargetEffectNode<CardPlayContext>(
                CombatantTargetSelectors.AllEnemiesOfSource,
                new ConditionalEffectNode<CardPlayContext>(
                    new IterationTargetHasStatusExpression<CardPlayContext>(StandardCombatIds.PoisonStatus),
                    new DealDamageNode<CardPlayContext>(
                        CombatantTargetSelectors.IterationTarget,
                        new IterationTargetStatusStacksExpression<CardPlayContext>(StandardCombatIds.PoisonStatus))));

            var fight = NewFight(20, 12, 3, 3, 5, program, cardCost: 0, shuffle: false);
            fight.Enemies.Clear();
            var poison = new[] { poison0, poison1, poison2 };
            var health = new[] { hp0, hp1, hp2 };
            for (var i = 0; i < 3; i++)
            {
                var foe = new EnemyBlueprint(EnemyId(i)) { MaxHealth = Math.Max(1, health[i]) };
                if (poison[i] > 0)
                    foe.StartingStatuses.Add(new StartingStatusSpec(StandardCombatIds.PoisonStatus, Stacks: poison[i]));
                fight.Enemies.Add(foe);
            }

            var report = RunFight(fight, PlayOnce(), seed);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 6. decrees (rules of combat carried by a status) ───────────────────────────────────────────────

    /// <summary>
    /// Wears a decree status and drives a turn boundary, so the rule is the only difference between runs.
    /// rule: 0 = NO decree at all (the control), 1 = UnspentResourceCarries, 2 = MaxHandSize(ruleAmount).
    /// variant: 0 = end the turn (turn-start refill fires, the hand is then discarded),
    ///          1 = play four cards then end the turn,
    ///          2 = play ONE free card and stop (starts the turn without ending it, so the opening draw is
    ///              still in hand when the state is read - which is the only way to observe a hand-size cap).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_decree")]
    public static int ProbeDecree(
        int rule, int ruleAmount, int startEnergy, int maxEnergy,
        int drawPerTurn, int deckSize, int cardCost, int enemyHp, int seed, int variant)
    {
        try
        {
            var fight = NewFight(20, enemyHp, 1, deckSize, drawPerTurn,
                new NoOpEffectNode<CardPlayContext>(), cardCost, shuffle: false, energy: startEnergy);
            fight.Hero!.Resources.Clear();
            fight.Hero.Resources.Add(
                new ResourceSpec(StandardCombatIds.EnergyResource, Current: startEnergy, Max: maxEnergy));

            if (rule != 0)
            {
                var decree = new StatusBlueprint("oracle.decree")
                {
                    Polarity = StatusPolarity.Buff,
                    StackingBehavior = StatusStackingBehavior.MergeWithExistingInstance,
                };
                decree.CombatRules.Add(new CombatRuleSpec(
                    rule == 2 ? CombatRule.MaxHandSize : CombatRule.UnspentResourceCarries,
                    Amount: ruleAmount));
                fight.Statuses.Add(decree);
                fight.Hero.StartingStatuses.Add(new StartingStatusSpec(decree.DefinitionId));
            }

            var script = new ScenarioScript();
            if (variant == 1)
            {
                for (var i = 0; i < 4; i++)
                    script.HeroPlays(CardId, EnemyId(0));
                script.HeroEndsTurn();
            }
            else if (variant == 2)
            {
                script.HeroPlays(CardId, EnemyId(0));
            }
            else
            {
                script.HeroEndsTurn();
            }

            var report = RunFight(fight, script.Build(), seed);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 7. the discard-pile reshuffle (the OTHER RNG consumer) ────────────────────────────────────────

    /// <summary>
    /// Draws out the whole pile, ends the turn (the hand is discarded), and wraps the round so the next
    /// opening draw finds an empty draw pile and must reshuffle the discard pile. That path consumes a
    /// random step of its own; the hand order it produces is the observation, and running the same call
    /// twice must produce the same hand, the same step and the same hash.
    ///
    /// The deck is one copy each of deckSize DISTINCT cards, so the hand's card ids spell out the reshuffled
    /// order instead of being N identical strings.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_reshuffle")]
    public static int ProbeReshuffle(int deckSize, int drawPerTurn, int seed)
    {
        try
        {
            if (deckSize < 1 || deckSize > 64)
                throw new ArgumentOutOfRangeException(nameof(deckSize), "deckSize must be 1..64.");

            var fight = new ScenarioBlueprint
            {
                CardsDrawnPerTurn = Math.Max(1, drawPerTurn),
                ShuffleDrawPileOnStart = false,
            };
            fight.Hero = new HeroBlueprint(HeroId) { MaxHealth = 20 };
            fight.Hero.Resources.Add(
                new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));
            for (var i = 0; i < deckSize; i++)
            {
                var id = "c" + i;
                fight.Cards.Add(new CardBlueprint(id)
                {
                    Program = new EffectProgram<CardPlayContext>(new NoOpEffectNode<CardPlayContext>()),
                });
                fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(id)));
            }
            fight.Enemies.Add(new EnemyBlueprint(EnemyId(0)) { MaxHealth = 12 });

            var script = new ScenarioScript().HeroEndsTurn().NextRound().Build();
            var report = RunFight(fight, script, seed);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 8. triggered-program firing order ─────────────────────────────────────────────────────────────

    /// <summary>
    /// Three triggers on the same event whose effects are distinguishable by their Block amount (id -&gt;
    /// amount: test.zzz 1, test.aaa 100, test.mmm 10000). They are registered in reverse id order, so the
    /// order the BlockGained entries appear in the combat log is the engine's real firing order — and the
    /// amounts in those log messages say which trigger each entry belongs to.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_trigger_order")]
    public static int ProbeTriggerOrder(int priorityZzz, int priorityAaa, int priorityMmm, int seed)
    {
        try
        {
            var fight = NewFight(20, 12, 1, 3, 5,
                new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, Effects.Const(1)),
                cardCost: 0, shuffle: false);

            Register("test.zzz", 1, priorityZzz);
            Register("test.aaa", 100, priorityAaa);
            Register("test.mmm", 10000, priorityMmm);

            var report = RunFight(fight, PlayOnce(), seed);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;

            void Register(string id, int block, int priority)
            {
                var program = new EffectProgram<DamageDealtTriggeredEffectContext>(
                    new GainBlockNode<DamageDealtTriggeredEffectContext>(
                        // The event target, NOT an explicit id: an explicit selector is allowed to name a
                        // DOWNED combatant, and GainBlock is a living-only operation, so the registry
                        // validator refuses that pairing (RDCP016). The event target is living-only by default.
                        CombatantTargetSelectors.EventTarget,
                        new ConstantExpression<DamageDealtTriggeredEffectContext>(block)));
                fight.TriggeredPrograms.Add(
                    TriggeredProgramContextAdapters.DamageDealt.Define(
                        new TriggeredEffectDefinitionId(id), program, priority: priority));
            }
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 9. snapshot / restore / JSON round trip ───────────────────────────────────────────────────────

    /// <summary>
    /// Plays a mid-fight board into existence, then asks whether the hash survives the trip:
    /// state -&gt; snapshot -&gt; Restore -&gt; snapshot must hash identically. Both hashes go into the text
    /// buffer and their agreement is rd_oracle_probe_ok().
    ///
    /// THE JSON HALF OF THE CITED TEST IS DELIBERATELY ABSENT. <c>CombatSaveJson</c> calls the reflection
    /// overloads of System.Text.Json, which (a) raise IL2026/IL3050 for this AOT project and (b) fail at
    /// RUNTIME here - measured: "Reflection-based serialization has been disabled for this application."
    /// Calling it would trade a clean AOT build for a probe that cannot run, so the save/load format is
    /// reported as NOT COVERED instead of quietly mis-measured.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_snapshot")]
    public static int ProbeSnapshot(int seed)
    {
        try
        {
            _probeOk = 0;
            var fight = NewFight(20, 12, 1, 5, 3,
                new DealDamageNode<CardPlayContext>(CombatantTargetSelectors.EventTarget, Effects.Const(3)),
                cardCost: 1, shuffle: true);
            fight.Hero!.StartingStatuses.Add(new StartingStatusSpec(StandardCombatIds.DexterityStatus, Stacks: 2));
            fight.Enemies[0].StartingStatuses.Add(
                new StartingStatusSpec(StandardCombatIds.StunStatus, DurationTurns: 1));
            var script = new ScenarioScript()
                .HeroPlays(CardId, EnemyId(0)).HeroEndsTurn().NextRound().Build();

            var report = RunFight(fight, script, seed);
            if (report is null)
                return -1;

            var state = report.FinalState;
            Capture(report);
            var direct = _hash;

            var restored = CombatState.Restore(state.CreateSnapshot());
            var viaRestore = CombatStateHasher.ComputeHash(restored.CreateSnapshot());

            _probeOk = direct == viaRestore ? 1 : 0;
            _detail += ";snap_direct=" + direct + ";snap_restore=" + viaRestore
                     + ";snap_restore_rstep=" + restored.RandomStep
                     + ";snap_restore_round=" + restored.CurrentRound
                     + ";snap_restore_energy=" + Resource(restored);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    private static int Resource(CombatState combat)
    {
        var hero = combat.GetCombatant(new CombatantId(HeroId));
        return hero.Resources.TryGetValue(StandardCombatIds.EnergyResource, out var pool) ? pool.Current : -1;
    }

    // ── 11. status application: prohibitions and amplifiers (decrees over incoming statuses) ──────────

    /// <summary>
    /// Two statuses decide what happens to a THIRD one on its way in: a prohibition eats it stack for
    /// stack, an amplifier enlarges the next application and is spent doing it. Both live on the status
    /// DEFINITION (StatusPreventionSpec / StatusAmplificationSpec), so they are authorable content and the
    /// engine's own Declarative*Interceptor does the work - no interceptor has to be written for this.
    ///
    /// kind 0: Toll 2 eats a 3-stack Fear stack for stack  -> Fear 1, Toll 0.
    /// kind 1: same board plus Charge 1 (Priority 10, RefusesWholeApplication) -> Fear 0, Charge 0, Toll 2.
    /// kind 2: Register 1 enlarges a 2-stack Curse by 1     -> Curse 3, Register 0.
    /// kind 3: Register 3 enlarges a 1-stack Curse by 1     -> Curse 2, Register 2.
    /// The applied-and-worn status stacks are read out of the detail string's heroStatuses field.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_intercept")]
    public static int ProbeIntercept(int kind, int seed)
    {
        try
        {
            var fear = new StatusBlueprint("oracle.fear") { Polarity = StatusPolarity.Debuff, UsesStacks = true };
            var curse = new StatusBlueprint("oracle.curse") { Polarity = StatusPolarity.Debuff, UsesStacks = true };
            var toll = new StatusBlueprint("oracle.toll")
            {
                Polarity = StatusPolarity.Buff,
                UsesStacks = true,
                Prevention = new StatusPreventionSpec(StatusPreventionScope.Debuffs, StacksPerStack: 1),
            };
            var charge = new StatusBlueprint("oracle.charge")
            {
                Polarity = StatusPolarity.Buff,
                UsesStacks = true,
                Prevention = new StatusPreventionSpec(
                    StatusPreventionScope.UnwantedByBearer, StacksPerStack: 1,
                    Priority: 10, RefusesWholeApplication: true),
            };
            var register = new StatusBlueprint("oracle.register")
            {
                Polarity = StatusPolarity.Neutral,
                UsesStacks = true,
                Amplification = new StatusAmplificationSpec(),
            };

            IEffectNode<CardPlayContext> program = kind switch
            {
                // A prohibition only has to be WORN to answer the application, so the card just sends it.
                0 or 1 => Effects.ApplyStatus(CombatantTargetSelectors.Source, fear.DefinitionId, 3),
                // The amplifier has to be worn BEFORE the enlarged application, and a Sequence's children
                // enqueue in order, so one card can stage both.
                2 => Effects.Sequence(
                    Effects.ApplyStatus(CombatantTargetSelectors.Source, register.DefinitionId, 1),
                    Effects.ApplyStatus(CombatantTargetSelectors.Source, curse.DefinitionId, 2)),
                3 => Effects.Sequence(
                    Effects.ApplyStatus(CombatantTargetSelectors.Source, register.DefinitionId, 3),
                    Effects.ApplyStatus(CombatantTargetSelectors.Source, curse.DefinitionId, 1)),
                _ => throw new ArgumentOutOfRangeException(nameof(kind)),
            };

            var fight = NewFight(50, 200, 1, 3, 5, program, cardCost: 0, shuffle: false);
            fight.Hero!.Resources.Clear();
            fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));
            fight.Statuses.Add(fear);
            fight.Statuses.Add(curse);
            fight.Statuses.Add(toll);
            fight.Statuses.Add(charge);
            fight.Statuses.Add(register);

            // The prohibition is worn ONLY for the prohibition cases: a Toll eats Debuffs, so leaving it on
            // during the amplification cases would swallow the very Curse the amplifier is supposed to enlarge.
            if (kind is 0 or 1)
            {
                fight.Hero.StartingStatuses.Add(new StartingStatusSpec(toll.DefinitionId, Stacks: 2));
                if (kind == 1)
                    fight.Hero.StartingStatuses.Add(new StartingStatusSpec(charge.DefinitionId, Stacks: 1));
            }

            var report = RunFight(fight, PlayOnce(), seed);
            if (report is null)
                return -1;

            Capture(report);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 10. the turn machine, driven directly (minimal registry) ──────────────────────────────────────

    /// <summary>
    /// The cited turn tests register ONLY a block handler, a damage handler and the Block pool — no standard
    /// package, so the only log entries are the ones the turn machine itself writes. That is what makes the
    /// log sequence decidable, and it also means this probe must build the CombatState by hand.
    ///
    /// variant 0: StartCurrentTurn then EndCurrentTurn (one combatant's turn).
    /// variant 1: same, but starting from the enemy, so the order wraps and the round advances.
    /// variant 2: StartCurrentTurn, queue GainBlock + DealDamage, EndCurrentTurn (effects drain first).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_turn")]
    public static int ProbeTurn(int heroHp, int enemyHp, int blockAmount, int damageAmount, int seed, int variant)
    {
        try
        {
            var builder = new CombatDefinitionRegistryBuilder();
            builder.RegisterEffectRequestHandler(new DealDamageEffectHandler());
            builder.RegisterEffectRequestHandler(new GainBlockEffectHandler());
            builder.RegisterDefensivePool(new DefensivePoolDefinition(
                StandardCombatIds.BlockDefensivePool, AbsorbPriority: 0, ClearsOnOwnerTurnStart: true));
            var registry = builder.Build();

            var heroId = new CombatantId(HeroId);
            var enemyId = new CombatantId(EnemyId(0));
            var combat = new CombatState(new CombatId("oracle_turn"), seed);
            combat.AddCombatant(new CombatantState(heroId,
                new CombatantDefinitionId("standard.hero"), "combatant.hero",
                StandardCombatIds.PlayerTeam, new HealthState(heroHp, heroHp)));
            combat.AddCombatant(new CombatantState(enemyId,
                new CombatantDefinitionId("standard.goblin"), "combatant.goblin",
                StandardCombatIds.EnemyTeam, new HealthState(enemyHp, enemyHp)));
            combat.SetActiveCombatant(variant == 1 ? enemyId : heroId);

            var turns = new CombatTurnProcessor();
            var queues = new CombatQueueProcessor();
            var problems = new List<string>();

            turns.StartCurrentTurn(combat, registry);
            if (variant == 2)
            {
                combat.EnqueueEffect(new GainBlockEffectRequest(heroId, blockAmount));
                combat.EnqueueEffect(new DealDamageEffectRequest(heroId, damageAmount));
            }
            turns.EndCurrentTurn(combat, registry);
            queues.ResolvePendingQueues(combat, registry);

            CaptureState(combat, problems, 0, playedSomething: false);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }
}
