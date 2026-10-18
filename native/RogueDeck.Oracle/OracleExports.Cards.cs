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
/// The PER-CARD oracle: one short fight per card in the content mirror, so the Rust kernel's per-card dump
/// (`kernel/rd-fightdump --cards`) can be diffed against the reference engine card by card
/// (`native/fight_diff.py`'s CARD_DIFF).
///
/// <para>
/// Why it cannot reuse <see cref="FightRun"/>: that one restates two cards by hand, and 62 hand restatements is
/// exactly the thing that rots. Instead this file reads <c>native/card_specs.json</c> — generated from the image
/// by <c>native/gen_card_specs.py</c> — and TRANSLATES it into the engine's typed nodes at run time. The image
/// stays the only source of truth: <c>fight_diff.py</c> re-derives every spec field from the mirror with
/// <c>tools/contentc/reader.py</c> and compares it against the facts this file reports from the AUTHORED
/// objects, and it also checks that the json on disk is not stale.
/// </para>
///
/// <para>
/// The translation is deliberately strict: an unknown node kind, selector, expression, zone, or a field this
/// file does not know how to author (a result key, an unrefusable-by status, a second trigger event) THROWS with
/// the card id and the json path. "Skip that card and carry on" would turn a hole into a green number.
/// </para>
///
/// <para>
/// The canonical program text is produced from the authored node objects, never from the json, so a bug in the
/// translator shows up as a text mismatch instead of vanishing. Its spelling must stay byte-identical to
/// <c>native/gen_card_specs.py</c>'s <c>node_text</c> — both sides spell every optional field explicitly,
/// because the image omits default-valued keys on the wire.
/// </para>
/// </summary>
public static partial class OracleExports
{
    // ── the fixed fight shape ────────────────────────────────────────────────────────────────────────
    // These numbers are NOT free: kernel/rd-fightdump/src/main.rs authors the same fight (its CARD_*
    // constants), and native/fight_diff.py compares the two header lines key by key before it compares a
    // single hash. Change one side and the gate goes red — which is the point.

    private const string CardCombatId = "card_diff";
    private const int CardSeed = 1;

    /// <summary>Same id as <see cref="FightHeroId"/>, so <see cref="CaptureFight"/>'s hero read is the right one.</summary>
    private const string CardHeroId = "hero";

    private const int CardHeroHp = 70;

    /// <summary>Authored (the image has no enemy table).</summary>
    private const string CardEnemyId = "queue_imp";

    /// <summary>High enough that no single card in the mirror can kill it (max single hit: damage 24 or paperwork×5).</summary>
    private const int CardEnemyHp = 500;

    /// <summary>Energy 10/10: the per-card fight asks what the card DOES, not whether it could be paid for.</summary>
    private const int CardEnergy = 10;

    /// <summary>
    /// The standard package's own refill amount (<c>StandardCombatPackage.cs:124</c>). Deliberately NOT
    /// registered here — the standard package installs it. A refill targets the pool's MAX when it has one
    /// (<c>ResourceEffects.cs</c>'s RefillResourceEffectHandler: `refillTarget = resource.Max ?? request.DefaultMax`),
    /// so with a 10/10 pool both sides refill to 10 whatever the default is. The kernel's mirror of that line is
    /// <c>turn.rs:438-449</c>.
    /// </summary>
    private const int CardEnergyRefill = 3;

    /// <summary>The image's one enemy action, authored so the enemy is not actionless (same choice as the fight oracle).</summary>
    private const string CardEnemyAction = "queue_imp.desk_jab";

    // ── storage ─────────────────────────────────────────────────────────────────────────────────────

    private static string _cardSpecsRaw = string.Empty;
    private static JsonDocument? _cardSpecsDoc;
    private static SpecCard[] _cardSpecs = [];
    private static SpecStatus[] _statusSpecs = [];
    private static string _cardSteps = string.Empty;
    private static string _cardFacts = string.Empty;

    // ── the spec model (mirrors native/gen_card_specs.py's output, nothing else) ─────────────────────

    private sealed record SpecCost(string Resource, int Amount);

    private sealed record SpecProgram(string Id, int Depth, int Steps, JsonElement Root);

    private sealed record SpecCard(
        int Index,
        string Id,
        string Package,
        SpecCost[] Costs,
        string[] Tags,
        CardZone PlayedZone,
        CardZone TurnEndZone,
        bool Retain,
        bool IsAction,
        bool QueueOnPlay,
        SpecProgram Program);

    private sealed record SpecModifier(
        PassiveModifierPipeline Pipeline,
        PassiveModifierOperation Operation,
        int Magnitude,
        int Priority,
        DamageKind? RestrictDamageKind);

    private sealed record SpecTrigger(string Event, SpecProgram Program);

    private sealed record SpecStatus(
        string Id,
        string Package,
        StatusPolarity Polarity,
        StatusStackingBehavior Stacking,
        string[] Tags,
        bool UsesStacks,
        bool UsesDuration,
        bool UsesCharges,
        SpecModifier[] Modifiers,
        SpecTrigger[] Triggers);

    /// <summary>One registered status trigger, kept so the facts can be rendered from the object that runs.</summary>
    private sealed record AuthoredTrigger(
        StatusDefinitionId Status, int Index, string Event,
        IEffectNode<DamageDealtTriggeredEffectContext> Root);

    // ── loading the spec ────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Reads <c>native/card_specs.json</c> from <paramref name="utf8Path"/> and translates it into the spec
    /// model. Returns the card count, or -1 (see `rd_oracle_error_*`).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_specs_load")]
    public static int CardSpecsLoad(IntPtr utf8Path)
    {
        _error = string.Empty;
        try
        {
            var path = Marshal.PtrToStringUTF8(utf8Path)
                       ?? throw new ArgumentNullException(nameof(utf8Path), "the spec path is not a UTF-8 string.");
            if (!File.Exists(path))
                throw new FileNotFoundException(
                    $"card specs not found: {path}\n  They are derived from the image, so generate them:\n"
                    + "    python native/gen_card_specs.py", path);
            var raw = File.ReadAllText(path, Encoding.UTF8);
            return LoadCardSpecsFromText(raw);
        }
        catch (Exception ex)
        {
            _cardSpecsDoc?.Dispose();
            _cardSpecsDoc = null;
            _cardSpecs = [];
            _statusSpecs = [];
            _cardSpecsRaw = string.Empty;
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    /// <summary>The json exactly as loaded — the diff compares it to the bytes on disk (a stale file is a bug).</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_specs_text_len")]
    public static int CardSpecsTextLen() => _cardSpecsRaw.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_specs_text_char")]
    public static int CardSpecsTextChar(int i) => i >= 0 && i < _cardSpecsRaw.Length ? _cardSpecsRaw[i] : -1;

    /// <summary>How many cards the loaded spec describes (-1 when nothing is loaded).</summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_count")]
    public static int CardCount() => _cardSpecsDoc is null ? -1 : _cardSpecs.Length;

    private static int LoadCardSpecsFromText(string raw)
    {
        _cardSpecsDoc?.Dispose();
        _cardSpecsDoc = JsonDocument.Parse(raw);
        _cardSpecsRaw = raw;

        var root = _cardSpecsDoc.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("card specs must be a json object at the root.");
        RejectUnknownKeys(root, ["format", "image", "image_bytes", "card_count", "statuses", "cards"], "spec");
        var format = Field(root, "format", "spec").GetInt32();
        if (format != 1)
            throw new InvalidOperationException(
                $"card specs format {format} — this build only understands format 1.");

        var statuses = new List<SpecStatus>();
        var statusIndex = 0;
        foreach (var element in Field(root, "statuses", "spec").EnumerateArray())
            statuses.Add(ReadStatus(element, $"spec.statuses[{statusIndex++}]"));

        var cards = new List<SpecCard>();
        var cardIndex = 0;
        foreach (var element in Field(root, "cards", "spec").EnumerateArray())
            cards.Add(ReadCard(element, $"spec.cards[{cardIndex++}]"));

        var declared = Field(root, "card_count", "spec").GetInt32();
        if (declared != cards.Count)
            throw new InvalidOperationException(
                $"card specs say card_count={declared} but carry {cards.Count} cards — the file is self-inconsistent.");

        // The card list order IS the index, and the index is how the Rust dump and this export agree on which
        // card is which. A hole or a shuffle here would silently compare card A against card B.
        for (var index = 0; index < cards.Count; index++)
            if (cards[index].Index != index)
                throw new InvalidOperationException(
                    $"card specs card #{index} carries index={cards[index].Index} — the list order and the index disagree.");

        _cardSpecs = [.. cards];
        _statusSpecs = [.. statuses];
        _error = string.Empty;
        return _cardSpecs.Length;
    }

    private static SpecStatus ReadStatus(JsonElement element, string where)
    {
        RequireKind(element, JsonValueKind.Object, where);
        RejectUnknownKeys(element, ["id", "package", "polarity", "stacking", "tags", "uses_stacks",
            "uses_duration", "uses_charges", "passive_modifiers", "triggers"], where);
        var modifiers = new List<SpecModifier>();
        var modifierIndex = 0;
        foreach (var item in Field(element, "passive_modifiers", where).EnumerateArray())
            modifiers.Add(ReadModifier(item, $"{where}.passive_modifiers[{modifierIndex++}]"));
        var triggers = new List<SpecTrigger>();
        var triggerIndex = 0;
        foreach (var item in Field(element, "triggers", where).EnumerateArray())
            triggers.Add(ReadTrigger(item, $"{where}.triggers[{triggerIndex++}]"));
        return new SpecStatus(
            Str(element, "id", where),
            Str(element, "package", where),
            EnumValue<StatusPolarity>(Str(element, "polarity", where), where + ".polarity"),
            EnumValue<StatusStackingBehavior>(Str(element, "stacking", where), where + ".stacking"),
            Strings(element, "tags", where),
            Bool(element, "uses_stacks", where),
            Bool(element, "uses_duration", where),
            Bool(element, "uses_charges", where),
            [.. modifiers],
            [.. triggers]);
    }

    private static SpecModifier ReadModifier(JsonElement element, string where)
    {
        RequireKind(element, JsonValueKind.Object, where);
        RejectUnknownKeys(element, ["pipeline", "operation", "magnitude", "priority", "restrictDamageKind"], where);
        var kindText = OptString(element, "restrictDamageKind", where);
        return new SpecModifier(
            EnumValue<PassiveModifierPipeline>(Str(element, "pipeline", where), where + ".pipeline"),
            EnumValue<PassiveModifierOperation>(Str(element, "operation", where), where + ".operation"),
            Int(element, "magnitude", where),
            Int(element, "priority", where),
            kindText is null ? null : EnumValue<DamageKind>(kindText, where + ".restrictDamageKind"));
    }

    private static SpecTrigger ReadTrigger(JsonElement element, string where)
    {
        RequireKind(element, JsonValueKind.Object, where);
        RejectUnknownKeys(element, ["event", "program"], where);
        return new SpecTrigger(Str(element, "event", where), ReadProgram(Field(element, "program", where), where + ".program"));
    }

    private static SpecProgram ReadProgram(JsonElement element, string where)
    {
        RequireKind(element, JsonValueKind.Object, where);
        RejectUnknownKeys(element, ["id", "depth", "steps", "root"], where);
        return new SpecProgram(
            Str(element, "id", where),
            Int(element, "depth", where),
            Int(element, "steps", where),
            Field(element, "root", where));
    }

    private static SpecCard ReadCard(JsonElement element, string where)
    {
        RequireKind(element, JsonValueKind.Object, where);
        RejectUnknownKeys(element, ["index", "id", "package", "costs", "tags", "played_zone", "turn_end_zone",
            "retain", "is_action", "queue_on_play", "lifecycle", "play_condition", "program"], where);
        // Two fields describe mechanisms this round does not author. They are "absent" in this image and the
        // spec carries their absence explicitly; a value here means authoring would be incomplete, so refuse.
        if (Int(element, "lifecycle", where) != 0)
            throw new InvalidOperationException($"{where}: lifecycle programmes are not authored by this build.");
        if (OptString(element, "play_condition", where) is not null)
            throw new InvalidOperationException($"{where}: play conditions are not authored by this build.");

        var costs = new List<SpecCost>();
        var costIndex = 0;
        foreach (var item in Field(element, "costs", where).EnumerateArray())
        {
            var costWhere = $"{where}.costs[{costIndex++}]";
            RequireKind(item, JsonValueKind.Object, costWhere);
            RejectUnknownKeys(item, ["resource", "amount"], costWhere);
            costs.Add(new SpecCost(Str(item, "resource", costWhere), Int(item, "amount", costWhere)));
        }
        return new SpecCard(
            Int(element, "index", where),
            Str(element, "id", where),
            Str(element, "package", where),
            [.. costs],
            Strings(element, "tags", where),
            EnumValue<CardZone>(Str(element, "played_zone", where), where + ".played_zone"),
            EnumValue<CardZone>(Str(element, "turn_end_zone", where), where + ".turn_end_zone"),
            Bool(element, "retain", where),
            Bool(element, "is_action", where),
            Bool(element, "queue_on_play", where),
            ReadProgram(Field(element, "program", where), where + ".program"));
    }

    // ── the export ──────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Authors every card (plus the statuses its programmes reference and the one enemy action), builds the
    /// fixed-shape fight with card #<paramref name="index"/> alone in the deck, plays it once, and stashes the
    /// observables + per-step hashes the diff reads. Returns the hash length, or -1.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_run")]
    public static int CardRun(int index, int seed)
    {
        _hash = string.Empty;
        _error = string.Empty;
        _detail = string.Empty;
        _cardSteps = string.Empty;
        _cardFacts = string.Empty;
        _played = -1;
        try
        {
            if (_cardSpecsDoc is null)
                throw new InvalidOperationException(
                    "no card specs are loaded — call rd_oracle_card_specs_load(path) first.");
            if (index < 0 || index >= _cardSpecs.Length)
                throw new ArgumentOutOfRangeException(nameof(index), $"index must be 0..{_cardSpecs.Length - 1}.");
            var selected = _cardSpecs[index];

            var triggers = new List<AuthoredTrigger>();
            var fight = AuthorBlueprint(triggers);

            fight.Hero = new HeroBlueprint(CardHeroId) { MaxHealth = CardHeroHp };
            fight.Hero.Resources.Add(new ResourceSpec(StandardCombatIds.EnergyResource, CardEnergy, CardEnergy));
            fight.Hero.Deck.Add(new DeckEntry(new CardDefinitionId(selected.Id), Count: 1));
            fight.ShuffleDrawPileOnStart = false;
            fight.CardsDrawnPerTurn = 5;

            var enemy = new EnemyBlueprint(CardEnemyId) { MaxHealth = CardEnemyHp };
            enemy.Actions.Add(new EnemyActionDefinitionId(CardEnemyAction));
            fight.Enemies.Add(enemy);

            var steps = new List<ScenarioStep> { new HeroPlaysCard(selected.Id, CardEnemyId) };

            // Facts are produced BEFORE the run: a run that throws must still be diagnosable.
            _cardFacts = CardFactsText(fight, selected, triggers);

            var report = new ScenarioRunner().Run(
                new Playthrough(fight, steps, combatId: CardCombatId, randomSeed: seed));

            _cardSteps = CardStepText(fight, steps, report, seed, out var lastHash);
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

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_steps_len")]
    public static int CardStepsLen() => _cardSteps.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_steps_char")]
    public static int CardStepsChar(int i) => i >= 0 && i < _cardSteps.Length ? _cardSteps[i] : -1;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_facts_len")]
    public static int CardFactsLen() => _cardFacts.Length;

    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_card_facts_char")]
    public static int CardFactsChar(int i) => i >= 0 && i < _cardFacts.Length ? _cardFacts[i] : -1;

    // ── authoring ───────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// The whole authored content: every card in the spec, every referenced status, and the enemy action.
    /// All 62 are authored on every run — not just the selected one — because a card programme may CREATE
    /// another card (`createCardInstance`), and a missing definition would fail at play time with a message
    /// about the wrong card.
    /// </summary>
    private static ScenarioBlueprint AuthorBlueprint(List<AuthoredTrigger> triggers)
    {
        var fight = new ScenarioBlueprint();

        foreach (var spec in _cardSpecs)
        {
            var where = "card(" + spec.Id + ")";
            var card = new CardBlueprint(spec.Id)
            {
                PackageId = spec.Package,
                Program = ProgramOf(spec.Program, where),
                PlayedCardDestinationZone = spec.PlayedZone,
                TurnEndHandDestinationZone = spec.TurnEndZone,
                RetainInHandOnTurnEnd = spec.Retain,
                IsAction = spec.IsAction,
                QueueOnPlay = spec.QueueOnPlay,
                PlayCondition = null,
            };
            foreach (var cost in spec.Costs)
                card.Costs.Add(new ResourceCost(new ResourceId(cost.Resource), cost.Amount));
            foreach (var tag in spec.Tags)
                card.Tags.Add(new TagId(tag));
            fight.Cards.Add(card);
        }

        foreach (var spec in _statusSpecs)
        {
            var where = "status(" + spec.Id + ")";
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

            var definitionId = new StatusDefinitionId(spec.Id);
            for (var index = 0; index < spec.Triggers.Length; index++)
            {
                var trigger = spec.Triggers[index];
                var triggerWhere = $"{where}.triggers[{index}]";
                if (trigger.Event != "DamageDealt")
                    throw new InvalidOperationException(
                        $"{triggerWhere}: trigger event `{trigger.Event}` is not authored by this build "
                        + "(only DamageDealt is; add the adapter here before letting the content through).");
                var program = new EffectProgram<DamageDealtTriggeredEffectContext>(
                    AuthorTriggerNode(trigger.Program.Root, triggerWhere + ".program.root"),
                    trigger.Program.Depth,
                    trigger.Program.Steps,
                    new EffectProgramId(trigger.Program.Id));
                // The registration shape is the reference's own (`StatusDataRebuild.cs:15-55`): id
                // "<status>_trigger<i>", gated on the status, filtered to the wearer as the event's source.
                fight.TriggeredPrograms.Add(TriggeredProgramContextAdapters.DamageDealt.Define(
                    new TriggeredEffectDefinitionId($"{spec.Id}_trigger{index}"),
                    program,
                    filters: [new DamageDealtSourceHasStatusTriggerFilter(definitionId)],
                    gatingStatus: definitionId));
                triggers.Add(new AuthoredTrigger(definitionId, index, trigger.Event, program.Root));
            }
        }

        fight.EnemyActions.Add(new EnemyActionBlueprint(
            CardEnemyAction, new ActionIntent("Desk Jab", IntentKind.Attack))
        {
            Program = new EffectProgram<EnemyActionContext>(
                new DealDamageNode<EnemyActionContext>(
                    CombatantTargetSelectors.EventTarget,
                    new ConstantExpression<EnemyActionContext>(8))),
        });

        return fight;
    }

    private static EffectProgram<CardPlayContext> ProgramOf(SpecProgram program, string where) =>
        new(AuthorNode(program.Root, where + ".program.root"), program.Depth, program.Steps,
            new EffectProgramId(program.Id));

    private static IEffectNode<CardPlayContext> AuthorNode(JsonElement node, string where)
    {
        RequireKind(node, JsonValueKind.Object, where);
        var kind = Str(node, "kind", where);
        switch (kind)
        {
            case "noop":
                RejectUnknownKeys(node, ["kind"], where);
                return new NoOpEffectNode<CardPlayContext>();
            case "sequence":
            {
                RejectUnknownKeys(node, ["kind", "children"], where);
                var children = new List<IEffectNode<CardPlayContext>>();
                var index = 0;
                foreach (var child in Field(node, "children", where).EnumerateArray())
                    children.Add(AuthorNode(child, $"{where}.children[{index++}]"));
                return new SequenceEffectNode<CardPlayContext>(children);
            }
            case "dealDamage":
            {
                RejectUnknownKeys(node, ["kind", "amount", "element", "ignoresBlock", "damageKind", "resultKey", "target"], where);
                RequireNoResultKey(node, where);
                var element = OptString(node, "element", where);
                return new DealDamageNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    AuthorExpression(Field(node, "amount", where), where + ".amount"),
                    resultKey: null,
                    ignoresBlock: Bool(node, "ignoresBlock", where),
                    element: element is null ? null : new ElementId(element),
                    kind: EnumValue<DamageKind>(Str(node, "damageKind", where), where + ".damageKind"));
            }
            case "applyStatus":
            {
                RejectUnknownKeys(node, ["kind", "charges", "duration", "resultKey", "source", "stacks", "status", "target"], where);
                RequireNoResultKey(node, where);
                var source = OptObject(node, "source", where);
                return new ApplyStatusNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    new StatusDefinitionId(Str(node, "status", where)),
                    AuthorExpression(Field(node, "stacks", where), where + ".stacks"),
                    durationTurns: Int(node, "duration", where),
                    charges: Int(node, "charges", where),
                    resultKey: null,
                    sourceSelector: source is { } from ? AuthorSelector(from, where + ".source") : null);
            }
            case "gainBlock":
            {
                RejectUnknownKeys(node, ["kind", "amount", "resultKey", "target"], where);
                RequireNoResultKey(node, where);
                return new GainBlockNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    AuthorExpression(Field(node, "amount", where), where + ".amount"),
                    resultKey: null);
            }
            case "drawCards":
            {
                RejectUnknownKeys(node, ["kind", "count", "resultKey", "target"], where);
                RequireNoResultKey(node, where);
                return new DrawCardsNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    AuthorExpression(Field(node, "count", where), where + ".count"),
                    resultKey: null);
            }
            case "gainResource":
            {
                RejectUnknownKeys(node, ["kind", "amount", "defaultMax", "resource", "resultKey", "target"], where);
                RequireNoResultKey(node, where);
                var defaultMax = OptInt(node, "defaultMax", where);
                return new GainResourceNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    new ResourceId(Str(node, "resource", where)),
                    AuthorExpression(Field(node, "amount", where), where + ".amount"),
                    defaultMax: defaultMax,
                    resultKey: null);
            }
            case "createCardInstance":
            {
                RejectUnknownKeys(node, ["kind", "card", "count", "resultKey", "target", "toZone"], where);
                RequireNoResultKey(node, where);
                return new CreateCardInstanceNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    new CardDefinitionId(Str(node, "card", where)),
                    EnumValue<CardZone>(Str(node, "toZone", where), where + ".toZone"),
                    AuthorExpression(Field(node, "count", where), where + ".count"),
                    resultKey: null);
            }
            case "forEachCardInZone":
            {
                RejectUnknownKeys(node, ["kind", "body", "definitionFilter", "maxIterations", "owner", "tagFilter", "takeFirst", "zone"], where);
                var definitionFilter = OptString(node, "definitionFilter", where);
                var tagFilter = OptString(node, "tagFilter", where);
                var takeFirst = OptInt(node, "takeFirst", where);
                return new ForEachCardInZoneNode<CardPlayContext>(
                    AuthorSelector(Field(node, "owner", where), where + ".owner"),
                    EnumValue<CardZone>(Str(node, "zone", where), where + ".zone"),
                    AuthorNode(Field(node, "body", where), where + ".body"),
                    definitionFilter: definitionFilter is null ? null : new CardDefinitionId(definitionFilter),
                    maxIterations: Int(node, "maxIterations", where),
                    tagFilter: tagFilter is null ? null : new TagId(tagFilter),
                    takeFirst: takeFirst);
            }
            case "moveCardToZone":
            {
                RejectUnknownKeys(node, ["kind", "card", "owner", "placement", "resultKey", "toZone"], where);
                RequireNoResultKey(node, where);
                return new MoveCardToZoneNode<CardPlayContext>(
                    AuthorSelector(Field(node, "owner", where), where + ".owner"),
                    AuthorCardExpression(Field(node, "card", where), where + ".card"),
                    EnumValue<CardZone>(Str(node, "toZone", where), where + ".toZone"),
                    resultKey: null,
                    placement: EnumValue<ZonePlacement>(Str(node, "placement", where), where + ".placement"));
            }
            case "modifyStatusStacks":
            {
                RejectUnknownKeys(node, ["kind", "delta", "resultKey", "status", "target"], where);
                RequireNoResultKey(node, where);
                return new ModifyStatusStacksNode<CardPlayContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    new StatusDefinitionId(Str(node, "status", where)),
                    AuthorExpression(Field(node, "delta", where), where + ".delta"),
                    resultKey: null);
            }
            default:
                throw new InvalidOperationException(
                    $"{where}: node kind `{kind}` is not authored by this build — add it to OracleExports.Cards.cs "
                    + "(and to native/gen_card_specs.py's node_text) instead of skipping the card.");
        }
    }

    private static IEffectNode<DamageDealtTriggeredEffectContext> AuthorTriggerNode(JsonElement node, string where)
    {
        RequireKind(node, JsonValueKind.Object, where);
        var kind = Str(node, "kind", where);
        switch (kind)
        {
            case "noop":
                RejectUnknownKeys(node, ["kind"], where);
                return new NoOpEffectNode<DamageDealtTriggeredEffectContext>();
            case "sequence":
            {
                RejectUnknownKeys(node, ["kind", "children"], where);
                var children = new List<IEffectNode<DamageDealtTriggeredEffectContext>>();
                var index = 0;
                foreach (var child in Field(node, "children", where).EnumerateArray())
                    children.Add(AuthorTriggerNode(child, $"{where}.children[{index++}]"));
                return new SequenceEffectNode<DamageDealtTriggeredEffectContext>(children);
            }
            case "modifyStatusStacks":
            {
                RejectUnknownKeys(node, ["kind", "delta", "resultKey", "status", "target"], where);
                RequireNoResultKey(node, where);
                return new ModifyStatusStacksNode<DamageDealtTriggeredEffectContext>(
                    AuthorSelector(Field(node, "target", where), where + ".target"),
                    new StatusDefinitionId(Str(node, "status", where)),
                    AuthorTriggerExpression(Field(node, "delta", where), where + ".delta"),
                    resultKey: null);
            }
            default:
                throw new InvalidOperationException(
                    $"{where}: trigger node kind `{kind}` is not authored by this build.");
        }
    }

    private static ICombatExpression<CardPlayContext, int> AuthorExpression(JsonElement expression, string where)
    {
        RequireKind(expression, JsonValueKind.Object, where);
        var kind = Str(expression, "kind", where);
        switch (kind)
        {
            case "const":
                RejectUnknownKeys(expression, ["kind", "value"], where);
                return new ConstantExpression<CardPlayContext>(Int(expression, "value", where));
            case "multiply":
                RejectUnknownKeys(expression, ["kind", "left", "right"], where);
                return new MultiplyExpression<CardPlayContext>(
                    AuthorExpression(Field(expression, "left", where), where + ".left"),
                    AuthorExpression(Field(expression, "right", where), where + ".right"));
            case "combatantStatusStacks":
                RejectUnknownKeys(expression, ["kind", "selector", "status"], where);
                return new CombatantStatusStacksExpression<CardPlayContext>(
                    AuthorSelector(Field(expression, "selector", where), where + ".selector"),
                    new StatusDefinitionId(Str(expression, "status", where)));
            default:
                throw new InvalidOperationException(
                    $"{where}: expression `{kind}` is not authored by this build.");
        }
    }

    private static ICombatExpression<DamageDealtTriggeredEffectContext, int> AuthorTriggerExpression(
        JsonElement expression, string where)
    {
        RequireKind(expression, JsonValueKind.Object, where);
        var kind = Str(expression, "kind", where);
        if (kind == "const")
        {
            RejectUnknownKeys(expression, ["kind", "value"], where);
            return new ConstantExpression<DamageDealtTriggeredEffectContext>(Int(expression, "value", where));
        }
        throw new InvalidOperationException($"{where}: trigger expression `{kind}` is not authored by this build.");
    }

    private static ICombatantTargetSelector AuthorSelector(JsonElement selector, string where)
    {
        RequireKind(selector, JsonValueKind.Object, where);
        RejectUnknownKeys(selector, ["kind"], where);
        return Str(selector, "kind", where) switch
        {
            "eventTarget" => CombatantTargetSelectors.EventTarget,
            "source" => CombatantTargetSelectors.Source,
            "allEnemies" => CombatantTargetSelectors.AllEnemiesOfSource,
            var other => throw new InvalidOperationException($"{where}: selector `{other}` is not authored by this build."),
        };
    }

    private static ICardInstanceExpression<CardPlayContext> AuthorCardExpression(JsonElement expression, string where)
    {
        RequireKind(expression, JsonValueKind.Object, where);
        RejectUnknownKeys(expression, ["kind"], where);
        return Str(expression, "kind", where) switch
        {
            "iterated" => new IteratedCardExpression<CardPlayContext>(),
            var other => throw new InvalidOperationException(
                $"{where}: card expression `{other}` is not authored by this build."),
        };
    }

    // ── per-step text ───────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// One line per step in `rd-fightdump`'s key=value shape (that is what the diff parses on both sides).
    /// Per-step hashes come from PREFIX REPLAYS, for the reason spelled out in OracleExports.Fight.cs: the
    /// runner has no cursor. A fresh runner per replay, because ScenarioRunner owns processors.
    /// </summary>
    private static string CardStepText(
        ScenarioBlueprint blueprint, List<ScenarioStep> steps, ScenarioReport report, int seed, out string lastHash)
    {
        var text = new StringBuilder();
        lastHash = string.Empty;
        for (var k = 1; k <= steps.Count; k++)
        {
            var prefix = new ScenarioRunner().Run(
                new Playthrough(blueprint, steps.GetRange(0, k), combatId: CardCombatId, randomSeed: seed));
            var state = prefix.FinalState;
            var step = report.Steps[k - 1];
            lastHash = HashOf(state);
            text.Append("step=").Append(k - 1)
                .Append(" round=").Append(step.Round)
                .Append(" turn=").Append(step.Turn)
                .Append(" problems=").Append(step.Problems.Count)
                .Append(" hero_hp=").Append(HpOf(state, CardHeroId))
                .Append(" enemy_hp=").Append(HpOf(state, CardEnemyId))
                .Append(" hash=").Append(lastHash)
                .Append('\n');
        }
        return text.ToString();
    }

    // ── facts text ──────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// The authored content as canonical `key=value` lines, read OUT of the blueprint objects (so a change to
    /// what will actually run changes this text). `native/fight_diff.py` re-derives every `card.*`, `status.*`
    /// and `enemy_action.*` line from the image and fails on any disagreement — including the fight SHAPE, so a
    /// hero HP of 69 instead of 70 cannot slip through as "just a different scenario".
    /// </summary>
    private static string CardFactsText(
        ScenarioBlueprint fight, SpecCard selected, List<AuthoredTrigger> triggers)
    {
        var text = new StringBuilder();

        for (var index = 0; index < fight.Cards.Count; index++)
        {
            Fact(text, $"cards.{index}.index", index.ToString());
            Fact(text, $"cards.{index}.id", fight.Cards[index].Id);
        }
        Fact(text, "card_count", fight.Cards.Count.ToString());
        Fact(text, "selected.index", Array.FindIndex(_cardSpecs, spec => spec.Id == selected.Id).ToString());
        Fact(text, "selected.id", selected.Id);

        foreach (var card in fight.Cards)
            CardFacts(text, card);

        foreach (var status in fight.Statuses)
        {
            var prefix = "status." + status.Id;
            Fact(text, prefix + ".package", status.PackageId);
            Fact(text, prefix + ".polarity", status.Polarity.ToString());
            Fact(text, prefix + ".stacking", status.StackingBehavior.ToString());
            Fact(text, prefix + ".tags", string.Join(",", status.Tags.Select(tag => tag.value)));
            Fact(text, prefix + ".uses_stacks", BoolText(status.UsesStacks));
            Fact(text, prefix + ".uses_duration", BoolText(status.UsesDuration));
            Fact(text, prefix + ".uses_charges", BoolText(status.UsesCharges));
            Fact(text, prefix + ".passive_modifiers", status.PassiveModifiers.Count.ToString());
            for (var index = 0; index < status.PassiveModifiers.Count; index++)
            {
                var spec = status.PassiveModifiers[index];
                Fact(text, $"{prefix}.modifier.{index}",
                    spec.Pipeline + ":" + spec.Operation + ":" + spec.Magnitude + ":" + spec.Priority + ":"
                    + (spec.RestrictDamageKind?.ToString() ?? "none"));
            }
            Fact(text, prefix + ".incoming_delay", status.IncomingStatusDelay is null ? "none" : "set");
            Fact(text, prefix + ".disclosure", status.Disclosure is null ? "none" : "set");
        }

        foreach (var trigger in triggers)
        {
            var prefix = "status." + trigger.Status.value + ".trigger." + trigger.Index;
            Fact(text, prefix + ".event", trigger.Event);
            Fact(text, prefix + ".program", TriggerNodeText(trigger.Root));
        }

        foreach (var action in fight.EnemyActions)
            EnemyActionFacts(text, action);

        // The mechanisms this fight does NOT use — the same pins the whole-fight gate uses, plus the shape.
        Fact(text, "content.cards_drawn_per_turn", fight.CardsDrawnPerTurn.ToString());
        Fact(text, "content.allies", fight.Allies.Count.ToString());
        Fact(text, "content.triggered_programs", fight.TriggeredPrograms.Count.ToString());
        Fact(text, "content.pre_down_interceptors", fight.PreDownInterceptors.Count.ToString());
        Fact(text, "content.status_application_interceptors", fight.StatusApplicationInterceptors.Count.ToString());
        Fact(text, "content.defensive_pools", fight.DefensivePools.Count.ToString());
        Fact(text, "content.turn_start_refills", fight.TurnStartResourceRefills.Count.ToString());
        Fact(text, "content.cell_exclusive", BoolText(fight.CellExclusive));
        Fact(text, "content.simultaneous_team_turns", BoolText(fight.SimultaneousTeamTurns));

        Fact(text, "shape.combat", CardCombatId);
        Fact(text, "shape.seed", CardSeed.ToString());
        Fact(text, "shape.shuffle", BoolText(fight.ShuffleDrawPileOnStart));
        Fact(text, "shape.hero", fight.Hero!.Id + "/" + fight.Hero!.MaxHealth);
        Fact(text, "shape.enemies", string.Join(",", fight.Enemies.Select(foe => foe.Id + "/" + foe.MaxHealth)));
        Fact(text, "shape.deck", string.Join(",", fight.Hero!.Deck.Select(entry => entry.Card.value + ":" + entry.Count)));
        Fact(text, "shape.energy",
            string.Join(",", fight.Hero!.Resources.Select(spec => spec.Resource.value + ":" + spec.Current + "/" + spec.Max)));
        Fact(text, "shape.energy_refill", CardEnergyRefill.ToString());
        Fact(text, "shape.steps", "1");
        Fact(text, "shape.step.0", "play:" + selected.Id + ":" + CardEnemyId);
        return text.ToString();
    }

    // ── json helpers (strict: a missing key is a failure, not a default) ────────────────────────────

    private static void RequireKind(JsonElement element, JsonValueKind kind, string where)
    {
        if (element.ValueKind != kind)
            throw new InvalidOperationException($"{where}: expected a json {kind}, got {element.ValueKind}.");
    }

    private static void RejectUnknownKeys(JsonElement element, string[] allowed, string where)
    {
        foreach (var property in element.EnumerateObject())
            if (Array.IndexOf(allowed, property.Name) < 0)
                throw new InvalidOperationException(
                    $"{where}: unknown field `{property.Name}` in card_specs.json (known: {string.Join(", ", allowed)}).");
        foreach (var name in allowed)
            if (!element.TryGetProperty(name, out _))
                throw new InvalidOperationException($"{where}: missing field `{name}` in card_specs.json.");
    }

    private static JsonElement Field(JsonElement element, string name, string where) =>
        element.TryGetProperty(name, out var value)
            ? value
            : throw new InvalidOperationException($"{where}: missing field `{name}` in card_specs.json.");

    private static JsonElement? OptObject(JsonElement element, string name, string where)
    {
        var value = Field(element, name, where);
        return value.ValueKind == JsonValueKind.Null ? null : value;
    }

    private static string Str(JsonElement element, string name, string where) =>
        Field(element, name, where).GetString()
        ?? throw new InvalidOperationException($"{where}: field `{name}` is null, expected a string.");

    private static string? OptString(JsonElement element, string name, string where)
    {
        var value = Field(element, name, where);
        return value.ValueKind == JsonValueKind.Null ? null : value.GetString();
    }

    private static int Int(JsonElement element, string name, string where) =>
        Field(element, name, where).GetInt32();

    private static int? OptInt(JsonElement element, string name, string where)
    {
        var value = Field(element, name, where);
        return value.ValueKind == JsonValueKind.Null ? null : value.GetInt32();
    }

    private static bool Bool(JsonElement element, string name, string where)
    {
        var value = Field(element, name, where);
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new InvalidOperationException($"{where}: field `{name}` is not a boolean."),
        };
    }

    private static string[] Strings(JsonElement element, string name, string where)
    {
        var list = new List<string>();
        foreach (var item in Field(element, name, where).EnumerateArray())
            list.Add(item.GetString() ?? throw new InvalidOperationException($"{where}: `{name}` holds a null."));
        return [.. list];
    }

    /// <summary>
    /// A result key is a data-flow slot other nodes read back; this build authors none, and silently dropping
    /// one would change the programme. Refuse instead.
    /// </summary>
    private static void RequireNoResultKey(JsonElement node, string where)
    {
        if (OptString(node, "resultKey", where) is not null)
            throw new InvalidOperationException(
                $"{where}: result keys are not authored by this build (the mirror has none; if that changed, "
                + "author the producer slot instead of dropping it).");
    }

    private static T EnumValue<T>(string text, string where) where T : struct, Enum
    {
        // Deliberately not Enum.TryParse: it also accepts numeric text ("3"), and a spec that names a value it
        // does not spell out is exactly the kind of drift this gate exists to catch.
        if (Array.IndexOf(Enum.GetNames<T>(), text) < 0)
            throw new InvalidOperationException(
                $"{where}: `{text}` is not a {typeof(T).Name} (known: {string.Join(", ", Enum.GetNames<T>())}).");
        return Enum.Parse<T>(text);
    }
}
