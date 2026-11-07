# 遗物清单（生成物，别手改）

由 `python -X utf8 native/audit_relic_gap.py --write` 生成：左列来自 wiki 的
`Module:Relics/data`（`native/wiki_relics/relics_data.lua.txt`，离线可复核），
右列来自内容镜像的 `Relics` 表与 `rd-run::relic_effect`。

> `Implemented` = 内核有这条效果（`relic_effect` 的 match 里有它）。**内容门要求两者一一对应**，
> 所以"wiki 有、我们没有"的遗物不会半吊子地出现在池子里（一件没效果的遗物被抽出来是最坏的形态）。

| # | 统计 | 值 |
|---|---|---|
| 1 | wiki 遗物总数 | 193 |
| 2 | 内容里的遗物 | 56 |
| 3 | 缺（wiki 有、内容没有） | 137 |

## Starter（4）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 有 | `burning_blood` | Burning Blood | Ironclad | At the end of combat, heal 6 HP. |
| 缺 | `cracked_core` | Cracked Core | Defect | At the start of each combat, $Channel 1 $Lightning. |
| 缺 | `pure_water` | Pure Water | Watcher | At the start of each combat, add 1 {{C\|Miracle}} into your hand. |
| 缺 | `ring_of_the_snake` | Ring of the Snake | Silent | At the start of each combat, draw 2 additional cards. |

## Common（36）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `akabeko` | Akabeko | Shared | Your first {{QueryLink\|Cards\|type:Attack\|Attack}} each combat deals 8 additional damage |
| 有 | `anchor` | Anchor | Shared | Start each combat with 10 $Block. |
| 缺 | `ancient_tea_set` | Ancient Tea Set | Shared | Whenever you enter a Rest Site, start the next combat with 2 extra $Energy. |
| 缺 | `art_of_war` | Art of War | Shared | If you do not play any {{QueryLink\|Cards\|type:Attack\|Attacks}} during your turn, gain an additional $Energy next turn. |
| 有 | `bag_of_marbles` | Bag of Marbles | Shared | At the start of each combat, apply 1 $Vulnerable to ALL enemies. |
| 有 | `bag_of_preparation` | Bag of Preparation | Shared | At the start of each combat, draw 2 additional cards. |
| 有 | `blood_vial` | Blood Vial | Shared | At the start of each combat, heal 2 HP. |
| 有 | `bronze_scales` | Bronze Scales | Shared | Start each combat with 3 $Thorns. |
| 缺 | `centennial_puzzle` | Centennial Puzzle | Shared | The first time you lose HP each combat, draw 3 cards. |
| 缺 | `ceramic_fish` | Ceramic Fish | Shared | Whenever you add a card to your deck, gain 9 [[Gold]]. |
| 缺 | `damaru` | Damaru | Watcher | At the start of your turn, gain 1 $Mantra. |
| 缺 | `data_disk` | Data Disk | Defect | Start each combat with 1 $Focus. |
| 有 | `dream_catcher` | Dream Catcher | Shared | Whenever you Rest, you may add a card to your deck. |
| 缺 | `happy_flower` | Happy Flower | Shared | Every 3 turns, gain 1 $Energy. |
| 缺 | `juzu_bracelet` | Juzu Bracelet | Shared | Regular enemy combats are no longer encountered in ? rooms. |
| 有 | `lantern` | Lantern | Shared | Gain 1 $Energy on the first turn of each combat. |
| 缺 | `maw_bank` | Maw Bank | Shared | Whenever you climb a floor, gain 12 [[Gold]]. No longer works when you spend any [[Gold]] at a shop. |
| 缺 | `meal_ticket` | Meal Ticket | Shared | Whenever you enter a shop, heal 15 HP. |
| 有 | `nunchaku` | Nunchaku | Shared | Every time you play 10 {{QueryLink\|Cards\|type:Attack\|Attacks}}, gain 1 $Energy. |
| 有 | `oddly_smooth_stone` | Oddly Smooth Stone | Shared | At the start of each combat, gain 1 $Dexterity. |
| 缺 | `omamori` | Omamori | Shared | Negate the next 2 {{QueryLink\|Cards\|type:Curse\|Curses}} you obtain. |
| 有 | `orichalcum` | Orichalcum | Shared | If you end your turn without $Block, gain 6 $Block. |
| 有 | `pen_nib` | Pen Nib | Shared | Every 10th {{QueryLink\|Cards\|type:Attack\|Attack}} you play deals double damage. |
| 有 | `potion_belt` | Potion Belt | Shared | Upon pickup, gain 2 [[Potions\|Potion]] slots. |
| 缺 | `preserved_insect` | Preserved Insect | Shared | Enemies in Elite combats have 25% less HP. |
| 有 | `red_skull` | Red Skull | Ironclad | While your HP is at or below 50%, you have 3 additional $Strength. |
| 有 | `regal_pillow` | Regal Pillow | Shared | Whenever you Rest, heal an additional 15 HP. |
| 缺 | `smiling_mask` | Smiling Mask | Shared | The merchant's card removal service now always costs 50 [[Gold]]. |
| 有 | `snecko_skull` | Snecko Skull | Silent | Whenever you apply $Poison, apply an additional 1 $Poison. |
| 有 | `strawberry` | Strawberry | Shared | Upon pickup, raise your Max HP by 7. |
| 有 | `the_boot` | The Boot | Shared | Whenever you would deal 4 or less unblocked {{QueryLink\|Cards\|type:Attack\|Attack}} damage, increase it to 5. |
| 缺 | `tiny_chest` | Tiny Chest | Shared | Every 4th ? room is a Treasure room. |
| 缺 | `toy_ornithopter` | Toy Ornithopter | Shared | Whenever you use a [[Potions\|potion]], heal 5 HP. |
| 有 | `vajra` | Vajra | Shared | At the start of each combat, gain 1 $Strength. |
| 缺 | `war_paint` | War Paint | Shared | Upon pick up, $Upgrade 2 random {{QueryLink\|Cards\|type:Skill\|Skills}}. |
| 缺 | `whetstone` | Whetstone | Shared | Upon pickup, $Upgrade 2 random {{QueryLink\|Cards\|type:Attack\|Attacks}}. |

## Uncommon（36）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `blue_candle` | Blue Candle | Shared | $Unplayable {{QueryLink\|Cards\|type:Curse\|Curse}} cards can now be played. <br>Whenever you play a {{QueryLink\|Cards\|type:Curse\|Curse}}, lose 1 HP and $Exhaust it. |
| 缺 | `bottled_flame` | Bottled Flame | Shared | Upon pickup, choose an {{QueryLink\|Cards\|type:Attack\|Attack}} card. <br>At the start of each combat, this card will be in your hand. |
| 缺 | `bottled_lightning` | Bottled Lightning | Shared | Upon pickup, choose a {{QueryLink\|Cards\|type:Skill\|Skill}} card. <br>At the start of each combat, this card will be in your hand. |
| 缺 | `bottled_tornado` | Bottled Tornado | Shared | Upon pickup, choose a {{QueryLink\|Cards\|type:Power\|Power}} card. <br>At the start of each combat, this card will be in your hand. |
| 缺 | `darkstone_periapt` | Darkstone Periapt | Shared | Whenever you obtain a {{QueryLink\|Cards\|type:Curse\|Curse}}, increase your Max HP by 6 |
| 缺 | `duality` | Duality | Watcher | Whenever you play an {{QueryLink\|Cards\|type:Attack\|Attack}}, gain 1 temporary $Dexterity. |
| 有 | `eternal_feather` | Eternal Feather | Shared | For every 5 cards in your deck, heal 3 HP whenever you enter a Rest Site. |
| 缺 | `frozen_egg` | Frozen Egg | Shared | Whenever you add a {{QueryLink\|Cards\|type:Power\|Power}} card to your deck, $Upgrade it. |
| 缺 | `gold_plated_cables` | Gold-Plated Cables | Defect | Your rightmost $Orb triggers its passive an additional time. |
| 有 | `gremlin_horn` | Gremlin Horn | Shared | Whenever an enemy dies, gain 1 $Energy and draw 1 card. |
| 有 | `horn_cleat` | Horn Cleat | Shared | At the start of your 2nd turn, gain 14 $Block. |
| 有 | `ink_bottle` | Ink Bottle | Shared | Whenever you play 10 cards, draw 1 card. |
| 有 | `kunai` | Kunai | Shared | Every time you play 3 {{QueryLink\|Cards\|type:Attack\|Attacks}} in a single turn, gain 1 $Dexterity |
| 有 | `letter_opener` | Letter Opener | Shared | Every time you play 3 {{QueryLink\|Cards\|type:Skill\|Skills}} in a single turn, deal 5 damage to ALL enemies. |
| 缺 | `matryoshka` | Matryoshka | Shared | The next 2 non-boss chests you open contain 2 Relics. |
| 有 | `meat_on_the_bone` | Meat on the Bone | Shared | If your HP is at or below 50% at the end of combat, heal 12 HP. |
| 有 | `mercury_hourglass` | Mercury Hourglass | Shared | At the start of your turn, deal 3 damage to ALL enemies. |
| 缺 | `molten_egg` | Molten Egg | Shared | Whenever you add an {{QueryLink\|Cards\|type:Attack\|Attack}} card to your deck, $Upgrade it. |
| 缺 | `mummified_hand` | Mummified Hand | Shared | Whenever you play a {{QueryLink\|Cards\|type:Power\|Power}} card, a random card in your hand costs 0 that turn. |
| 缺 | `ninja_scroll` | Ninja Scroll | Silent | At the start each combat, add 3 {{C\|Shiv\|Shivs}} into your hand. |
| 有 | `ornamental_fan` | Ornamental Fan | Shared | Every time you play 3 {{QueryLink\|Cards\|type:Attack\|Attacks}} in a single turn, gain 4 $Block. |
| 缺 | `pantograph` | Pantograph | Shared | At the start of Boss combats, heal 25 HP. |
| 有 | `paper_krane` | Paper Krane | Silent | Enemies with $Weak deal 40% less damage rather than 25%. |
| 有 | `paper_phrog` | Paper Phrog | Ironclad | Enemies with $Vulnerable take 75% more damage rather than 50%. |
| 有 | `pear` | Pear | Shared | Upon pickup, raise your Max HP by 10. |
| 缺 | `question_card` | Question Card | Shared | Future card rewards have 1 additional card to choose from. |
| 缺 | `self_forming_clay` | Self-Forming Clay | Ironclad | Whenever you lose HP, gain 3 $Block next turn. |
| 有 | `shuriken` | Shuriken | Shared | Every time you play 3 {{QueryLink\|Cards\|type:Attack\|Attacks}} in a single turn, gain 1 $Strength. |
| 缺 | `singing_bowl` | Singing Bowl | Shared | When adding cards to your deck, you may raise your Max HP by 2 instead. |
| 缺 | `strike_dummy` | Strike Dummy | Shared | Cards containing \"Strike\" deal 3 additional damage. |
| 缺 | `sundial` | Sundial | Shared | Every 3 times you shuffle your draw pile, gain 2 $Energy. |
| 缺 | `symbiotic_virus` | Symbiotic Virus | Defect | At the start of each combat, $Channel 1 $Dark. |
| 缺 | `teardrop_locket` | Teardrop Locket | Watcher | Start each combat in $Calm. |
| 缺 | `the_courier` | The Courier | Shared | The Merchant restocks [[Cards\|cards]], [[Relics\|relics]], and [[Potions\|potions]]. All prices are reduced by 20%. |
| 缺 | `toxic_egg` | Toxic Egg | Shared | Whenever you add a {{QueryLink\|Cards\|type:Skill\|Skill}} card to your deck, $Upgrade it. |
| 缺 | `white_beast_statue` | White Beast Statue | Shared | [[Potions]] always appear in combat rewards. |

## Rare（34）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `bird_faced_urn` | Bird-Faced Urn | Shared | Whenever you play a {{QueryLink\|Cards\|type:Power\|Power}} card, heal 2 HP. |
| 有 | `calipers` | Calipers | Shared | At the start of your turn, lose 15 $Block rather than all of your $Block. |
| 有 | `captains_wheel` | Captain's Wheel | Shared | At the start of your 3rd turn, gain 18 $Block. |
| 有 | `champion_belt` | Champion Belt | Ironclad | Whenever you apply $Vulnerable, also apply 1 $Weak. |
| 缺 | `charons_ashes` | Charon's Ashes | Ironclad | Whenever you $Exhaust a card, deal 3 damage to ALL enemies. |
| 有 | `cloak_clasp` | Cloak Clasp | Watcher | At the end of your turn, gain 1 $Block for each card in your hand. |
| 缺 | `dead_branch` | Dead Branch | Shared | Whenever you $Exhaust a card, add a random card to your hand. |
| 有 | `du_vu_doll` | Du-Vu Doll | Shared | For each {{QueryLink\|Cards\|type:Curse\|Curse}} in your deck, start each combat with 1 $Strength. |
| 缺 | `emotion_chip` | Emotion Chip | Defect | If you lost HP during the previous turn, trigger the passive ability of all $Orbs at the start of your turn. |
| 缺 | `fossilized_helix` | Fossilized Helix | Shared | Prevent the first time you would lose HP in combat. |
| 缺 | `gambling_chip` | Gambling Chip | Shared | At the start of each combat, discard any number of cards, then draw that many cards. |
| 有 | `ginger` | Ginger | Shared | You can no longer become $Weakened. |
| 有 | `girya` | Girya | Shared | You can now gain $Strength at Rest Sites (up to 3 times). |
| 缺 | `golden_eye` | Golden Eye | Watcher | Whenever you $Scry, $Scry 2 additional cards. |
| 有 | `ice_cream` | Ice Cream | Shared | $Energy is now conserved between turns. |
| 有 | `incense_burner` | Incense Burner | Shared | Every 6 turns, gain 1 $Intangible. |
| 缺 | `lizard_tail` | Lizard Tail | Shared | When you would die, heal to 50% of your Max HP instead (works once). |
| 缺 | `magic_flower` | Magic Flower | Ironclad | Healing is 50% more effective during combat. |
| 缺 | `mango` | Mango | Shared | Upon pickup, raise your Max HP by 14. |
| 缺 | `old_coin` | Old Coin | Shared | Upon pickup, gain 300 [[Gold]]. |
| 有 | `peace_pipe` | Peace Pipe | Shared | You can now remove cards from your deck at Rest Sites. |
| 有 | `pocketwatch` | Pocketwatch | Shared | Whenever you play 3 or less cards during your turn, draw 3 additional cards at the start of your next turn. |
| 缺 | `prayer_wheel` | Prayer Wheel | Shared | Normal enemies drop an additional card reward. |
| 有 | `shovel` | Shovel | Shared | You can now Dig for relics at Rest Sites. |
| 有 | `stone_calendar` | Stone Calendar | Shared | At the end of turn 7, deal 52 damage to ALL enemies. |
| 有 | `the_specimen` | The Specimen | Silent | Whenever an enemy dies, transfer any $Poison it has to a random enemy. |
| 有 | `thread_and_needle` | Thread and Needle | Shared | At the start of each combat, gain 4 $Plated Armor. |
| 缺 | `tingsha` | Tingsha | Silent | Whenever you discard a card during your turn, deal 3 damage to a random enemy. |
| 有 | `torii` | Torii | Shared | Whenever you would receive 5 or less unblocked {{QueryLink\|Cards\|type:Attack\|Attack}} damage, reduce it to 1. |
| 缺 | `tough_bandages` | Tough Bandages | Silent | Whenever you discard a card during your turn, gain 3 $Block. |
| 有 | `tungsten_rod` | Tungsten Rod | Shared | Whenever you would lose HP, lose 1 less. |
| 有 | `turnip` | Turnip | Shared | You can no longer become $Frail. |
| 缺 | `unceasing_top` | Unceasing Top | Shared | Whenever you have no cards in hand during your turn, draw a card. |
| 缺 | `wing_boots` | Wing Boots | Shared | You may ignore paths when choosing the next room to travel to 3 times. |

## Boss（30）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `astrolabe` | Astrolabe | Shared | Upon pickup, $Transform 3 cards, then $Upgrade them. |
| 缺 | `black_blood` | Black Blood | Ironclad | Replaces {{R\|Burning Blood}}. At the end of combat, heal 12 HP. |
| 缺 | `black_star` | Black Star | Shared | Elites now drop an additional relic when defeated. |
| 缺 | `busted_crown` | Busted Crown | Shared | Gain 1 $Energy at the start of your turn. Future card rewards have 2 less cards to choose from. |
| 缺 | `calling_bell` | Calling Bell | Shared | Upon pickup, obtain a unique {{QueryLink\|Cards\|type:Curse\|Curse}} and 3 relics. |
| 有 | `coffee_dripper` | Coffee Dripper | Shared | Gain 1 $Energy at the start of your turn. You can no longer Rest at Rest Sites. |
| 缺 | `cursed_key` | Cursed Key | Shared | Gain 1 $Energy at the start of your turn. Whenever you open a non-Boss chest, obtain a {{QueryLink\|Cards\|type:Curse\|Curse}}. |
| 缺 | `ectoplasm` | Ectoplasm | Shared | Gain 1 $Energy at the start of your turn. You can no longer gain [[Gold]]. |
| 缺 | `empty_cage` | Empty Cage | Shared | Upon pickup, remove 2 cards from your deck. |
| 缺 | `frozen_core` | Frozen Core | Defect | Replaces {{R\|Cracked Core}}. If you end your turn with any empty $Orb slots, $Channel 1 $Frost. |
| 有 | `fusion_hammer` | Fusion Hammer | Shared | Gain 1 $Energy at the start of your turn. You can no longer Smith at Rest Sites. |
| 缺 | `holy_water` | Holy Water | Watcher | Replaces {{R\|Pure Water}}. At the start of each combat, add 3 {{C\|Miracle\|Miracles}} into your hand. |
| 缺 | `hovering_kite` | Hovering Kite | Silent | The first time you discard a card each turn, gain 1 $Energy. |
| 缺 | `inserter` | Inserter | Defect | Every 2 turns, gain 1 $Orb slot. |
| 缺 | `mark_of_pain` | Mark of Pain | Ironclad | Gain 1 $Energy at the start of your turn. At the start of combat, shuffle 2 {{C\|Wound\|Wounds}} into your draw pile. |
| 缺 | `nuclear_battery` | Nuclear Battery | Defect | At the start of each combat, $Channel 1 $Plasma. |
| 缺 | `pandoras_box` | Pandora's Box | Shared | Upon pickup, $Transform all Strike and Defend cards. |
| 缺 | `philosophers_stone` | Philosopher's Stone | Shared | Gain 1 $Energy at the start of your turn. ALL enemies start combat with 1 $Strength. |
| 缺 | `ring_of_the_serpent` | Ring of the Serpent | Silent | Replaces {{R\|Ring of the Snake}}. At the start of your turn, draw 1 additional card. |
| 缺 | `runic_cube` | Runic Cube | Ironclad | Whenever you lose HP, draw 1 card. |
| 缺 | `runic_dome` | Runic Dome | Shared | Gain 1 $Energy at the start of your turn. You can no longer see enemy intents. |
| 缺 | `runic_pyramid` | Runic Pyramid | Shared | At the end of your turn, you no longer discard your hand. |
| 缺 | `sacred_bark` | Sacred Bark | Shared | Double the effectiveness of [[Potions\|potions]]. |
| 缺 | `slavers_collar` | Slaver's Collar | Shared | During Boss and Elite combats, gain 1 $Energy at the start of your turn. |
| 缺 | `snecko_eye` | Snecko Eye | Shared | At the start of your turn, draw 2 additional cards. Start each combat $Confused. |
| 缺 | `sozu` | Sozu | Shared | Gain 1 $Energy at the start of your turn. You can no longer obtain [[Potions\|potions]]. |
| 缺 | `tiny_house` | Tiny House | Shared | Upon pickup, obtain 1 [[Potions\|Potion]]. <br>Gain 50 [[Gold]]. <br>Raise your Max HP by 5. <br>Obtain 1 card. <br>$Upgrade 1 random card. |
| 缺 | `velvet_choker` | Velvet Choker | Shared | Gain 1 $Energy at the start of your turn. You cannot play more than 6 cards per turn. |
| 缺 | `violet_lotus` | Violet Lotus | Watcher | Whenever you exit $Calm, gain an additional $Energy. |
| 缺 | `wrist_blade` | Wrist Blade | Silent | {{QueryLink\|Cards\|type:Attack\|Attacks}} that cost 0 deal 4 additional damage. |

## Shop（20）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `brimstone` | Brimstone | Ironclad | At the start of your turn, gain 2 $Strength and ALL enemies gain 1 $Strength. |
| 缺 | `cauldron` | Cauldron | Shared | When obtained, brews 5 random [[Potions\|potions]]. |
| 缺 | `chemical_x` | Chemical X | Shared | The effects of your cost X cards are increased by 2. |
| 缺 | `clockwork_souvenir` | Clockwork Souvenir | Shared | Start each combat with 1 $Artifact. |
| 缺 | `dollys_mirror` | Dolly's Mirror | Shared | Upon pickup, obtain an additional copy of a card in your deck. |
| 缺 | `frozen_eye` | Frozen Eye | Shared | When viewing your Draw Pile, the cards are now shown in order. |
| 缺 | `hand_drill` | Hand Drill | Shared | Whenever you break an enemy's $Block, apply 2 $Vulnerable. |
| 缺 | `lees_waffle` | Lee's Waffle | Shared | Upon pickup, raise your Max HP by 7 and heal all of your HP. |
| 缺 | `medical_kit` | Medical Kit | Shared | $Unplayable {{QueryLink\|Cards\|type:Status\|Status}} cards can now be played. Whenever you play a {{QueryLink\|Cards\|type:Status\|Status}} card, $Exhaust it. |
| 缺 | `melange` | Melange | Watcher | Whenever you shuffle your draw pile, $Scry 3. |
| 缺 | `membership_card` | Membership Card | Shared | 50% discount on all products! |
| 缺 | `orange_pellets` | Orange Pellets | Shared | Whenever you play a {{QueryLink\|Cards\|type:Power\|Power}}, {{QueryLink\|Cards\|type:Attack\|Attack}}, and {{QueryLink\|Cards\|type:Skill\|Skill}} in the same turn, remove all of your [[Debuffs\|debuffs]]. |
| 缺 | `orrery` | Orrery | Shared | Upon pickup, choose and add 5 cards to your deck. |
| 缺 | `prismatic_shard` | Prismatic Shard | Shared | Combat reward screens now contain {{QueryLink\|Cards\|color:Colorless\|Colorless}} cards and cards from other colors. |
| 缺 | `runic_capacitor` | Runic Capacitor | Defect | Start each combat with 3 additional $Orb slots. |
| 缺 | `sling_of_courage` | Sling of Courage | Shared | Start each Elite combat with 2 $Strength. |
| 缺 | `strange_spoon` | Strange Spoon | Shared | Cards which $Exhaust when played will instead discard 50% of the time. |
| 缺 | `the_abacus` | The Abacus | Shared | Whenever you shuffle your draw pile, gain 6 $Block. |
| 缺 | `toolbox` | Toolbox | Shared | At the start of each combat, choose 1 of 3 random {{QueryLink\|Cards\|color:Colorless\|Colorless}} cards and add the chosen card into your hand. |
| 有 | `twisted_funnel` | Twisted Funnel | Silent | At the start of each combat, apply 4 $Poison to ALL enemies. |

## Event（18）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `bloody_idol` | Bloody Idol | Shared | Whenever you gain [[Gold]], heal 5 HP. |
| 缺 | `cultist_headpiece` | Cultist Headpiece | Shared | You feel more talkative. |
| 缺 | `enchiridion` | Enchiridion | Shared | At the start of each combat, add a random {{QueryLink\|Cards\|type:Power\|Power}} card into your hand. It costs 0 for that turn. |
| 缺 | `face_of_cleric` | Face of Cleric | Shared | At the end of combat, raise your Max HP by 1. |
| 有 | `golden_idol` | Golden Idol | Shared | Enemies drop 25% more [[Gold]]. |
| 缺 | `gremlin_visage` | Gremlin Visage | Shared | Start each combat with 1 $Weak. |
| 有 | `mark_of_the_bloom` | Mark of the Bloom | Shared | You can no longer heal. |
| 缺 | `mutagenic_strength` | Mutagenic Strength | Shared | Start each combat with 3 $Strength. At the end of your first turn, lose 3 $Strength. |
| 缺 | `nloths_gift` | N'loth's Gift | Shared | Triples the chance of finding {{QueryLink\|Cards\|rarity:Rare\|Rare}} cards from combat rewards. |
| 缺 | `nloths_hungry_face` | N'loth's Hungry Face | Shared | The next non-Boss chest you open is empty. |
| 缺 | `necronomicon` | Necronomicon | Shared | The first {{QueryLink\|Cards\|type:Attack\|Attack}} played each turn that costs 2 or more is played twice. Upon pickup, obtain a special {{QueryLink\|Cards\|type:Curse\|Curse}}. |
| 缺 | `neows_lament` | Neow's Lament | Shared | Enemies in your first 3 combats will have 1 HP. |
| 缺 | `nilrys_codex` | Nilry's Codex | Shared | At the end of each turn, you may shuffle 1 of 3 random cards to shuffle into your draw pile. |
| 有 | `odd_mushroom` | Odd Mushroom | Shared | When $Vulnerable, take 25% more attack damage rather than 50%. |
| 缺 | `red_mask` | Red Mask | Shared | At the start of each combat, apply 1 $Weak to ALL enemies. |
| 缺 | `spirit_poop` | Spirit Poop | Shared | It's unpleasant. |
| 缺 | `ssserpent_head` | Ssserpent Head | Shared | Whenever you enter a ? room, gain 50 [[Gold]]. |
| 缺 | `warped_tongs` | Warped Tongs | Shared | At the start of your turn, $Upgrade a random card in your hand for the rest of combat. |

## Special（2）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `circlet` | Circlet | Shared | Collect as many as you can. |
| 缺 | `red_circlet` | Red Circlet | Shared | You ran out of relics. Impressive! |

## Blight（13）

| 状态 | id | 名称 | 归属 | wiki 描述 |
|---|---|---|---|---|
| 缺 | `accursed` | Accursed | Shared | Whenever you defeat a Boss, obtain 2 random {{QueryLink\|Cards\|type:Curse\|Curses}}. |
| 缺 | `ancient_augmentation` | Ancient Augmentation | Shared | Enemies start combat with 1 $Artifact, 10 $Plated Armor, and 10 $Regenerate. |
| 缺 | `grotesque_trophy` | Grotesque Trophy | Shared | Upon pickup, obtain 3 {{C\|Pride\|Prides}}. |
| 缺 | `hauntings` | Hauntings | Shared | Enemies start combat with 1 $Intangible. |
| 缺 | `mimic_infestation` | Mimic Infestation | Shared | Treasure rooms in future acts are replaced by Elites. Elites no longer drop Relics. |
| 缺 | `muzzle` | Muzzle | Shared | You can no longer increase your Max HP. All healing is halved. |
| 缺 | `post_durian` | Post-Durian | Shared | Lose 50% of your Max HP. |
| 缺 | `scatterbrain` | Scatterbrain | Shared | Draw 1 less card a turn. |
| 缺 | `shield_of_blight` | Shield of Blight | Shared | Enemies have 50% more HP. |
| 缺 | `spear_of_blight` | Spear of Blight | Shared | Enemies deal 100% more damage. |
| 缺 | `time_maze` | Time Maze | Shared | 	You cannot play more than 15 cards per turn. |
| 缺 | `twisting_mind` | Twisting Mind | Shared | At the end of your turn, add 1 random {{QueryLink\|Cards\|type:Status\|Status}} card to the top of your draw pile. |
| 缺 | `void_essence` | Void Essence | Shared | 	Lose 1 $Energy permanently. |

## 说明

* `Blight` 是无尽模式的遗物，本移植不做；列在这里是为了"总数对得上"，不是为了待办。
* `Starter` / `Boss` / `Shop` / `Event` 都是**不可掉落**的桶（`RELIC_RARITY_WEIGHTS` 只有三档），
  它们进内容之后也只会被事件/宝箱/Boss 奖励这样的**显式**来路发出。
