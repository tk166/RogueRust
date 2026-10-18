using System.Runtime.InteropServices;
using System.Text;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// The FIGHT oracle: authors one fight out of the CONTENT MIRROR's facts (not out of synthetic `strike`/`ogre`)
/// and answers it with the real engine, so the Rust kernel's whole-combat driver (`kernel/rd-fightdump`) can be
/// diffed against it hash-for-hash.
///
/// <para>
/// Why a new export instead of <c>rd_oracle_run</c>: card DEFINITION IDS go into the state hash, so both sides
/// have to fight with the same id, the same program, the same cost and the same destination zone. The kernel
/// cannot build a card program in Rust (its card definitions ARE the image), so the C# side has to restate the
/// image's facts by hand — and a hand restatement is exactly the thing that silently rots. Hence the second half
/// of this file: <c>rd_oracle_fight_facts_*</c> returns a canonical text derived from the AUTHORED
/// <see cref="ScenarioBlueprint"/> OBJECTS (not from a second copy of the numbers), and <c>native/fight_diff.py</c>
/// asserts it line-by-line against the image it reads with <c>tools/contentc/reader.py</c>. Mirror changes ⇒ the
/// gate goes red instead of the diff quietly comparing two different fights.
/// </para>
///
/// <para>
/// Per-step hashes: <see cref="ScenarioRunner.Run"/> always builds a fresh combat and <see cref="ScenarioReport"/>
/// has no cursor, so "the hash after step k" is taken from a PREFIX RUN (steps 0..k-1). That is not a second
/// driver: the engine is deterministic from (blueprint, seed) and every prefix replays from the same start, so a
/// k-step prefix ends in exactly the state a continuous run is in after k steps. The longest prefix's hash is
/// compared against the full run's own hash, so a broken prefix model reports a divergence instead of handing back
/// a plausible-looking hash.
/// </para>
/// </summary>
public static partial class OracleExports
{
    // ── the mirror's facts, restated here ────────────────────────────────────────────────────────────
    // Every constant below was measured out of tools/contentc/out/content.core.rdcf with tools/contentc/reader.py
    // and is RE-CHECKED against that image by native/fight_diff.py on every run. Change one of them and the gate
    // fails unless the image changed too.

    /// <summary>Hero combatant id (authored; the kernel's dump authors the same one).</summary>
    private const string FightHeroId = "hero";

    /// <summary>`CARD.Id` — root = `node.dealDamage` 6 at the event target, cost 1, lands in the discard pile.</summary>
    private const string PaperCutCard = "paper_cut";

    /// <summary>`CARD.Id` — root = `node.applyStatus paperwork 5` at the event target, cost 2.</summary>
    private const string PermitCard = "permit_a38";

    /// <summary>
    /// `CARD.Id` of a card that is deliberately NEITHER authored NOR dealt: the `refusals` script plays it to
    /// observe `CardNotInHand` ("the card is not in the hand" is not "the card is unknown"). Leaving it out of the
    /// registry is the honest statement that a play that never finds an instance never reaches a definition.
    /// </summary>
    private const string UnhandCard = "strong_binder";

    /// <summary>Enemy combatant id (authored — the image has no enemy table, only encounter rows).</summary>
    private const string QueueImp = "queue_imp";

    /// <summary>Second enemy of the `dot_kill` scenario (authored).</summary>
    private const string StampGoblin = "stamp_goblin";

    /// <summary>`EACT.Id` — root = `node.dealDamage` 8 at the event target, intent Kind Attack.</summary>
    private const string DeskJabAction = "queue_imp.desk_jab";

    /// <summary>`STATUS.Id` — Debuff, MergeWithExistingInstance, tags [damage_over_time], stacks only.</summary>
    private const string PaperworkStatus = "paperwork";

    // ── the exports' storage ────────────────────────────────────────────────────────────────────────

    private static string _fightSteps = string.Empty;
    private static string _fightFacts = string.Empty;
    private static string _fightLastPrefixHash = string.Empty;

    private readonly record struct FightStep(int Kind, string First, string? Second);

    private readonly record struct FightFoe(string Id, int Hp);

    private readonly record struct FightDeck(string Card, int Count);

    private sealed record FightScenario(
        string Name,
        string CombatId,
        int Seed,
        int HeroHp,
        FightFoe[] Enemies,
        FightDeck[] Deck,
        bool Shuffle,
        FightStep[] Steps);

    private const int StepPlay = 0;
    private const int StepEndTurn = 1;
    private const int StepEnemyActs = 2;
    private const int StepNextRound = 3;

    /// <summary>
    /// The four scenarios of `kernel/rd-fightdump/src/main.rs`, restated. The ORDER here is not the contract —
    /// `native/fight_diff.py` matches by NAME (`scenario.&lt;i&gt;.name=…` below) — but the CONTENT is: same combat
    /// id, same seed, same combatant ids and HP, same deck, same shuffle flag, same step list.
    /// </summary>
    private static FightScenario[] FightScenarios()
    {
        const int heroHp = 70;
        var play = new FightStep(StepPlay, PaperCutCard, QueueImp);
        var deskJab = new FightStep(StepEnemyActs, QueueImp, DeskJabAction);
        var endTurn = new FightStep(StepEndTurn, "", null);
        var nextRound = new FightStep(StepNextRound, "", null);
        return
        [
            new FightScenario(
                "finish", "city_easy_01", 7, heroHp,
                [new FightFoe(QueueImp, 22)],
                [new FightDeck(PaperCutCard, 12)],
                Shuffle: true,
                Steps: [play, play, play, nextRound, play]),

            new FightScenario(
                "enemy_hits", "enemy_hits", 1, heroHp,
                [new FightFoe(QueueImp, 22)],
                [new FightDeck(PaperCutCard, 2)],
                Shuffle: false,
                Steps: [endTurn, deskJab]),

            new FightScenario(
                "refusals", "refusals", 1, heroHp,
                [new FightFoe(QueueImp, 22)],
                [new FightDeck(PaperCutCard, 2)],
                Shuffle: false,
                Steps:
                [
                    new FightStep(StepPlay, UnhandCard, QueueImp),   // not in hand ⇒ CardNotInHand, no state change
                    play,
                    play,
                    deskJab,                                          // still the hero's turn ⇒ two problems
                ]),

            new FightScenario(
                "dot_kill", "dot_kill", 1, heroHp,
                [new FightFoe(QueueImp, 5), new FightFoe(StampGoblin, 22)],
                [new FightDeck(PermitCard, 5)],
                Shuffle: false,
                Steps:
                [
                    new FightStep(StepPlay, PermitCard, QueueImp),
                    endTurn,                                          // the DoT ticks at the imp's turn start
                    deskJab,                                          // the imp is already down ⇒ EnemyNotAlive
                ]),
        ];
    }

    // ── the export ──────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Authors the fight selected by <paramref name="variant"/> out of the mirror's facts, runs its script, and
    /// stashes the observables the diff reads. Returns the state hash's length, or -1 (see `rd_oracle_error_*`).
    ///
    /// <para>
    /// The final observables land in the SAME statics `rd_oracle_run_ex` already fills (`rd_oracle_hero_hp`,
    /// `rd_oracle_energy`, `rd_oracle_hand_count`, …, `rd_oracle_hash_*`), so there is no duplicate export family.
    /// Only what those cannot express is new: the per-step lines (<c>rd_oracle_fight_steps_*</c>) and the
    /// authored-facts text (<c>rd_oracle_fight_facts_*</c>).
    /// </para>
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_fight_run")]
    public static int FightRun(int variant, int seed)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _fightSteps = string.Empty;
        _fightFacts = string.Empty;
        _fightLastPrefixHash = string.Empty;
        _played = -1;
        try
        {
            var table = FightScenarios();
            if (variant < 0 || variant >= table.Length)
                throw new ArgumentOutOfRangeException(nameof(variant), $"variant must be 0..{table.Length - 1}.");
            var spec = table[variant];

            var blueprint = BuildFightBlueprint(spec);
            var steps = BuildFightSteps(spec);
            // Facts are produced BEFORE the run: a run that throws must still be diagnosable.
            _fightFacts = FightFacts(table, spec, blueprint, steps);

            var report = new ScenarioRunner().Run(
                new Playthrough(blueprint, steps, combatId: spec.CombatId, randomSeed: seed));

            _fightSteps = PerStepText(spec, blueprint, steps, report, seed, out _fightLastPrefixHash);
            CaptureFight(report);

            // The prefix replays must land on the full run's state, or "hash after step k" is a lie.
            var fullHash = HashOf(report.FinalState);
            if (!string.Equals(_fightLastPrefixHash, fullHash, StringComparison.Ordinal))
                throw new InvalidOperationException(
                    $"prefix replay diverged from the full run (prefix {_fightLastPrefixHash}, full {fullHash}).");
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    /// <summary>One line per step of the last <see cref="FightRun"/>, see <see cref="PerStepText"/>.</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_fight_steps_len")]
    public static int FightStepsLen() => _fightSteps.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_fight_steps_char")]
    public static int FightStepsChar(int i) => i >= 0 && i < _fightSteps.Length ? _fightSteps[i] : -1;

    /// <summary>
    /// The authored content described as canonical `key=value` lines — the half of the contract
    /// <c>native/fight_diff.py</c> checks against the image (see the class comment).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_fight_facts_len")]
    public static int FightFactsLen() => _fightFacts.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_fight_facts_char")]
    public static int FightFactsChar(int i) => i >= 0 && i < _fightFacts.Length ? _fightFacts[i] : -1;

    // ── authoring ───────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// The scenario blueprint: the two cards, the DoT status and the enemy action, all restated from the image,
    /// plus the hero / enemies / deck / shuffle this scenario authors.
    ///
    /// <para>
    /// Deliberately NOT set: <c>TurnStartResourceRefills</c> — the standard package already installs the energy
    /// refill (`StandardCombatPackage.cs:124`, `defaultMax: 3`), which is the same automation the kernel's turn
    /// machine performs from its `standard_turn_config()`. A second handler would refill twice.
    /// </para>
    /// </summary>
    private static ScenarioBlueprint BuildFightBlueprint(FightScenario spec)
    {
        // CardsDrawnPerTurn keeps its default (5) — the number both the standard package and the kernel's
        // standard_turn_config() use. Written out so a future default change cannot pass unnoticed.
        var fight = new ScenarioBlueprint { CardsDrawnPerTurn = 5 };

        // `paper_cut`: root = node.dealDamage(Amount const 6, Element null, IgnoresBlock false, ResultKey null,
        // TargetSelector sel.eventTarget); Program.Id "(unnamed)", MaxNodeDepth 64, MaxProgramSteps 1024 (the
        // EffectProgram defaults); Tags [attack, bureaucracy, action]; Costs [{Amount 1, standard.energy}];
        // RetainInHandOnTurnEnd false; TurnEnd- and PlayedCardDestinationZone DiscardPile; PackageId "scenario";
        // IsAction / QueueOnPlay / PlayCondition absent (⇒ false / false / null); LifecyclePrograms empty.
        var paperCut = new CardBlueprint(PaperCutCard)
        {
            Program = Effects.Program(Effects.DealDamage(CombatantTargetSelectors.EventTarget, 6)),
            PlayedCardDestinationZone = CardZone.DiscardPile,
            TurnEndHandDestinationZone = CardZone.DiscardPile,
            RetainInHandOnTurnEnd = false,
            IsAction = false,
            QueueOnPlay = false,
            PlayCondition = null,
        }.Cost(StandardCombatIds.EnergyResource, 1);
        paperCut.Tags.Add(new TagId("attack"));
        paperCut.Tags.Add(new TagId("bureaucracy"));
        paperCut.Tags.Add(new TagId("action"));
        fight.Cards.Add(paperCut);

        // `permit_a38`: root = node.applyStatus(Charges 0, DurationTurns 0, ResultKey null, Stacks const 5,
        // StatusDefinitionId paperwork, TargetSelector sel.eventTarget); Tags [bureaucracy, paperwork, form];
        // cost 2; zone DiscardPile.
        var permit = new CardBlueprint(PermitCard)
        {
            Program = Effects.Program(Effects.ApplyStatus(
                CombatantTargetSelectors.EventTarget,
                new StatusDefinitionId(PaperworkStatus),
                stacks: 5)),
            PlayedCardDestinationZone = CardZone.DiscardPile,
            TurnEndHandDestinationZone = CardZone.DiscardPile,
            RetainInHandOnTurnEnd = false,
            IsAction = false,
            QueueOnPlay = false,
            PlayCondition = null,
        }.Cost(StandardCombatIds.EnergyResource, 2);
        permit.Tags.Add(new TagId("bureaucracy"));
        permit.Tags.Add(new TagId("paperwork"));
        permit.Tags.Add(new TagId("form"));
        fight.Cards.Add(permit);

        // `paperwork`: Polarity Debuff, StackingBehavior MergeWithExistingInstance, Tags [damage_over_time], no
        // triggers, no passive modifiers, no death prevention / debuff block / incoming-status delay / disclosure,
        // UsesStacks true, UsesDuration false, UsesCharges false. The TAG is what makes it tick — the turn-start
        // automation matches StandardCombatIds.DamageOverTimeTag, not the id (StatusEffects.cs:449-475).
        var paperwork = new StatusBlueprint(PaperworkStatus)
        {
            Polarity = StatusPolarity.Debuff,
            StackingBehavior = StatusStackingBehavior.MergeWithExistingInstance,
            UsesStacks = true,
            UsesDuration = false,
            UsesCharges = false,
        };
        paperwork.Tags.Add(new TagId("damage_over_time"));
        fight.Statuses.Add(paperwork);

        // `queue_imp.desk_jab`: root = node.dealDamage(Amount const 8, Element null, IgnoresBlock false,
        // ResultKey null, TargetSelector sel.eventTarget); Intent Kind Attack. The image carries no intent LABEL
        // (the label is harness-only metadata the engine never sees), so one is authored for readability only.
        fight.EnemyActions.Add(new EnemyActionBlueprint(DeskJabAction, new ActionIntent("Desk Jab", IntentKind.Attack))
        {
            Program = new EffectProgram<EnemyActionContext>(
                new DealDamageNode<EnemyActionContext>(
                    CombatantTargetSelectors.EventTarget,
                    new ConstantExpression<EnemyActionContext>(8))),
        });

        fight.Hero = new HeroBlueprint(FightHeroId) { MaxHealth = spec.HeroHp };
        fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, Current: 3, Max: 3));
        foreach (var entry in spec.Deck)
            fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(entry.Card), Count: entry.Count));
        fight.ShuffleDrawPileOnStart = spec.Shuffle;

        foreach (var foe in spec.Enemies)
        {
            var enemy = new EnemyBlueprint(foe.Id) { MaxHealth = foe.Hp };
            enemy.Actions.Add(new EnemyActionDefinitionId(DeskJabAction));
            fight.Enemies.Add(enemy);
        }

        return fight;
    }

    private static List<ScenarioStep> BuildFightSteps(FightScenario spec)
    {
        var steps = new List<ScenarioStep>(spec.Steps.Length);
        foreach (var step in spec.Steps)
        {
            steps.Add(step.Kind switch
            {
                // The scripts only ever name the hero as a target, so EnemyActs' third field is the hero.
                StepPlay => new HeroPlaysCard(step.First, step.Second),
                StepEndTurn => new HeroEndsTurn(),
                StepEnemyActs => new EnemyActs(step.First, step.Second ?? string.Empty, FightHeroId),
                StepNextRound => new AdvanceToNextRound(),
                _ => throw new ArgumentOutOfRangeException(nameof(spec), $"unknown step kind {step.Kind}."),
            });
        }
        return steps;
    }

    // ── per-step text ───────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// One line per step in `rd-fightdump`'s key=value shape (that is what the diff parses on both sides):
    /// <c>step=&lt;i&gt; round=&lt;r&gt; turn=&lt;t&gt; problems=&lt;n&gt; hero_hp=&lt;n&gt; enemy_hp=&lt;a,b&gt;
    /// hash=&lt;64 hex&gt;</c>. `round`/`turn` are the PRE-execution context (`ScenarioRunner.cs:106,140,164,203`);
    /// the hash is the state AFTER the step.
    /// </summary>
    private static string PerStepText(
        FightScenario spec,
        ScenarioBlueprint blueprint,
        List<ScenarioStep> steps,
        ScenarioReport report,
        int seed,
        out string lastHash)
    {
        var text = new StringBuilder();
        lastHash = string.Empty;
        for (var k = 1; k <= steps.Count; k++)
        {
            // A FRESH runner per replay: ScenarioRunner owns a CombatTurnProcessor / CombatQueueProcessor pair,
            // and whether those are per-combat state is not something this export should assume.
            var prefix = new ScenarioRunner().Run(
                new Playthrough(blueprint, steps.GetRange(0, k), combatId: spec.CombatId, randomSeed: seed));
            var state = prefix.FinalState;
            var step = report.Steps[k - 1];
            lastHash = HashOf(state);
            text.Append("step=").Append(k - 1)
                .Append(" round=").Append(step.Round)
                .Append(" turn=").Append(step.Turn)
                .Append(" problems=").Append(step.Problems.Count)
                .Append(" hero_hp=").Append(HpOf(state, FightHeroId))
                .Append(" enemy_hp=").Append(EnemyHps(spec, state))
                .Append(" hash=").Append(lastHash)
                .Append('\n');
        }
        return text.ToString();
    }

    private static string HashOf(CombatState state) =>
        CombatStateHasher.ComputeHash(state.CreateSnapshot());

    private static int HpOf(CombatState state, string combatant) =>
        state.TryGetCombatant(new CombatantId(combatant), out var found) && found is not null
            ? found.Health.Current
            : -1;

    private static string EnemyHps(FightScenario spec, CombatState state) =>
        string.Join(",", spec.Enemies.Select(foe => HpOf(state, foe.Id)));

    // ── capture ─────────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Fills the observables the existing `rd_oracle_*` exports hand back. This is the same capture
    /// <c>rd_oracle_run_ex</c> does, with one difference that matters: the hero id is the blueprint's, not the
    /// hard-coded `"knight"` (the id goes into the hash, so it cannot be normalised away).
    /// </summary>
    private static void CaptureFight(ScenarioReport report)
    {
        var final = report.FinalState;
        var problemCount = report.Steps.Sum(step => step.Problems.Count);
        var snapshot = final.CreateSnapshot();

        _hash = CombatStateHasher.ComputeHash(snapshot);
        StoreHashInput(snapshot);
        _steps = report.Steps.Count;
        _problems = problemCount > 0 ? 1 : 0;
        _round = final.CurrentRound;
        _turn = final.CurrentTurn;
        _randomStep = final.RandomStep;
        _pending = final.PendingEffectCount;
        _logCount = final.CombatLog.Count;
        _phase = (int)final.TurnPhase;
        _result = (int)final.Result;
        _detail = string.Empty; // the rich detail string belongs to rd_oracle_run_ex, not here

        var heroId = new CombatantId(FightHeroId);
        var hero = final.GetCombatant(heroId);
        _heroHp = hero.Health.Current;
        _heroBlock = PoolOf(hero, StandardCombatIds.BlockDefensivePool);
        _heroWard = PoolOf(hero, WardPool);
        var energy = hero.Resources.TryGetValue(StandardCombatIds.EnergyResource, out var pool) ? pool : null;
        _energy = energy?.Current ?? -1;
        _energyMax = energy?.Max ?? -1;

        var zones = final.GetCardZones(heroId);
        _handCount = zones.Hand.Count;
        _drawCount = zones.DrawPile.Count;
        _discardCount = zones.DiscardPile.Count;
        _exhaustCount = zones.ExhaustPile.Count;
        _queueCount = zones.Queue.Count;

        for (var axis = 0; axis < HeroStacks.Length; axis++)
        {
            HeroStacks[axis] = StacksOf(hero, StatusAxis[axis]);
            EnemyStacks[axis] = 0;
        }

        _enemyHp = -1;
        _enemyBlock = 0;
        _enemyWard = 0;
        _enemyCount = 0;
        foreach (var combatant in final.Combatants)
        {
            if (combatant.TeamId != StandardCombatIds.EnemyTeam)
                continue;
            if (_enemyCount >= EnemyHpAt.Length)
                throw new InvalidOperationException("more enemies than the export's fixed tables can hold.");
            EnemyHpAt[_enemyCount] = combatant.Health.Current;
            EnemyBlockAt[_enemyCount] = PoolOf(combatant, StandardCombatIds.BlockDefensivePool);
            if (_enemyCount == 0)
            {
                _enemyHp = combatant.Health.Current;
                _enemyBlock = EnemyBlockAt[0];
                _enemyWard = PoolOf(combatant, WardPool);
                for (var axis = 0; axis < EnemyStacks.Length; axis++)
                    EnemyStacks[axis] = StacksOf(combatant, StatusAxis[axis]);
            }
            _enemyCount++;
        }
    }

    // ── facts text ──────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// The authored content as canonical `key=value` lines, read OUT of the blueprint objects (so a change to what
    /// will actually run changes this text). `native/fight_diff.py` re-derives every `card.*`, `status.*` and
    /// `enemy_action.*` line from `tools/contentc/out/content.core.rdcf` and fails on any disagreement.
    /// </summary>
    private static string FightFacts(
        FightScenario[] table, FightScenario selected, ScenarioBlueprint blueprint, List<ScenarioStep> steps)
    {
        var text = new StringBuilder();
        foreach (var card in blueprint.Cards)
            CardFacts(text, card);
        foreach (var status in blueprint.Statuses)
            StatusFacts(text, status);
        foreach (var action in blueprint.EnemyActions)
            EnemyActionFacts(text, action);

        // The mechanisms this fight does NOT use. They are part of the assumption: the image's `paperwork` has no
        // triggers, no passive modifiers, no death prevention and no debuff block, so authoring none of them is a
        // claim the gate can check.
        Fact(text, "content.cards_drawn_per_turn", blueprint.CardsDrawnPerTurn.ToString());
        Fact(text, "content.allies", blueprint.Allies.Count.ToString());
        Fact(text, "content.triggered_programs", blueprint.TriggeredPrograms.Count.ToString());
        Fact(text, "content.pre_down_interceptors", blueprint.PreDownInterceptors.Count.ToString());
        Fact(text, "content.status_application_interceptors", blueprint.StatusApplicationInterceptors.Count.ToString());
        Fact(text, "content.defensive_pools", blueprint.DefensivePools.Count.ToString());
        Fact(text, "content.turn_start_refills", blueprint.TurnStartResourceRefills.Count.ToString());
        Fact(text, "content.cell_exclusive", BoolText(blueprint.CellExclusive));
        Fact(text, "content.simultaneous_team_turns", BoolText(blueprint.SimultaneousTeamTurns));

        for (var index = 0; index < table.Length; index++)
            ScenarioFacts(text, index, table[index]);
        Fact(text, "selected", selected.Name);
        Fact(text, "selected.steps", steps.Count.ToString());
        return text.ToString();
    }

    private static void CardFacts(StringBuilder text, CardBlueprint card)
    {
        var prefix = "card." + card.Id;
        Fact(text, prefix + ".package", card.PackageId);
        Fact(text, prefix + ".costs", string.Join("+", card.Costs.Select(cost => cost.ResourceId.value + ":" + cost.Amount)));
        Fact(text, prefix + ".tags", string.Join(",", card.Tags.Select(tag => tag.value)));
        Fact(text, prefix + ".program", ProgramText(card.Program));
        Fact(text, prefix + ".played_zone", card.PlayedCardDestinationZone.ToString());
        Fact(text, prefix + ".turn_end_zone", card.TurnEndHandDestinationZone.ToString());
        Fact(text, prefix + ".retain", BoolText(card.RetainInHandOnTurnEnd));
        Fact(text, prefix + ".is_action", BoolText(card.IsAction));
        Fact(text, prefix + ".queue_on_play", BoolText(card.QueueOnPlay));
        Fact(text, prefix + ".lifecycle", card.LifecyclePrograms.Count.ToString());
        Fact(text, prefix + ".play_condition", card.PlayCondition is null ? "none" : "set");
    }

    private static void StatusFacts(StringBuilder text, StatusBlueprint status)
    {
        var prefix = "status." + status.Id;
        Fact(text, prefix + ".package", status.PackageId);
        Fact(text, prefix + ".polarity", status.Polarity.ToString());
        Fact(text, prefix + ".stacking", status.StackingBehavior.ToString());
        Fact(text, prefix + ".tags", string.Join(",", status.Tags.Select(tag => tag.value)));
        Fact(text, prefix + ".uses_stacks", BoolText(status.UsesStacks));
        Fact(text, prefix + ".uses_duration", BoolText(status.UsesDuration));
        Fact(text, prefix + ".uses_charges", BoolText(status.UsesCharges));
        // A status's own triggers are registered on the BLUEPRINT (fight.TriggeredPrograms), which
        // `content.triggered_programs` below already pins to 0 — so this line is only about the declarative half.
        Fact(text, prefix + ".passive_modifiers", status.PassiveModifiers.Count.ToString());
        Fact(text, prefix + ".incoming_delay", status.IncomingStatusDelay is null ? "none" : "set");
        Fact(text, prefix + ".disclosure", status.Disclosure is null ? "none" : "set");
        // NOT declared here (the gate has no image-side counterpart it can trust):
        //   CombatRules / Prevention / Amplification — they are the interceptor mechanisms, and
        //   `content.status_application_interceptors` / `content.pre_down_interceptors` below already pin
        //   that this fight registers none of them.
    }

    private static void EnemyActionFacts(StringBuilder text, EnemyActionBlueprint action)
    {
        var prefix = "enemy_action." + action.Id;
        Fact(text, prefix + ".package", action.PackageId);
        Fact(text, prefix + ".intent", action.Intent.Kind.ToString());
        Fact(text, prefix + ".program", ProgramText(action.Program));
    }

    private static void ScenarioFacts(StringBuilder text, int index, FightScenario spec)
    {
        var prefix = "scenario." + index;
        Fact(text, prefix + ".name", spec.Name);
        Fact(text, prefix + ".combat", spec.CombatId);
        Fact(text, prefix + ".seed", spec.Seed.ToString());
        Fact(text, prefix + ".shuffle", BoolText(spec.Shuffle));
        // Same separators the kernel's dump prints, so the diff can compare these strings verbatim.
        Fact(text, prefix + ".hero", FightHeroId + "/" + spec.HeroHp);
        Fact(text, prefix + ".enemies", string.Join(",", spec.Enemies.Select(foe => foe.Id + "/" + foe.Hp)));
        Fact(text, prefix + ".deck", string.Join(",", spec.Deck.Select(entry => entry.Card + ":" + entry.Count)));
        Fact(text, prefix + ".steps", spec.Steps.Length.ToString());
        for (var step = 0; step < spec.Steps.Length; step++)
            Fact(text, prefix + ".step." + step, StepText(spec.Steps[step]));
    }

    private static string StepText(FightStep step) => step.Kind switch
    {
        StepPlay => "play:" + step.First + ":" + (step.Second ?? "-"),
        StepEndTurn => "end_turn",
        StepEnemyActs => "enemy_acts:" + step.First + ":" + (step.Second ?? "-") + ":" + FightHeroId,
        StepNextRound => "next_round",
        _ => "unknown:" + step.Kind,
    };

    // ── canonical program text ─────────────────────────────────────────────────────────────────────
    // Both sides must produce the SAME string for the same program. The image's side is derived in
    // native/fight_diff.py from the decoded term tree; this side is derived from the node objects themselves.
    // Fields are listed in alphabetical order and every optional field has an explicit "none", because the image
    // omits default-valued keys on the wire and "absent" must not be distinguishable from "explicitly default".

    private static string ProgramText(EffectProgram<CardPlayContext>? program) =>
        program is null
            ? "none"
            : "program(id=" + program.Id.Value
              + ";depth=" + program.MaxNodeDepth
              + ";steps=" + program.MaxProgramSteps
              + ";root=" + NodeText(program.Root) + ")";

    private static string ProgramText(EffectProgram<EnemyActionContext>? program) =>
        program is null
            ? "none"
            : "program(id=" + program.Id.Value
              + ";depth=" + program.MaxNodeDepth
              + ";steps=" + program.MaxProgramSteps
              + ";root=" + NodeText(program.Root) + ")";

    private static string NodeText(IEffectNode<CardPlayContext>? node) => node switch
    {
        null => "none",
        NoOpEffectNode<CardPlayContext> => "noop",
        SequenceEffectNode<CardPlayContext> sequence =>
            "sequence(" + string.Join(",", sequence.Children.Select(NodeText)) + ")",
        DealDamageNode<CardPlayContext> damage =>
            "dealDamage(amount=" + AmountText(damage.Amount)
            + ";element=" + (damage.Element is { } element ? element.value : "none")
            + ";ignores_block=" + BoolText(damage.IgnoresBlock)
            + ";kind=" + damage.Kind
            + ";result_key=" + (damage.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(damage.TargetSelector) + ")",
        ApplyStatusNode<CardPlayContext> status =>
            "applyStatus(charges=" + status.Charges
            + ";duration=" + status.DurationTurns
            + ";result_key=" + (status.ResultKey is null ? "none" : "set")
            + ";source=" + (status.SourceSelector is null ? "none" : SelectorText(status.SourceSelector))
            + ";stacks=" + AmountText(status.Stacks)
            + ";status=" + status.StatusDefinitionId.value
            + ";target=" + SelectorText(status.TargetSelector) + ")",
        // ── the kinds the 62-card mirror actually uses (see native/card_specs.json) ──────────────────
        // Every field is spelled out, defaults included, because the image omits default-valued keys and
        // "absent" must equal "explicitly default". The order is alphabetical on purpose: the python side
        // (native/gen_card_specs.py's node_text) renders from the decoded term tree and cannot see the
        // order the constructor arguments happen to be in.
        GainBlockNode<CardPlayContext> block =>
            "gainBlock(amount=" + AmountText(block.Amount)
            + ";result_key=" + (block.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(block.TargetSelector) + ")",
        DrawCardsNode<CardPlayContext> draw =>
            "drawCards(count=" + AmountText(draw.Count)
            + ";result_key=" + (draw.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(draw.TargetSelector) + ")",
        GainResourceNode<CardPlayContext> resource =>
            "gainResource(amount=" + AmountText(resource.Amount)
            + ";default_max=" + (resource.DefaultMax?.ToString() ?? "none")
            + ";resource=" + resource.ResourceId.value
            + ";result_key=" + (resource.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(resource.TargetSelector) + ")",
        CreateCardInstanceNode<CardPlayContext> create =>
            "createCardInstance(card=" + create.CardDefinitionId.value
            + ";count=" + AmountText(create.Count)
            + ";result_key=" + (create.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(create.TargetSelector)
            + ";to_zone=" + create.ToZone + ")",
        ForEachCardInZoneNode<CardPlayContext> loop =>
            "forEachCardInZone(body=" + NodeText(loop.Body)
            + ";definition_filter=" + (loop.DefinitionFilter?.value ?? "none")
            + ";max_iterations=" + loop.MaxIterations
            + ";owner=" + SelectorText(loop.OwnerSelector)
            + ";tag_filter=" + (loop.TagFilter?.value ?? "none")
            + ";take_first=" + (loop.TakeFirst?.ToString() ?? "none")
            + ";zone=" + loop.Zone + ")",
        MoveCardToZoneNode<CardPlayContext> move =>
            "moveCardToZone(card=" + CardExpressionText(move.CardExpression)
            + ";owner=" + SelectorText(move.OwnerSelector)
            + ";placement=" + move.Placement
            + ";result_key=" + (move.ResultKey is null ? "none" : "set")
            + ";to_zone=" + move.ToZone + ")",
        ModifyStatusStacksNode<CardPlayContext> stacks =>
            "modifyStatusStacks(delta=" + AmountText(stacks.Delta)
            + ";result_key=" + (stacks.ResultKey is null ? "none" : "set")
            + ";status=" + stacks.StatusDefinitionId.value
            + ";target=" + SelectorText(stacks.TargetSelector) + ")",
        // An unmapped node is a MISMATCH, not a silent pass: the diff compares texts.
        _ => "unsupported(" + node.GetType().Name + ")",
    };

    /// <summary>
    /// A status trigger's program root, in the same canonical shape. Only the kinds a status trigger uses in
    /// this mirror are mapped; anything else renders `unsupported(…)` and goes red in the gate.
    /// </summary>
    private static string TriggerNodeText(IEffectNode<DamageDealtTriggeredEffectContext>? node) => node switch
    {
        null => "none",
        NoOpEffectNode<DamageDealtTriggeredEffectContext> => "noop",
        SequenceEffectNode<DamageDealtTriggeredEffectContext> sequence =>
            "sequence(" + string.Join(",", sequence.Children.Select(TriggerNodeText)) + ")",
        ModifyStatusStacksNode<DamageDealtTriggeredEffectContext> stacks =>
            "modifyStatusStacks(delta=" + AmountText(stacks.Delta)
            + ";result_key=" + (stacks.ResultKey is null ? "none" : "set")
            + ";status=" + stacks.StatusDefinitionId.value
            + ";target=" + SelectorText(stacks.TargetSelector) + ")",
        _ => "unsupported(" + node.GetType().Name + ")",
    };

    /// <summary>The card-instance side of a card op: only "the card this loop is on" occurs in the mirror.</summary>
    private static string CardExpressionText(ICardInstanceExpression<CardPlayContext> expression) => expression switch
    {
        IteratedCardExpression<CardPlayContext> => "iterated",
        _ => "unsupported(" + expression.GetType().Name + ")",
    };

    private static string NodeText(IEffectNode<EnemyActionContext>? node) => node switch
    {
        null => "none",
        NoOpEffectNode<EnemyActionContext> => "noop",
        SequenceEffectNode<EnemyActionContext> sequence =>
            "sequence(" + string.Join(",", sequence.Children.Select(NodeText)) + ")",
        DealDamageNode<EnemyActionContext> damage =>
            "dealDamage(amount=" + AmountText(damage.Amount)
            + ";element=" + (damage.Element is { } element ? element.value : "none")
            + ";ignores_block=" + BoolText(damage.IgnoresBlock)
            + ";kind=" + damage.Kind
            + ";result_key=" + (damage.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorText(damage.TargetSelector) + ")",
        _ => "unsupported(" + node.GetType().Name + ")",
    };

    private static string AmountText(ICombatExpression<CardPlayContext, int> expression) => expression switch
    {
        ConstantExpression<CardPlayContext> constant => "const(" + constant.Value + ")",
        MultiplyExpression<CardPlayContext> multiply =>
            "multiply(" + AmountText(multiply.Left) + "," + AmountText(multiply.Right) + ")",
        CombatantStatusStacksExpression<CardPlayContext> stacks =>
            "combatantStatusStacks(selector=" + SelectorText(stacks.Selector)
            + ";status=" + stacks.StatusId.value + ")",
        _ => "unsupported(" + expression.GetType().Name + ")",
    };

    private static string AmountText(ICombatExpression<EnemyActionContext, int> expression) => expression switch
    {
        ConstantExpression<EnemyActionContext> constant => "const(" + constant.Value + ")",
        _ => "unsupported(" + expression.GetType().Name + ")",
    };

    private static string AmountText(ICombatExpression<DamageDealtTriggeredEffectContext, int> expression) =>
        expression switch
        {
            ConstantExpression<DamageDealtTriggeredEffectContext> constant => "const(" + constant.Value + ")",
            _ => "unsupported(" + expression.GetType().Name + ")",
        };

    private static string SelectorText(ICombatantTargetSelector selector) =>
        ReferenceEquals(selector, CombatantTargetSelectors.Source) ? "source"
        : ReferenceEquals(selector, CombatantTargetSelectors.EventTarget) ? "eventTarget"
        : ReferenceEquals(selector, CombatantTargetSelectors.AllEnemiesOfSource) ? "allEnemies"
        : "unsupported(" + selector.GetType().Name + ")";

    // ── small helpers ──────────────────────────────────────────────────────────────────────────────

    private static void Fact(StringBuilder text, string key, string value) =>
        text.Append(key).Append('=').Append(value).Append('\n');

    private static string BoolText(bool value) => value ? "true" : "false";
}
