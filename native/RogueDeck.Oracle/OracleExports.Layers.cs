using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// The two layers that go BEYOND "one step per card": the cross-turn card layer (`CARD_MULTI`) and the
/// per-enemy-action layer (`ENEMY_DIFF`). Both are diffed against <c>kernel/rd-fightdump --cards-multi</c> and
/// <c>--enemies</c> by <c>native/fight_diff.py</c>.
///
/// <para>
/// Why these need their own file rather than more variants of <see cref="FightRun"/>: that one restates two cards
/// by hand, and 62 multi-step variants × 2 plus 394 enemy actions is exactly the thing that rots. Everything here
/// is TRANSLATED from <c>native/card_specs.json</c> — generated from the image by
/// <c>native/gen_card_specs.py</c>, re-derived from the image by <c>fight_diff.py</c> on every run — and every
/// fact reported back is read OUT of the authored objects, so a translator bug shows up as a text mismatch
/// instead of vanishing.
/// </para>
///
/// <para>
/// The enemy layer is the one that finally exercises the rest of the image's content: until it existed, 393 of the
/// image's 394 enemy actions had never been executed by anything. Actions whose programs need node/expression
/// kinds this build cannot author are NOT skipped silently: <see cref="EnemyRun"/> throws with the action id and
/// the json path, and <c>fight_diff.py</c> counts that action as "not authorable" (denominator included).
/// </para>
/// </summary>
public static partial class OracleExports
{
    // ── shapes (mirrored by kernel/rd-fightdump's CARD_MULTI_* / ENEMY_* constants and fight_diff.py) ──

    private const string CardMultiCombatId = "card_multi";
    private const int CardMultiSeed = 1;
    private const string CardMultiHeroId = "hero";
    private const int CardMultiHeroHp = 70;
    private const string CardMultiEnemyId = "queue_imp";
    private const int CardMultiEnemyHp = 500;
    private const int CardMultiEnergy = 3;
    private const string CardMultiAction = "queue_imp.desk_jab";

    /// <summary>Variant A: play it, end the turn, wrap a whole round, play it again.</summary>
    private const int MultiPlayAgain = 0;

    /// <summary>Variant B: play it, end the turn, let the enemy act, wrap back to the hero's turn.</summary>
    private const int MultiEnemyThenWrap = 1;
    private const int MultiVariants = 2;

    private const string EnemyCombatId = "enemy_diff";
    private const int EnemySeed = 1;
    private const string EnemyHeroId = "hero";
    private const int EnemyHeroHp = 70;
    private const int EnemyFightHp = 60;
    private const int EnemyEnergy = 3;

    // ── storage ─────────────────────────────────────────────────────────────────────────────────────

    private static string _multiSteps = string.Empty;
    private static string _multiFacts = string.Empty;
    private static string _enemySteps = string.Empty;
    private static string _enemyFacts = string.Empty;

    /// <summary>
    /// One registered status trigger, kept with the canonical text of its program (rendered from the typed node, so
    /// a translator bug shows up as a text mismatch rather than vanishing).
    /// </summary>
    private sealed record EnemyTrigger(StatusDefinitionId Status, int Index, string Event, string Text);

    // ═══════════════════════════════════════════════════════════════════════════════════════════════
    // Layer 1: per card × 2 multi-step variants
    // ═══════════════════════════════════════════════════════════════════════════════════════════════

    /// <summary>
    /// Authors the whole card content (exactly what <see cref="CardRun"/> authors — same
    /// <see cref="AuthorBlueprint"/> call, so the gate that verified it for `CARD_DIFF` covers this layer too),
    /// builds the cross-turn fight for card #<paramref name="index"/> / variant #<paramref name="variant"/>, and
    /// stashes the per-step hashes. Returns the hash length, or -1.
    ///
    /// <para>
    /// The seed is the fixed <see cref="CardMultiSeed"/> rather than an argument: the ABI is `(int, int)` and the
    /// two ints are the card index and the variant. The seed is still compared — it is part of the shape facts and
    /// of `rd-fightdump`'s header line.
    /// </para>
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_multi_run")]
    public static int CardMultiRun(int index, int variant)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _multiSteps = string.Empty;
        _multiFacts = string.Empty;
        _played = -1;
        try
        {
            if (_cardSpecsDoc is null)
                throw new InvalidOperationException(
                    "no card specs are loaded — call rd_oracle_card_specs_load(path) first.");
            if (index < 0 || index >= _cardSpecs.Length)
                throw new ArgumentOutOfRangeException(nameof(index), $"index must be 0..{_cardSpecs.Length - 1}.");
            if (variant < 0 || variant >= MultiVariants)
                throw new ArgumentOutOfRangeException(nameof(variant), $"variant must be 0..{MultiVariants - 1}.");
            var selected = _cardSpecs[index];

            var fight = MultiBlueprint();
            var steps = MultiSteps(selected, variant);
            var deckCount = variant == MultiPlayAgain ? 2 : 1;

            // Facts BEFORE the run: a run that throws must still be diagnosable.
            _multiFacts = MultiFactsText(fight, selected, variant, deckCount, steps);

            var report = new ScenarioRunner().Run(
                new Playthrough(fight, steps, combatId: CardMultiCombatId, randomSeed: CardMultiSeed));

            _multiSteps = MultiStepText(fight, steps, report, out var lastHash);
            CaptureFight(report);

            var fullHash = HashOf(report.FinalState);
            if (!string.Equals(lastHash, fullHash, StringComparison.Ordinal))
                throw new InvalidOperationException(
                    $"prefix replay diverged from the full run (prefix {lastHash}, full {fullHash}).");
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_multi_steps_len")]
    public static int CardMultiStepsLen() => _multiSteps.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_multi_steps_char")]
    public static int CardMultiStepsChar(int i) => i >= 0 && i < _multiSteps.Length ? _multiSteps[i] : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_multi_facts_len")]
    public static int CardMultiFactsLen() => _multiFacts.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_multi_facts_char")]
    public static int CardMultiFactsChar(int i) => i >= 0 && i < _multiFacts.Length ? _multiFacts[i] : -1;

    /// <summary>
    /// The cross-turn fight's content: the SAME authored blueprint the per-card layer uses (62 cards + the card
    /// statuses + the one enemy action), plus a 3/3 energy pool and a `queue_imp` whose only action is the image's
    /// `desk_jab`. Energy 3/3 (not 10/10) on purpose: the turn start's refill tops up to Max, and on a 10/10 pool
    /// that is the identity — the mechanism would be permanently green.
    /// </summary>
    private static ScenarioBlueprint MultiBlueprint()
    {
        var triggers = new List<AuthoredTrigger>();
        var fight = AuthorBlueprint(triggers);

        fight.Hero = new HeroBlueprint(CardMultiHeroId) { MaxHealth = CardMultiHeroHp };
        fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, CardMultiEnergy, CardMultiEnergy));
        fight.ShuffleDrawPileOnStart = false;
        fight.CardsDrawnPerTurn = 5;

        var enemy = new EnemyBlueprint(CardMultiEnemyId) { MaxHealth = CardMultiEnemyHp };
        enemy.Actions.Add(new EnemyActionDefinitionId(CardMultiAction));
        fight.Enemies.Add(enemy);
        return fight;
    }

    /// <summary>
    /// The 4 steps. Both variants cross a turn boundary; A also recycles the hand and reshuffles (deck 2 ⇒ the
    /// draw pile is empty on turn two), B lets the enemy hit the hero and then wraps back.
    /// </summary>
    private static List<ScenarioStep> MultiSteps(SpecCard card, int variant)
    {
        var play = new HeroPlaysCard(card.Id, CardMultiEnemyId);
        var steps = new List<ScenarioStep>();
        switch (variant)
        {
            case MultiPlayAgain:
                steps.Add(play);
                steps.Add(new HeroEndsTurn());
                steps.Add(new AdvanceToNextRound());
                steps.Add(new HeroPlaysCard(card.Id, CardMultiEnemyId));
                break;
            case MultiEnemyThenWrap:
                steps.Add(play);
                steps.Add(new HeroEndsTurn());
                steps.Add(new EnemyActs(CardMultiEnemyId, CardMultiAction, CardMultiHeroId));
                steps.Add(new AdvanceToNextRound());
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(variant), $"unknown multi variant {variant}.");
        }
        return steps;
    }

    /// <summary>
    /// The deck is authored here (not in <see cref="MultiBlueprint"/>) because it depends on the card under test
    /// and on the variant; the facts read it back out of the blueprint, which is why this has to be called before
    /// they are rendered.
    /// </summary>
    private static void AuthorMultiDeck(ScenarioBlueprint fight, SpecCard card, int deckCount)
    {
        fight.Hero!.Deck.Add(new DeckEntry(new CardDefinitionId(card.Id), deckCount));
    }

    private static string MultiStepText(
        ScenarioBlueprint blueprint, List<ScenarioStep> steps, ScenarioReport report, out string lastHash)
    {
        var text = new StringBuilder();
        lastHash = string.Empty;
        for (var k = 1; k <= steps.Count; k++)
        {
            var prefix = new ScenarioRunner().Run(
                new Playthrough(blueprint, steps.GetRange(0, k), combatId: CardMultiCombatId, randomSeed: CardMultiSeed));
            var state = prefix.FinalState;
            var snapshot = state.CreateSnapshot();
            var step = report.Steps[k - 1];
            lastHash = HashOf(state);
            text.Append("step=").Append(k - 1)
                .Append(" round=").Append(step.Round)
                .Append(" turn=").Append(step.Turn)
                .Append(" problems=").Append(step.Problems.Count)
                .Append(" hero_hp=").Append(HpOf(state, CardMultiHeroId))
                .Append(" enemy_hp=").Append(HpOf(state, CardMultiEnemyId))
                .Append(" chain=").Append(snapshot.NextEffectChainNumber)
                .Append(" exec=").Append(snapshot.NextProgramExecutionId)
                .Append(" hash=").Append(lastHash)
                .Append('\n');
        }
        return text.ToString();
    }

    private static string MultiFactsText(
        ScenarioBlueprint fight, SpecCard selected, int variant, int deckCount, List<ScenarioStep> steps)
    {
        // The deck is authored... here, so the shape below reads the object that will actually run.
        AuthorMultiDeck(fight, selected, deckCount);

        var text = new StringBuilder();
        Fact(text, "selected.index", selected.Index.ToString());
        Fact(text, "selected.id", selected.Id);
        Fact(text, "shape.combat", CardMultiCombatId);
        Fact(text, "shape.seed", CardMultiSeed.ToString());
        Fact(text, "shape.shuffle", BoolText(fight.ShuffleDrawPileOnStart));
        Fact(text, "shape.hero", fight.Hero!.Id + "/" + fight.Hero!.MaxHealth);
        Fact(text, "shape.enemies", string.Join(",", fight.Enemies.Select(foe => foe.Id + "/" + foe.MaxHealth)));
        Fact(text, "shape.deck", string.Join(",", fight.Hero!.Deck.Select(entry => entry.Card.value + ":" + entry.Count)));
        Fact(text, "shape.energy",
            string.Join(",", fight.Hero!.Resources.Select(spec => spec.Resource.value + ":" + spec.Current + "/" + spec.Max)));
        Fact(text, "shape.energy_refill", CardEnergyRefill.ToString());
        Fact(text, "shape.variant", variant.ToString());
        Fact(text, "shape.steps", steps.Count.ToString());
        for (var index = 0; index < steps.Count; index++)
            Fact(text, "shape.step." + index, StepTextOf(steps[index]));
        return text.ToString();
    }

    /// <summary>The same spelling <c>fight_diff.py</c> derives for the script (see its `step_text`).</summary>
    private static string StepTextOf(ScenarioStep step) => step switch
    {
        HeroPlaysCard play => "play:" + play.CardId + ":" + (play.TargetId ?? "-"),
        HeroEndsTurn => "end_turn",
        EnemyActs enemy => "enemy_acts:" + enemy.EnemyId + ":" + enemy.ActionId + ":" + enemy.TargetId,
        AdvanceToNextRound => "next_round",
        _ => "unsupported(" + step.GetType().Name + ")",
    };

    // ═══════════════════════════════════════════════════════════════════════════════════════════════
    // Layer 2: every enemy action in the image
    // ═══════════════════════════════════════════════════════════════════════════════════════════════

    /// <summary>How many enemy actions the loaded spec describes (-1 when nothing is loaded).</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_action_count")]
    public static int EnemyActionCount() => _cardSpecsDoc is null ? -1 : _enemySpecs.Length;

    /// <summary>
    /// Authors enemy action #<paramref name="index"/> (plus exactly the status definitions its program needs,
    /// triggers included), builds the fixed-shape fight with the action's owning enemy, and stashes the observables
    /// and per-step hashes. Returns the hash length, or -1 with <c>rd_oracle_error</c> explaining why — an action
    /// this build cannot author is a counted "not authorable", never a silent skip.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_run")]
    public static int EnemyRun(int index, int seed)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _enemySteps = string.Empty;
        _enemyFacts = string.Empty;
        _played = -1;
        try
        {
            if (_cardSpecsDoc is null)
                throw new InvalidOperationException(
                    "no card specs are loaded — call rd_oracle_card_specs_load(path) first.");
            if (index < 0 || index >= _enemySpecs.Length)
                throw new ArgumentOutOfRangeException(nameof(index), $"index must be 0..{_enemySpecs.Length - 1}.");
            var action = _enemySpecs[index];

            var triggers = new List<EnemyTrigger>();
            var fight = AuthorEnemyBlueprint(action, triggers);
            var steps = new List<ScenarioStep>
            {
                new HeroEndsTurn(),
                new EnemyActs(action.Enemy, action.Id, EnemyHeroId),
            };

            // Facts BEFORE the run: an authoring failure inside the run must still be diagnosable.
            _enemyFacts = EnemyFactsText(fight, action, triggers, steps, seed);

            var report = new ScenarioRunner().Run(
                new Playthrough(fight, steps, combatId: EnemyCombatId, randomSeed: seed));

            _enemySteps = EnemyStepText(fight, steps, action, report, seed, out var lastHash);
            CaptureFight(report);

            var fullHash = HashOf(report.FinalState);
            if (!string.Equals(lastHash, fullHash, StringComparison.Ordinal))
                throw new InvalidOperationException(
                    $"prefix replay diverged from the full run (prefix {lastHash}, full {fullHash}).");
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_steps_len")]
    public static int EnemyStepsLen() => _enemySteps.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_steps_char")]
    public static int EnemyStepsChar(int i) => i >= 0 && i < _enemySteps.Length ? _enemySteps[i] : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_facts_len")]
    public static int EnemyFactsLen() => _enemyFacts.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_enemy_facts_char")]
    public static int EnemyFactsChar(int i) => i >= 0 && i < _enemyFacts.Length ? _enemyFacts[i] : -1;

    /// <summary>
    /// The blueprint for one enemy action: no cards, no allies, no interceptor mechanisms, one hero (70), one
    /// enemy (its owner, 60 — high enough that a single 24-damage action cannot end the fight early), and the
    /// status definitions that action's program needs.
    ///
    /// <para>
    /// The statuses are authored WITH their triggers. That is not decoration: <c>panic</c> decays on TurnEnded,
    /// <c>fatigue</c> drains energy on TurnStarted, <c>bookworm</c> moves stacks around on TurnStarted, and
    /// <c>doubt</c> scales the wearer's damage on DamageDealt. Authoring the definition without the trigger would
    /// mean the reference runs a different fight — and it would stay invisible until a trigger happened to fire.
    /// </para>
    /// </summary>
    private static ScenarioBlueprint AuthorEnemyBlueprint(SpecEnemyAction action, List<EnemyTrigger> triggers)
    {
        var fight = new ScenarioBlueprint { CardsDrawnPerTurn = 5 };

        foreach (var statusId in action.Statuses)
        {
            var spec = _statusSpecs.FirstOrDefault(candidate => candidate.Id == statusId)
                       ?? throw new InvalidOperationException(
                           $"enemy action `{action.Id}` needs status `{statusId}`, but the spec does not describe it.");
            var status = new StatusBlueprint(spec.Id)
            {
                PackageId = spec.Package,
                Polarity = spec.Polarity,
                StackingBehavior = spec.Stacking,
                UsesStacks = spec.UsesStacks,
                UsesDuration = spec.UsesDuration,
                UsesCharges = spec.UsesCharges,
            };
            foreach (var tag in spec.Tags)
                status.Tags.Add(new TagId(tag));
            foreach (var modifier in spec.Modifiers)
                status.PassiveModifiers.Add(new PassiveModifierSpec(
                    modifier.Pipeline,
                    modifier.Operation,
                    modifier.Magnitude,
                    Priority: modifier.Priority,
                    RestrictDamageKind: modifier.RestrictDamageKind));
            fight.Statuses.Add(status);
            AuthorStatusTriggers(fight, spec, triggers);
        }

        fight.EnemyActions.Add(new EnemyActionBlueprint(
            action.Id, new ActionIntent(action.Id, EnumValue<IntentKind>(action.Intent, "enemy_action(" + action.Id + ").intent")))
        {
            PackageId = action.Package,
            Program = new EffectProgram<EnemyActionContext>(
                AuthorNode<EnemyActionContext>(action.Program.Root, "enemy_action(" + action.Id + ").program.root"),
                action.Program.Depth,
                action.Program.Steps,
                new EffectProgramId(action.Program.Id)),
        });

        fight.Hero = new HeroBlueprint(EnemyHeroId) { MaxHealth = EnemyHeroHp };
        fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, EnemyEnergy, EnemyEnergy));
        fight.ShuffleDrawPileOnStart = false;

        var enemy = new EnemyBlueprint(action.Enemy) { MaxHealth = EnemyFightHp };
        enemy.Actions.Add(new EnemyActionDefinitionId(action.Id));
        fight.Enemies.Add(enemy);
        return fight;
    }

    /// <summary>
    /// Registers one status's triggers on the blueprint, dispatching on the event. Three events occur in this
    /// image: DamageDealt, TurnStarted, TurnEnded — each has its own context adapter and its own "the wearer is the
    /// source" filter (<c>TriggeredProgramContextAdapters.cs:44-106</c>;
    /// <c>DamageDealtSourceHasStatusTriggerFilter</c>, <c>TurnStartedCombatantHasStatusTriggerFilter</c>,
    /// <c>TurnEndedCombatantHasStatusTriggerFilter</c>). The registration id is the reference's own
    /// "<c>&lt;status&gt;_trigger&lt;i&gt;</c>" (StatusDataRebuild.cs:15-55).
    /// </summary>
    private static void AuthorStatusTriggers(ScenarioBlueprint fight, SpecStatus spec, List<EnemyTrigger> into)
    {
        var definitionId = new StatusDefinitionId(spec.Id);
        for (var index = 0; index < spec.Triggers.Length; index++)
        {
            var trigger = spec.Triggers[index];
            var where = $"status({spec.Id}).triggers[{index}]";
            var root = trigger.Program.Root;
            var id = new TriggeredEffectDefinitionId($"{spec.Id}_trigger{index}");
            switch (trigger.Event)
            {
                case "DamageDealt":
                {
                    var node = AuthorNode<DamageDealtTriggeredEffectContext>(root, where + ".program.root");
                    var program = new EffectProgram<DamageDealtTriggeredEffectContext>(
                        node, trigger.Program.Depth, trigger.Program.Steps, new EffectProgramId(trigger.Program.Id));
                    fight.TriggeredPrograms.Add(TriggeredProgramContextAdapters.DamageDealt.Define(
                        id, program,
                        filters: [new DamageDealtSourceHasStatusTriggerFilter(definitionId)],
                        gatingStatus: definitionId));
                    into.Add(new EnemyTrigger(definitionId, index, trigger.Event, NodeTextOf(node)));
                    break;
                }
                case "TurnStarted":
                {
                    var node = AuthorNode<TurnStartedTriggeredEffectContext>(root, where + ".program.root");
                    var program = new EffectProgram<TurnStartedTriggeredEffectContext>(
                        node, trigger.Program.Depth, trigger.Program.Steps, new EffectProgramId(trigger.Program.Id));
                    fight.TriggeredPrograms.Add(TriggeredProgramContextAdapters.TurnStarted.Define(
                        id, program,
                        filters: [new TurnStartedCombatantHasStatusTriggerFilter(definitionId)],
                        gatingStatus: definitionId));
                    into.Add(new EnemyTrigger(definitionId, index, trigger.Event, NodeTextOf(node)));
                    break;
                }
                case "TurnEnded":
                {
                    var node = AuthorNode<TurnEndedTriggeredEffectContext>(root, where + ".program.root");
                    var program = new EffectProgram<TurnEndedTriggeredEffectContext>(
                        node, trigger.Program.Depth, trigger.Program.Steps, new EffectProgramId(trigger.Program.Id));
                    fight.TriggeredPrograms.Add(TriggeredProgramContextAdapters.TurnEnded.Define(
                        id, program,
                        filters: [new TurnEndedCombatantHasStatusTriggerFilter(definitionId)],
                        gatingStatus: definitionId));
                    into.Add(new EnemyTrigger(definitionId, index, trigger.Event, NodeTextOf(node)));
                    break;
                }
                default:
                    throw new InvalidOperationException(
                        $"{where}: trigger event `{trigger.Event}` is not authored by this build "
                        + "(DamageDealt / TurnStarted / TurnEnded are; add the adapter here before letting the "
                        + "content through).");
            }
        }
    }

    private static string EnemyStepText(
        ScenarioBlueprint blueprint,
        List<ScenarioStep> steps,
        SpecEnemyAction action,
        ScenarioReport report,
        int seed,
        out string lastHash)
    {
        var text = new StringBuilder();
        lastHash = string.Empty;
        for (var k = 1; k <= steps.Count; k++)
        {
            var prefix = new ScenarioRunner().Run(
                new Playthrough(blueprint, steps.GetRange(0, k), combatId: EnemyCombatId, randomSeed: seed));
            var state = prefix.FinalState;
            var snapshot = state.CreateSnapshot();
            var step = report.Steps[k - 1];
            lastHash = HashOf(state);
            text.Append("step=").Append(k - 1)
                .Append(" round=").Append(step.Round)
                .Append(" turn=").Append(step.Turn)
                .Append(" problems=").Append(step.Problems.Count)
                .Append(" hero_hp=").Append(HpOf(state, EnemyHeroId))
                .Append(" enemy_hp=").Append(HpOf(state, action.Enemy))
                .Append(" chain=").Append(snapshot.NextEffectChainNumber)
                .Append(" exec=").Append(snapshot.NextProgramExecutionId)
                .Append(" hash=").Append(lastHash)
                .Append('\n');
        }
        return text.ToString();
    }

    /// <summary>
    /// The authored action + the status facts + the shape, read out of the objects that will actually run.
    /// `fight_diff.py` re-derives every one of these lines from the image (`mirror_enemy_action_facts`,
    /// `mirror_status_facts`, `enemy_layer_expected`) and fails on any disagreement, in either direction.
    /// </summary>
    private static string EnemyFactsText(
        ScenarioBlueprint fight, SpecEnemyAction action, List<EnemyTrigger> triggers,
        List<ScenarioStep> steps, int seed)
    {
        var text = new StringBuilder();
        Fact(text, "selected.index", action.Index.ToString());
        Fact(text, "selected.id", action.Id);
        Fact(text, "selected.enemy", action.Enemy);
        Fact(text, "selected.listed", BoolText(action.Listed));

        foreach (var authored in fight.EnemyActions)
        {
            // NOT `EnemyActionFacts` (Fight.cs): that one renders the enemy program with a two-kind switch
            // (enough for `desk_jab`), which would report `unsupported(...)` for everything else. The canonical
            // text must come from the same generic renderer the mirror derivation uses.
            var prefix = "enemy_action." + authored.Id;
            Fact(text, prefix + ".package", authored.PackageId);
            Fact(text, prefix + ".intent", authored.Intent.Kind.ToString());
            Fact(text, prefix + ".program", ProgramTextOf(authored.Program));
        }

        foreach (var status in fight.Statuses)
            StatusFacts(text, status);
        foreach (var trigger in triggers)
        {
            var prefix = "status." + trigger.Status.value + ".trigger." + trigger.Index;
            Fact(text, prefix + ".event", trigger.Event);
            Fact(text, prefix + ".program", trigger.Text);
        }
        foreach (var status in fight.Statuses)
            for (var index = 0; index < status.PassiveModifiers.Count; index++)
            {
                var modifier = status.PassiveModifiers[index];
                Fact(text, $"status.{status.Id}.modifier.{index}",
                    modifier.Pipeline + ":" + modifier.Operation + ":" + modifier.Magnitude + ":"
                    + modifier.Priority + ":" + (modifier.RestrictDamageKind?.ToString() ?? "none"));
            }

        Fact(text, "content.allies", fight.Allies.Count.ToString());
        Fact(text, "content.triggered_programs", fight.TriggeredPrograms.Count.ToString());
        Fact(text, "content.pre_down_interceptors", fight.PreDownInterceptors.Count.ToString());
        Fact(text, "content.status_application_interceptors", fight.StatusApplicationInterceptors.Count.ToString());
        Fact(text, "content.defensive_pools", fight.DefensivePools.Count.ToString());
        Fact(text, "content.turn_start_refills", fight.TurnStartResourceRefills.Count.ToString());
        Fact(text, "content.cards_drawn_per_turn", fight.CardsDrawnPerTurn.ToString());
        Fact(text, "content.cell_exclusive", BoolText(fight.CellExclusive));
        Fact(text, "content.simultaneous_team_turns", BoolText(fight.SimultaneousTeamTurns));

        Fact(text, "shape.combat", EnemyCombatId);
        Fact(text, "shape.seed", seed.ToString());
        Fact(text, "shape.shuffle", BoolText(fight.ShuffleDrawPileOnStart));
        Fact(text, "shape.hero", fight.Hero!.Id + "/" + fight.Hero!.MaxHealth);
        Fact(text, "shape.enemies", string.Join(",", fight.Enemies.Select(foe => foe.Id + "/" + foe.MaxHealth)));
        Fact(text, "shape.deck",
            string.Join(",", fight.Hero!.Deck.Select(entry => entry.Card.value + ":" + entry.Count)));
        Fact(text, "shape.energy",
            string.Join(",", fight.Hero!.Resources.Select(spec => spec.Resource.value + ":" + spec.Current + "/" + spec.Max)));
        Fact(text, "shape.energy_refill", CardEnergyRefill.ToString());
        Fact(text, "shape.steps", steps.Count.ToString());
        for (var index = 0; index < steps.Count; index++)
            Fact(text, "shape.step." + index, StepTextOf(steps[index]));
        return text.ToString();
    }

    // ═══════════════════════════════════════════════════════════════════════════════════════════════
    // Canonical program text, generic over the effect context
    //
    // Byte-identical to native/gen_card_specs.py's node_text / expression_text / condition_text.
    // Fields alphabetical, every optional field explicitly "none" (the image omits default-valued keys,
    // so "absent" must not be distinguishable from "explicitly default").
    // ═══════════════════════════════════════════════════════════════════════════════════════════════

    private static string ProgramTextOf<TContext>(EffectProgram<TContext>? program) where TContext : class =>
        program is null
            ? "none"
            : "program(id=" + program.Id.Value
              + ";depth=" + program.MaxNodeDepth
              + ";steps=" + program.MaxProgramSteps
              + ";root=" + NodeTextOf(program.Root) + ")";

    private static string NodeTextOf<TContext>(IEffectNode<TContext>? node) where TContext : class => node switch
    {
        null => "none",
        NoOpEffectNode<TContext> => "noop",
        SequenceEffectNode<TContext> sequence =>
            "sequence(" + string.Join(",", sequence.Children.Select(NodeTextOf)) + ")",
        DealDamageNode<TContext> damage =>
            "dealDamage(amount=" + AmountTextOf(damage.Amount)
            + ";element=" + (damage.Element is { } element ? element.value : "none")
            + ";ignores_block=" + BoolText(damage.IgnoresBlock)
            + ";kind=" + damage.Kind
            + ";result_key=" + (damage.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(damage.TargetSelector) + ")",
        ApplyStatusNode<TContext> apply =>
            "applyStatus(charges=" + apply.Charges
            + ";duration=" + apply.DurationTurns
            + ";result_key=" + (apply.ResultKey is null ? "none" : "set")
            + ";source=" + (apply.SourceSelector is null ? "none" : SelectorTextOf(apply.SourceSelector))
            + ";stacks=" + AmountTextOf(apply.Stacks)
            + ";status=" + apply.StatusDefinitionId.value
            + ";target=" + SelectorTextOf(apply.TargetSelector) + ")",
        GainBlockNode<TContext> block =>
            "gainBlock(amount=" + AmountTextOf(block.Amount)
            + ";result_key=" + (block.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(block.TargetSelector) + ")",
        DrawCardsNode<TContext> draw =>
            "drawCards(count=" + AmountTextOf(draw.Count)
            + ";result_key=" + (draw.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(draw.TargetSelector) + ")",
        GainResourceNode<TContext> gain =>
            "gainResource(amount=" + AmountTextOf(gain.Amount)
            + ";default_max=" + (gain.DefaultMax?.ToString() ?? "none")
            + ";resource=" + gain.ResourceId.value
            + ";result_key=" + (gain.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(gain.TargetSelector) + ")",
        LoseResourceNode<TContext> lose =>
            "loseResource(amount=" + AmountTextOf(lose.Amount)
            + ";resource=" + lose.ResourceId.value
            + ";result_key=" + (lose.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(lose.TargetSelector) + ")",
        CreateCardInstanceNode<TContext> create =>
            "createCardInstance(card=" + create.CardDefinitionId.value
            + ";count=" + AmountTextOf(create.Count)
            + ";result_key=" + (create.ResultKey is null ? "none" : "set")
            + ";target=" + SelectorTextOf(create.TargetSelector)
            + ";to_zone=" + create.ToZone + ")",
        ForEachCardInZoneNode<TContext> loop =>
            "forEachCardInZone(body=" + NodeTextOf(loop.Body)
            + ";definition_filter=" + (loop.DefinitionFilter is { } filter ? filter.value : "none")
            + ";max_iterations=" + loop.MaxIterations
            + ";owner=" + SelectorTextOf(loop.OwnerSelector)
            + ";tag_filter=" + (loop.TagFilter is { } tag ? tag.value : "none")
            + ";take_first=" + (loop.TakeFirst?.ToString() ?? "none")
            + ";zone=" + loop.Zone + ")",
        MoveCardToZoneNode<TContext> move =>
            "moveCardToZone(card=" + CardExpressionTextOf(move.CardExpression)
            + ";owner=" + SelectorTextOf(move.OwnerSelector)
            + ";placement=" + move.Placement
            + ";result_key=" + (move.ResultKey is null ? "none" : "set")
            + ";to_zone=" + move.ToZone + ")",
        ModifyStatusStacksNode<TContext> stacks =>
            "modifyStatusStacks(delta=" + AmountTextOf(stacks.Delta)
            + ";result_key=" + (stacks.ResultKey is null ? "none" : "set")
            + ";status=" + stacks.StatusDefinitionId.value
            + ";target=" + SelectorTextOf(stacks.TargetSelector) + ")",
        SetCombatantCounterNode<TContext> counter =>
            "setCombatantCounter(amount=" + AmountTextOf(counter.Amount)
            + ";counter=" + counter.CounterId.value
            + ";relative=" + BoolText(counter.Relative)
            + ";target=" + SelectorTextOf(counter.TargetSelector) + ")",
        ConditionalEffectNode<TContext> conditional =>
            "conditional(condition=" + ConditionTextOf(conditional.Condition)
            + ";else=" + NodeTextOf(conditional.Else)
            + ";then=" + NodeTextOf(conditional.Then) + ")",
        _ => "unsupported(" + node.GetType().Name + ")",
    };

    private static string AmountTextOf<TContext>(ICombatExpression<TContext, int> expression) where TContext : class =>
        expression switch
        {
            ConstantExpression<TContext> constant => "const(" + constant.Value + ")",
            MultiplyExpression<TContext> multiply =>
                "multiply(" + AmountTextOf(multiply.Left) + "," + AmountTextOf(multiply.Right) + ")",
            AddExpression<TContext> add =>
                "add(" + AmountTextOf(add.Left) + "," + AmountTextOf(add.Right) + ")",
            SubtractExpression<TContext> subtract =>
                "subtract(" + AmountTextOf(subtract.Left) + "," + AmountTextOf(subtract.Right) + ")",
            MinExpression<TContext> min =>
                "min(" + AmountTextOf(min.Left) + "," + AmountTextOf(min.Right) + ")",
            DivideExpression<TContext> divide =>
                "divide(" + AmountTextOf(divide.Dividend) + "," + AmountTextOf(divide.Divisor)
                + "," + divide.ZeroPolicy + ")",
            CombatantStatusStacksExpression<TContext> stacks =>
                "combatantStatusStacks(selector=" + SelectorTextOf(stacks.Selector)
                + ";status=" + stacks.StatusId.value + ")",
            CombatantCounterExpression<TContext> counter =>
                "combatantCounter(counter=" + counter.CounterId.value
                + ";selector=" + SelectorTextOf(counter.Selector) + ")",
            _ => "unsupported(" + expression.GetType().Name + ")",
        };

    private static string ConditionTextOf<TContext>(ICombatExpression<TContext, bool> condition) where TContext : class =>
        condition is ComparisonExpression<TContext> compare
            ? "compare(left=" + AmountTextOf(compare.Left) + ";op=" + compare.Op
              + ";right=" + AmountTextOf(compare.Right) + ")"
            : "unsupported(" + condition.GetType().Name + ")";

    private static string CardExpressionTextOf<TContext>(ICardInstanceExpression<TContext> expression)
        where TContext : class =>
        expression is IteratedCardExpression<TContext> ? "iterated" : "unsupported(" + expression.GetType().Name + ")";

    /// <summary>
    /// Selector spelling. `allAllies` is the fourth kind the image writes — and the only one that carries neither
    /// Cardinality nor RequiredContextCapabilities (`sel.rs:133` measures 4 of 24 with those fields; the kernel
    /// reports the same fact from the other side).
    /// </summary>
    private static string SelectorTextOf(ICombatantTargetSelector selector) =>
        ReferenceEquals(selector, CombatantTargetSelectors.Source) ? "source"
        : ReferenceEquals(selector, CombatantTargetSelectors.EventTarget) ? "eventTarget"
        : ReferenceEquals(selector, CombatantTargetSelectors.AllEnemiesOfSource) ? "allEnemies"
        : ReferenceEquals(selector, CombatantTargetSelectors.AllAlliesOfSource) ? "allAllies"
        : "unsupported(" + selector.GetType().Name + ")";
}
