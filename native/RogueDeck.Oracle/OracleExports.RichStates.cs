using System.Collections.Immutable;
using System.Runtime.InteropServices;
using RogueDeck.Core.Combat;
using RogueDeck.Scenario.Authoring;
using RogueDeck.Scenario.Dsl;
using RogueDeck.Scenario.Reporting;
using RogueDeck.Scenario.Scripting;

namespace RogueDeck.Oracle;

/// <summary>
/// RICH-STATE exports: the probes that make the canonical text actually CONTAIN the fields the 48 legacy
/// hash cases never exercised.
///
/// WHY THIS FILE EXISTS. <c>corpus/hash_cases/*.txt</c> is produced by <c>native/hash_diff.py</c> from
/// <c>rd_oracle_run</c> alone, and that entry point authors one strike against one ogre. Measured over the 48
/// cases, the pre-hash canonical text only ever contains these line heads:
///   id seed step result round turn phase active res tags cz draw hand disc
///   turn_order card_num chain_num exec_num status_num
/// <c>CombatStateHasher.AppendSnapshot</c> also writes — and nothing in that corpus ever contained:
///   <c>dp=</c>  combatant defensive pools                       (reachable through rd_oracle_run_ex)
///   <c>s=</c>   combatant statuses                              (reachable through rd_oracle_run_ex)
///   <c>queue=</c> the resolution queue + <c>qat:</c>            (reachable through rd_oracle_run_ex)
///   <c>gs=</c>  global statuses                                 (NO runtime path — see ProbeGlobalStatus)
///   <c>cnt=</c> combatant counters                              (new probe below)
///   <c>tr=</c>  temporary triggered rules                       (new probe below)
///   <c>aside=</c> the set-aside pile                            (new probe below)
///   <c>m:</c> <c>mc:</c> <c>msrc:</c> card-instance marks        (new probe below)
///   <c>pend=</c> a waiting (delayed) status instance            (new probe below)
/// So as far as those lines went, the port's byte-exactness was verified against a HAND-COPIED appender
/// rather than against engine output. These exports supply the engine output.
///
/// LAYOUT NOTE. This is a NEW partial file on purpose: <c>OracleExports</c> is a partial class, so nothing
/// that already exists had to be touched (the existing exports are pinned by golden_v1/v2 and by other
/// work in flight). Every probe here ends in the SAME observation point as everything else —
/// <c>CaptureState</c> in OracleExports.Extended.cs — so it hands back exactly the same shape of answer
/// (engine hash + pre-hash canonical text + the rich detail string).
///
/// HONESTY NOTE. Each probe's doc comment says whether the state it observes came out of a real combat run
/// or had to be built. Only <see cref="ProbeGlobalStatus"/> is in the second category, and it says so.
/// </summary>
public static partial class OracleExports
{
    // The marks / counters the rich probes write. Plain authored ids — the engine attaches no meaning to any
    // particular mark, which is exactly why they are good probes: what shows up in the text is the plumbing.
    private static readonly TagId[] RichMarkTags =
    [
        new("oracle.mark.a"),
        new("oracle.mark.b"),
        new("oracle.mark.c"),
    ];

    private static readonly CounterId RichMarkCounter = new("oracle.charge");
    private static readonly CounterId RichCombatCounter = new("oracle.heat");
    private static readonly StatusDefinitionId RichGlobalStatusId = new("oracle.global_law");

    // ── shared helpers ──────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// The card program root for a list of nodes: one node stands alone, several become a Sequence (whose
    /// children each ENQUEUE their request, and the queue then drains in order), none becomes a NoOp so a
    /// degenerate parameter set is still a legal card.
    /// </summary>
    private static IEffectNode<CardPlayContext> RichRoot(List<IEffectNode<CardPlayContext>> nodes) =>
        nodes.Count switch
        {
            0 => new NoOpEffectNode<CardPlayContext>(),
            1 => nodes[0],
            _ => new SequenceEffectNode<CardPlayContext>(nodes),
        };

    /// <summary>Every problem the runner reported, in step order — the same extraction <c>Capture</c> does.</summary>
    private static List<string> RichProblems(ScenarioReport report) =>
        report.Steps.SelectMany(step => step.Problems).ToList();

    /// <summary>
    /// Runs one played card against one 200-HP foe and captures the result. 200 HP so nothing dies mid-probe:
    /// a downed foe would move the VERY fields these probes exist to exercise (its pools are cleared, its
    /// statuses are removed), and a probe about the hasher's plumbing must not be about death.
    /// </summary>
    private static int RichPlayAndCapture(
        IEffectNode<CardPlayContext> program, int seed, bool endTurn = false,
        Action<CombatState>? afterRun = null)
    {
        var fight = NewFight(20, 200, 1, 6, 5, program, cardCost: 0, shuffle: false);
        var script = new ScenarioScript().HeroPlays(CardId, EnemyId(0));
        if (endTurn)
            script.HeroEndsTurn();

        var report = RunFight(fight, script.Build(), seed);
        if (report is null)
            return -1;

        var final = report.FinalState;
        afterRun?.Invoke(final);
        CaptureState(final, RichProblems(report), report.Steps.Count, playedSomething: true);
        return _hash.Length;
    }

    // ── 1. card-instance marks: m: / mc: / msrc: ────────────────────────────────────────────────────────

    /// <summary>
    /// Marks cards IN HAND from the card being played, so <c>AppendCards</c> has something to write after the
    /// definition id. One card can carry several marks (one <c>m:</c> per tag, tags sorted), the following
    /// cards carry the first tag only, and an optional mark counter covers <c>mc:</c>.
    ///
    /// MEASURED: the played card is still IN the hand list while the program's nodes evaluate, so hand index 0
    /// is the card being played — it collects the marks and then carries them into its own destination zone
    /// (which is how <c>disc=card_000001 strike m:…</c> below comes about), while indices 1.. are the cards
    /// that stay in hand. Both halves matter: a mark that survived a zone move, and marks on cards that did not.
    ///
    /// distinctTags: how many distinct tags land on hand[0] (1..3).
    /// extraCards:   how many FURTHER hand cards get the first tag (0..3).
    /// counterValue: <c>oracle.charge</c> on hand[0]; 0 writes no counter (a 0 counter is DELETED by the
    ///               engine, so 0 would silently mean "no mc: line at all").
    /// relative:     nonzero writes the value twice with Relative=true (0 + v + v = 2v); zero writes it twice
    ///               absolutely (v, v = v). Two writes on purpose, so this flag is OBSERVABLE in the text.
    /// withSource:   nonzero binds the mark to the hero, which is the only way <c>msrc:</c> appears.
    ///
    /// Part of the state is a REAL combat run: the cards are drawn, the card is played, its program runs.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_card_marks")]
    public static int ProbeCardMarks(int distinctTags, int extraCards, int counterValue, int relative,
                                     int withSource, int seed)
    {
        try
        {
            var tags = Math.Clamp(distinctTags, 1, RichMarkTags.Length);
            var extra = Math.Clamp(extraCards, 0, 3);
            var nodes = new List<IEffectNode<CardPlayContext>>();

            for (var i = 0; i < tags; i++)
                nodes.Add(MarkHandCard(0, RichMarkTags[i], withSource != 0));

            for (var card = 1; card <= extra; card++)
                nodes.Add(MarkHandCard(card, RichMarkTags[0], withSource != 0));

            if (counterValue != 0)
            {
                // Absolute = "set", relative = "add"; written twice so the two policies land on different
                // numbers instead of the same one.
                for (var write = 0; write < 2; write++)
                    nodes.Add(new SetCardInstanceMarkCounterNode<CardPlayContext>(
                        CombatantTargetSelectors.Source,
                        new CardInZoneExpression<CardPlayContext>(CardZone.Hand, 0),
                        RichMarkCounter,
                        Effects.Const(counterValue),
                        relative != 0));
            }

            return RichPlayAndCapture(RichRoot(nodes), seed);
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    /// <summary>
    /// <c>CardInZoneExpression(Hand, index)</c> is read by index at resolution time, and the played card has
    /// already LEFT the hand by then, so index 0 is the first card still in hand rather than the one being
    /// played — which is what makes "mark the next three cards" expressible in a single card program.
    /// </summary>
    private static IEffectNode<CardPlayContext> MarkHandCard(int handIndex, TagId mark, bool withSource) =>
        new MarkCardInstanceNode<CardPlayContext>(
            CombatantTargetSelectors.Source,
            new CardInZoneExpression<CardPlayContext>(CardZone.Hand, handIndex),
            mark,
            remove: false,
            sourceSelector: withSource ? CombatantTargetSelectors.Source : null);

    // ── 2. combatant counters: cnt= ─────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Writes the persistent per-combatant counter <c>oracle.heat</c> on the hero (the card's Source) and/or
    /// on the first foe (the card's EventTarget), which is what <c>AppendCombatant</c> renders as <c>cnt=</c>.
    /// The counter bag is sorted by key and only non-zero entries exist, so both sides being written gives one
    /// <c>cnt=</c> line under each combatant block.
    ///
    /// relative: nonzero adds (0 + amount + amount when twice), zero sets absolutely (amount).
    /// twice:    nonzero writes each amount twice, so `relative` is observable.
    ///
    /// A REAL combat run: the counter is written by the played card's own effect program.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_combatant_counter")]
    public static int ProbeCombatantCounter(int heroAmount, int foeAmount, int relative, int twice, int seed)
    {
        try
        {
            var nodes = new List<IEffectNode<CardPlayContext>>();
            AddCounter(CombatantTargetSelectors.Source, heroAmount);          // the hero
            AddCounter(CombatantTargetSelectors.EventTarget, foeAmount);      // foe0, the card's target

            return RichPlayAndCapture(RichRoot(nodes), seed);

            void AddCounter(ICombatantTargetSelector selector, int amount)
            {
                if (amount == 0)
                    return;
                var writes = twice != 0 ? 2 : 1;
                for (var i = 0; i < writes; i++)
                    nodes.Add(new SetCombatantCounterNode<CardPlayContext>(
                        selector, RichCombatCounter, Effects.Const(amount), relative != 0));
            }
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 3. temporary triggered rules: tr= ──────────────────────────────────────────────────────────────

    /// <summary>
    /// Installs a temporary triggered program and captures the fight while it is LIVE, so
    /// <c>AppendSnapshot</c>'s <c>tr=</c> line (id, event type, remaining activations, both expiry
    /// countdowns, owner, install round/turn) has something to write.
    ///
    /// lifetime: 0 = unlimited, 1 = one shot, 2 = N activations, 3 = until end of round N,
    ///           4 = until end of turn N (of round N), 5 = until the owner is removed.
    /// ownerMode: 0 = installed by the card's own effect (which never names an owner, so <c>owner=none</c>),
    ///            1 = installed directly on the final CombatState with the hero as owner — the only path to
    ///            <c>owner=knight</c>, and (with lifetime 5) to <c>ownerbound</c>. It replaces the card's own
    ///            install rather than adding to it, because the engine refuses a second rule under one id.
    /// damage:    nonzero appends a 1-damage hit AFTER the install, so the rule fires once and its activation
    ///            budget visibly counts down (2 -> 1).
    /// endTurn:   nonzero ends the turn after the play, which moves the round/turn the rule was installed on
    ///            away from the one it is observed in — and expires any rule whose round/turn countdown has
    ///            already been passed. An expired rule is PRUNED (removed from the list) in the same call that
    ///            expires it, so lifetime 1 + damage 1, or an expiry round/turn behind the current one, leaves
    ///            NO <c>tr=</c> line at all. That is engine behaviour, not a probe bug, and
    ///            <c>AppendSnapshot</c>'s " dead" suffix is unreachable for the same reason.
    ///
    /// REAL combat run; the damage-triggered program is the same shape as rd_oracle_probe_trigger_order's.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_temporary_rule")]
    public static int ProbeTemporaryRule(int lifetime, int amount, int ownerMode, int damage, int endTurn, int seed)
    {
        try
        {
            var spec = RichLifetime(lifetime, amount);
            var definition = TriggeredProgramContextAdapters.DamageDealt.Define(
                new TriggeredEffectDefinitionId($"oracle.rule.L{lifetime}A{amount}O{ownerMode}"),
                new EffectProgram<DamageDealtTriggeredEffectContext>(
                    new GainBlockNode<DamageDealtTriggeredEffectContext>(
                        CombatantTargetSelectors.EventTarget,
                        new ConstantExpression<DamageDealtTriggeredEffectContext>(1))),
                priority: 3);

            var nodes = new List<IEffectNode<CardPlayContext>>();
            if (ownerMode == 0)
                nodes.Add(new InstallTemporaryRuleNode<CardPlayContext>(definition, lifetime: spec));
            if (damage != 0)
                nodes.Add(new DealDamageNode<CardPlayContext>(
                    CombatantTargetSelectors.EventTarget, Effects.Const(1)));

            Action<CombatState>? installWithOwner = null;
            if (ownerMode != 0)
                installWithOwner = final => final.AddTemporaryTriggeredProgram(
                    definition, spec, new CombatantId(HeroId));

            return RichPlayAndCapture(
                RichRoot(nodes), seed, endTurn: endTurn != 0, afterRun: installWithOwner);
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    /// <summary>The lifetime table for <see cref="ProbeTemporaryRule"/>. The N-taking shapes need N > 0.</summary>
    private static TemporaryRuleLifetime RichLifetime(int lifetime, int amount)
    {
        var n = Math.Max(1, amount);
        return lifetime switch
        {
            0 => TemporaryRuleLifetime.Unlimited,
            1 => TemporaryRuleLifetime.OneShot,
            2 => TemporaryRuleLifetime.Activations(n),
            3 => TemporaryRuleLifetime.UntilEndOfRound(n),
            4 => TemporaryRuleLifetime.UntilEndOfTurn(n, n),
            _ => TemporaryRuleLifetime.UntilOwnerRemoved,
        };
    }

    // ── 4. the set-aside / exhaust / banished piles: aside= exh= ban= ───────────────────────────────────

    /// <summary>
    /// Moves cards out of the hand into one of the zones that only a card operation can reach, one node per
    /// card. These are the piles no legacy case ever contained: <c>CombatantCardZonesSnapshot.SetAsidePile</c>
    /// plus the two that only an explicit "exhaust it" / "banish it" ever fills
    /// (<c>ExhaustPile</c> / <c>BanishedPile</c>), so <c>AppendCardZones</c> writes <c>aside=</c>, <c>exh=</c>
    /// and <c>ban=</c> only from here.
    ///
    /// zone:  0 = SetAsidePile, 1 = ExhaustPile, 2 = BanishedPile.
    /// count: how many cards are moved (1..4). MEASURED: the played card is still IN the hand list while the
    ///        program's nodes evaluate, so hand index 0 is the card being played — the moves therefore start
    ///        at index 1 and walk forward, which keeps the played card going to its own destination and puts
    ///        `count` DISTINCT hand cards in the target pile, in the order they were moved. (Index 0 twice
    ///        would resolve to the same card twice and the second move would be the engine's no-op, which is
    ///        how this was found.)
    ///
    /// REAL combat run: the moves are requests enqueued by the played card and drained by the queue.
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_card_zone_move")]
    public static int ProbeCardZoneMove(int zone, int count, int seed)
    {
        try
        {
            var destination = zone switch
            {
                1 => CardZone.ExhaustPile,
                2 => CardZone.BanishedPile,
                _ => CardZone.SetAsidePile,
            };
            var moves = Math.Clamp(count, 1, 4);
            var nodes = new List<IEffectNode<CardPlayContext>>();
            for (var i = 0; i < moves; i++)
                nodes.Add(new MoveCardToZoneNode<CardPlayContext>(
                    CombatantTargetSelectors.Source,
                    new CardInZoneExpression<CardPlayContext>(CardZone.Hand, i + 1),
                    destination));

            return RichPlayAndCapture(RichRoot(nodes), seed);
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }

    // ── 5. a waiting status instance: pend= inside s= ───────────────────────────────────────────────────

    /// <summary>
    /// Gives the hero a status that POSTPONES what lands on it ("due notice": a status definition may carry
    /// <c>IncomingStatusDelay</c>), then plays a card that applies a debuff to the hero. The debuff lands with
    /// <c>PendingTurns = delay</c>, which <c>AppendStatus</c> renders as <c> pend=</c> — a field of the status
    /// line that no legacy case contains because every legacy status is applied with no delay in force.
    /// The debuff also carries a real duration and charge count, which is the OTHER pair of status values
    /// nothing in the legacy corpus ever made non-zero (<c>StartingStatusSpec</c>, which is all the wide
    /// runner has, passes stacks only).
    ///
    /// A REAL combat run, and a purely authorable one: the delay lives on a StatusBlueprint and the ordinary
    /// ApplyStatus request does the rest. Two statuses therefore show up in <c>s=</c>: the delaying one
    /// (stacks 0) and the postponed one (stacks N, dur D, chg C, pend=delay).
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_pending_status")]
    public static int ProbePendingStatus(int stacks, int delay, int duration, int charges, int seed)
    {
        try
        {
            var warden = new StatusBlueprint("oracle.warden")
            {
                Polarity = StatusPolarity.Buff,
                // null polarity = everything that arrives waits, which keeps the probe about the FIELD and
                // not about polarity rules.
                IncomingStatusDelay = new IncomingStatusDelaySpec(Math.Clamp(delay, 1, 4)),
            };
            var fear = new StatusBlueprint("oracle.fear")
            {
                Polarity = StatusPolarity.Debuff,
                UsesStacks = true,
                UsesDuration = true,
                UsesCharges = true,
            };

            var program = Effects.ApplyStatus(
                CombatantTargetSelectors.Source, fear.DefinitionId, Math.Clamp(stacks, 1, 9),
                durationTurns: Math.Clamp(duration, 0, 9), charges: Math.Clamp(charges, 0, 9));
            var fight = NewFight(20, 200, 1, 6, 5, program, cardCost: 0, shuffle: false);
            fight.Statuses.Add(warden);
            fight.Statuses.Add(fear);
            fight.Hero!.StartingStatuses.Add(new StartingStatusSpec(warden.DefinitionId));

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

    // ── 6. global statuses: gs= ─────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// ⚠ THE ONE PROBE WHOSE STATE IS NOT PRODUCED BY A COMBAT RUN, AND THAT IS A FINDING, NOT A SHORTCUT.
    ///
    /// MEASURED: <c>CombatState._globalStatuses</c> has exactly ONE writer in the whole engine —
    /// <c>CombatState.Restore</c> (CombatState.cs:818). No effect, no blueprint, no interceptor and no start
    /// path ever adds a global status, and <c>GlobalStatuses</c> is a read-only view of that list. So
    /// <c>gs=</c> cannot be reached from any combat a player can play in this revision: it is a line the
    /// hasher emits, that the snapshotter captures, that the restore consumes, and that nothing PRODUCES.
    ///
    /// This probe therefore does what a save file does: runs a REAL fight, takes the REAL snapshot of its
    /// final state, adds one global status to that snapshot, and hands it to the engine's own
    /// <c>CombatState.Restore</c> + <c>CombatStateSnapshotter</c> + <c>CombatStateHasher</c>. The text that
    /// comes out is engine text, and every other line in it is a real fight's. What it proves is that the
    /// gs= line is renderable and byte-exact; what it does NOT prove is that a fight can reach one.
    ///
    /// (Restore's registry overload is not needed here: no temporary rule is live, so the program-body
    /// relinking it guards against has nothing to relink.)
    /// </summary>
    [UnmanagedCallersOnly(EntryPoint = "rd_oracle_probe_global_status")]
    public static int ProbeGlobalStatus(int stacks, int duration, int charges, int seed)
    {
        try
        {
            var report = RunFight(
                NewFight(20, 200, 1, 6, 5, new NoOpEffectNode<CardPlayContext>(), cardCost: 0, shuffle: false),
                PlayOnce(), seed);
            if (report is null)
                return -1;

            var global = new StatusInstanceSnapshot(
                new StatusInstanceId("status_000900"),
                RichGlobalStatusId,
                // A global status has no BEARER, and the field is a non-nullable CombatantId, so it is left
                // default (""). AppendStatus never writes it, so the text cannot depend on it — which is the
                // same reason a global status is a plausible thing for the engine to hold at all.
                OwnerCombatantId: default,
                Stacks: stacks,
                DurationTurns: duration,
                Charges: charges,
                Polarity: StatusPolarity.Neutral,
                Tags: ImmutableArray<TagId>.Empty,
                Counters: ImmutableArray<CounterSnapshot>.Empty);

            var restored = CombatState.Restore(
                report.FinalState.CreateSnapshot() with { GlobalStatuses = [global] });

            CaptureState(restored, RichProblems(report), report.Steps.Count, playedSomething: true);
            return _hash.Length;
        }
        catch (Exception ex)
        {
            _error = ex.GetType().Name + ": " + ex.Message;
            return -1;
        }
    }
}
