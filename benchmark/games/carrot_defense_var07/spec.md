---
{
  "checkpoints": [
    {
      "desc": "Dimension D2.1 functional requirements",
      "id": "d2_1",
      "weight": 1
    },
    {
      "desc": "Dimension D2.2 functional requirements",
      "id": "d2_2",
      "weight": 1
    },
    {
      "desc": "Dimension D2.3 functional requirements",
      "id": "d2_3",
      "weight": 1
    },
    {
      "desc": "Dimension D2.4 functional requirements",
      "id": "d2_4",
      "weight": 1
    },
    {
      "desc": "Dimension D2.5 functional requirements",
      "id": "d2_5",
      "weight": 1
    }
  ],
  "difficulty": "hard",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Carrot Defense-like",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      600
    ]
  },
  "schema_version": 1,
  "family_slug": "carrot_defense",
  "variant_id": "var07",
  "instance_id": "carrot_defense_var07"
}
---

# Game Specification

## Game Name

Carrot Defense-like

---

# 1. Game Overview

Carrot Defense-like is a single-level tower defense game. The player builds defensive towers on a fixed grid map to prevent enemies from following one of two predefined branch routes and reaching the carrot target on the right side.

The game includes Gold resources, carrot HP, enemy waves, tower placement, automatic attacks, slowing effects, tower removal, and Perfect Wave rewards.

The game contains 4 fixed waves. Enemies spawn in a predefined order from one fixed entrance. After entering the map, enemies follow either an upper route or a lower route. The two routes merge again before reaching the carrot.

Enemies are assigned to the two routes according to their position in each Wave sequence. Odd-numbered enemies use the Upper Route, and even-numbered enemies use the Lower Route.

The player can spend Gold to build Basic Towers and Freeze Towers. Basic Towers provide primary damage, while Freeze Towers deal lower damage and apply a temporary slowing effect.

Defeated enemies provide Gold rewards. Enemies that reach the carrot damage it and are removed without providing Gold.

The player's goal is to complete all 4 waves while keeping carrot HP above 0.

If carrot HP reaches 0 or below at any time, the game immediately ends in Failure. After Wave 4 has fully ended, the player wins if carrot HP remains greater than 0.

A custom mechanic is the Perfect Wave reward. If no enemy reaches the carrot during an entire wave, the player receives 30 Gold when that wave ends.

If at least one enemy reaches the carrot, that wave provides no Perfect Wave reward.

---

# 2. Game Scene & Interface

The game window is 800 × 600 px and uses a horizontal layout. From top to bottom, it is divided into:

1. Top information area: 800 × 80 px
2. Map area: 800 × 440 px
3. Bottom control area: 800 × 80 px

## 2.1 Top Information Area

The top information area uses two lines.

The first line uses a font size of 24 px and displays:

- Current Gold
- Current carrot HP
- Current Wave, such as `Wave: 1/4`

These values should primarily use simple icons supplemented by text and numbers. Gold may use a yellow circular icon, carrot HP may use an orange carrot or circular icon, and Wave may use a small flag icon.

The second line uses a font size of 20 px and displays one of:

- `Next Wave in 3`
- `Next Wave in 2`
- `Next Wave in 1`
- `Enemies remaining: N`
- `Perfect Wave! +30 Gold`

During an active wave, N includes all enemies that have not yet spawned and all enemies currently alive on either route.

The 3-second preparation countdown is displayed only in the top information area.

## 2.2 Map Area

The map uses a fixed 12 × 8 grid with:

- Cell size: 50 × 50 px
- Grid size: 600 × 400 px
- Grid top-left coordinate: `(100, 100)`

The background uses a light-green grass-style appearance. Path cells use light brown, while non-path buildable cells use light green or another grass-like color.

Light grid lines may be shown.

The map contains:

- One entrance at `(0,3)`
- One split point at `(3,3)`
- One Upper Route
- One Lower Route
- One merge point at `(8,3)`
- One carrot near `(11,3)`

The shared entrance section is:

```text
(0,3), (1,3), (2,3), (3,3)
```

The Upper Route follows these cells in order:

```text
(0,3), (1,3), (2,3), (3,3),
(3,2), (3,1),
(4,1), (5,1), (6,1), (7,1), (8,1),
(8,2), (8,3),
(9,3), (10,3), (11,3)
```

The Lower Route follows these cells in order:

```text
(0,3), (1,3), (2,3), (3,3),
(3,4), (3,5),
(4,5), (5,5), (6,5), (7,5), (8,5),
(8,4), (8,3),
(9,3), (10,3), (11,3)
```

The map structure can be represented as:

```text
                            (3,1) → (4,1) → (5,1) → (6,1) → (7,1) → (8,1)
                              ↑                                               ↓
                            (3,2)                                           (8,2)
                              ↑                                               ↓
(0,3) → (1,3) → (2,3) → (3,3)                                           (8,3) → (9,3) → (10,3) → (11,3)
                              ↓                                               ↑                         Carrot
                            (3,4)                                           (8,4)
                              ↓                                               ↑
                            (3,5) → (4,5) → (5,5) → (6,5) → (7,5) → (8,5)
```

Both complete routes contain 16 path cells from entrance to carrot.

The Upper Route and Lower Route are fixed. Enemies do not dynamically choose a route.

The split point `(3,3)` and merge point `(8,3)` may use small visual markers to make the route structure clear.

All cells belonging to either route are path cells and cannot contain towers.

Any cell that belongs to neither route and does not already contain a tower is buildable.

The game does not include obstacles or destructible terrain.

## 2.3 Carrot Target

The carrot is located near `(11,3)` and uses an orange body with green leaves.

Initial carrot HP:

`10`

An HP bar is displayed near the carrot and may use either 10 discrete segments or a proportional horizontal bar.

Enemies from both routes ultimately reach the same carrot.

When an enemy reaches the carrot, the carrot briefly flashes for approximately 0.3 seconds. The map HP bar and top information HP value update together.

## 2.4 Bottom Control Area

The first line uses a font size of 24 px and displays:

- Basic Tower icon + `1` + `50`
- Freeze Tower icon + `2` + `70`
- Shovel icon + `X` + `No refund`
- `Right Click: Cancel`

The Basic Tower uses a blue-gray turret-style icon.

The Freeze Tower uses a light-blue or icy-blue appearance.

The Shovel uses a shovel icon.

The second line uses a font size of 20 px and normally displays one of:

- `Selected: None`
- `Selected: Basic Tower`
- `Selected: Freeze Tower`
- `Selected: Shovel`

The selected operation is indicated using a clearly visible highlight border.

Placement-failure feedback is limited to:

- `Cannot build on path`
- `Tile occupied`
- `Not enough gold`

The failure message remains visible for approximately 1 second before returning to the current selection display.

After Victory or Failure, the center of the map displays:

`You Win!`

or:

`Game Over`

followed by:

`Press R to Restart`

The result message uses a font size of 48 px and the restart message uses 28 px.

---

# 3. Game Objects & States

The main game objects and state variables include the map grid, Upper Route, Lower Route, carrot, Gold, towers, enemies, Waves, preparation state, current selection, and game state.

## 3.1 Map & Paths

The map consists of 12 × 8 cells.

Each cell is one of:

- Path cell
- Empty buildable cell
- Buildable cell containing a tower

The common entrance is:

`(0,3)`

The routes split at:

`(3,3)`

The routes merge at:

`(8,3)`

The shared final path ends at:

`(11,3)`

All cells belonging to either complete route are fixed path cells and cannot contain towers.

Enemies move through the center points of cells on their assigned route and cannot switch routes between the split point and merge point.

Both routes contain the same number of path cells.

Each enemy maintains a path-progress value based on its position along its assigned complete route. A higher value means the enemy is closer to the carrot and is used for tower target selection.

## 3.2 Carrot HP

The carrot starts with:

`HP = 10`

Damage when an enemy reaches the carrot:

- Normal Enemy: 1
- Fast Enemy: 1
- Tank Enemy: 2

The damage rule is identical for enemies using either route.

After dealing damage, the enemy is removed immediately and provides no Gold.

If carrot HP reaches 0 or below, the game immediately enters `failure`.

Victory after Wave 4 requires carrot HP to remain strictly greater than 0.

## 3.3 Gold

Initial Gold:

`120`

Gold costs:

- Basic Tower: 50
- Freeze Tower: 70
- Tower removal: no refund

Enemy defeat rewards:

- Normal Enemy: +10
- Fast Enemy: +12
- Tank Enemy: +25

Perfect Wave reward:

`+30`

If the player does not have enough Gold to place a selected tower, placement fails and no Gold is deducted.

## 3.4 Towers

The game contains two tower types:

| Tower | Cost | Range | Damage | Attack Interval | Special Effect |
|---|---:|---:|---:|---:|---|
| Basic Tower | 50 | 120 px | 20 | 0.8 s | None |
| Freeze Tower | 70 | 110 px | 8 | 1.2 s | 40% slow for 2 s |

Both towers use single-target instant-hit attacks.

Freeze Tower slow behavior:

- Enemy movement speed becomes 60% of its original speed.
- Slow duration is 2 seconds.
- Slow effects do not stack.
- A new Freeze hit while already slowed resets the remaining duration to 2 seconds.
- When the effect expires, original movement speed is restored.

Each tower is positioned at the center of its grid cell.

Range uses Euclidean distance between tower center and enemy center.

Towers may target enemies on either route whenever those enemies are within range.

A tower cannot target an enemy that is already defeated or has already reached the carrot.

## 3.5 Enemies

The game contains three enemy types:

| Enemy Type | HP | Original Speed | Carrot Damage | Defeat Reward | Visual |
|---|---:|---:|---:|---:|---|
| Normal | 40 | 60 px/s | 1 | 10 Gold | Purple circle |
| Fast | 30 | 90 px/s | 1 | 12 Gold | Smaller red circle or red circle with speed trails |
| Tank | 100 | 40 px/s | 2 | 25 Gold | Larger dark-gray rectangle or circle |

Enemies are defeated when HP reaches 0 or below.

Each enemy displays a small HP bar.

A slowed enemy should display a light-blue border or halo until the slow effect ends.

Each enemy stores one fixed route assignment:

- `upper_route`
- `lower_route`

The assigned route does not change during that enemy's lifetime.

## 3.6 Waves

The game contains 4 non-overlapping Waves.

Enemies within a Wave spawn from `(0,3)` at one global fixed interval of 0.8 seconds.

For each Wave:

- Enemy positions 1, 3, 5, 7, ... use the Upper Route.
- Enemy positions 2, 4, 6, 8, ... use the Lower Route.

There is still only one enemy spawn every 0.8 seconds.

The fixed sequences are:

| Wave | Enemy Sequence |
|---|---|
| Wave 1 | Normal, Normal, Normal, Normal, Normal, Normal |
| Wave 2 | Normal, Normal, Fast, Normal, Normal, Fast, Normal, Normal, Fast |
| Wave 3 | Normal, Normal, Fast, Normal, Fast, Tank, Normal, Fast, Normal |
| Wave 4 | Normal, Fast, Normal, Fast, Tank, Normal, Fast, Normal, Tank, Fast, Normal, Normal |

A Wave ends only after every enemy assigned to that Wave, across both routes, has either:

- Been defeated, or
- Reached the carrot

After Waves 1–3 end, the game enters a 3-second preparation phase.

The player may continue building and removing towers during preparation.

Wave 4 has no subsequent preparation phase.

## 3.7 Current Selection

The current selection is one of:

- `none`
- `basic_tower`
- `freeze_tower`
- `shovel`

The interface displays the equivalent user-facing `Selected: ...` text.

## 3.8 Game State

The main game states are:

- `running`
- `victory`
- `failure`

The game starts in `running`.

If carrot HP reaches 0 or below, the game immediately enters `failure`.

After Wave 4 has fully resolved, the game enters `victory` only if carrot HP remains greater than 0.

After `victory` or `failure`, enemy spawning, enemy movement, tower attacks, placement, removal, selection changes, and other gameplay updates stop.

Only R remains active.

---

# 4. Player Interaction

The player uses the keyboard and mouse.

## 4.1 Selecting an Operation

Controls:

- `1`: select Basic Tower
- `2`: select Freeze Tower
- `X`: select Shovel
- Right mouse button: cancel current selection

Selecting an operation highlights the corresponding icon and updates the selection text.

## 4.2 Placing Towers

When Basic Tower or Freeze Tower is selected, left-clicking a map cell attempts to place the selected tower.

Placement succeeds only if:

1. The cell does not belong to the Upper Route or Lower Route.
2. The cell does not already contain a tower.
3. The player has enough Gold.

On success:

- Place the tower at the cell center.
- Deduct the tower cost.
- Keep the same tower type selected.

Placement failure is checked in this fixed order:

1. Any path cell → `Cannot build on path`
2. Occupied cell → `Tile occupied`
3. Insufficient Gold → `Not enough gold`

A failed placement does not deduct Gold.

## 4.3 Removing Towers

When Shovel is selected, left-clicking a cell containing a tower removes that tower.

Tower removal:

- Provides no Gold refund.
- Does not affect either route.
- Does not affect enemies.
- Does not affect the Wave.
- Does not affect carrot HP.

Clicking an empty cell while Shovel is selected has no effect.

After successful removal, Shovel remains selected.

## 4.4 Canceling Selection

Right-clicking cancels the current selection and returns it to `none`.

After cancellation:

- No operation icon is highlighted.
- The display shows `Selected: None`.

When no operation is selected, left-clicking the map has no effect.

## 4.5 Restart

After Victory or Failure, pressing R fully restarts the game.

Restart resets:

- Gold to 120
- Carrot HP to 10
- Wave to Wave 1
- Tower list to empty
- Enemy list to empty
- Current selection to `none`
- Wave spawn state and timers
- Route-assignment sequence state
- Preparation state and timer
- Perfect Wave tracking
- Tower attack timers
- Game state to `running`

After Restart, enemies again spawn from `(0,3)`, and the first enemy of Wave 1 is assigned to the Upper Route.

No state from the previous run continues after Restart.

---

# 5. Core Rules & Mechanics

## 5.1 Enemy Movement

All enemies spawn at `(0,3)`.

Enemies first move along the shared entrance section:

```text
(0,3), (1,3), (2,3), (3,3)
```

At `(3,3)`:

- Enemies assigned to the Upper Route move through the upper branch.
- Enemies assigned to the Lower Route move through the lower branch.

Upper branch:

```text
(3,3), (3,2), (3,1), (4,1), (5,1), (6,1), (7,1), (8,1), (8,2), (8,3)
```

Lower branch:

```text
(3,3), (3,4), (3,5), (4,5), (5,5), (6,5), (7,5), (8,5), (8,4), (8,3)
```

Both routes merge at `(8,3)`.

After the merge point, all enemies follow:

```text
(8,3), (9,3), (10,3), (11,3)
```

Enemies cannot switch routes between the split and merge points.

Movement speed depends on enemy type, and enemies cannot leave path cells.

Path progress increases as an enemy moves along its assigned complete route toward the carrot and is used for tower targeting.

When an enemy reaches the carrot:

- Remove the enemy immediately.
- Do not grant Gold.
- Apply the enemy's carrot damage.
- Mark the current Wave as non-perfect.
- Flash the carrot for approximately 0.3 seconds.
- Update both carrot HP displays.

If carrot HP becomes 0 or below, immediately enter `failure`.

## 5.2 Tower Attacks

Each tower maintains an independent attack cooldown.

When a tower is ready to attack:

1. Find all valid enemies within its attack range, regardless of assigned route.
2. If multiple enemies are available, select the one with the highest path progress.
3. Apply the attack immediately.
4. Reset that tower's attack cooldown.

An enemy is in range when:

`distance(tower_center, enemy_center) ≤ attack_range`

Basic Tower:

- Damage: 20
- Interval: 0.8 s

Freeze Tower:

- Damage: 8
- Interval: 1.2 s
- Applies or refreshes the 2-second slow effect

Tower attacks are instant-hit. A brief attack line may be displayed between the tower and target.

## 5.3 Enemy Defeat & Gold

If enemy HP reaches 0 or below:

- Remove the enemy.
- Grant its fixed Gold reward.

Rewards:

- Normal: +10
- Fast: +12
- Tank: +25

The reward does not depend on assigned route.

An enemy that reaches the carrot is not considered defeated and grants no Gold.

## 5.4 Wave Progression

Enemies in the current Wave spawn sequentially every 0.8 seconds from `(0,3)`.

Route assignment follows sequence position:

- Odd position → Upper Route
- Even position → Lower Route

Completing the spawn sequence does not end the Wave.

The Wave ends only when all assigned enemies from both routes have been resolved through defeat or reaching the carrot.

When Waves 1–3 end normally:

1. Determine whether the Wave qualifies for Perfect Wave.
2. Grant the Perfect Wave reward if applicable.
3. Enter the 3-second preparation phase.
4. Allow tower placement and removal during preparation.
5. Begin the next Wave after preparation ends.

The Waves never overlap.

## 5.5 Perfect Wave Reward

At the beginning of each Wave, track whether any enemy from either route reaches the carrot.

If no enemy reaches the carrot before the Wave ends:

- Gold += 30
- Display `Perfect Wave! +30 Gold`
- Grant the reward at most once for that Wave

If at least one enemy reaches the carrot:

- No Perfect Wave reward is granted.

Wave 4 is also eligible for the reward.

If carrot HP reaches 0 or below, Failure occurs immediately and no subsequent wave-end settlement is processed.

## 5.6 Wave 4 Final Settlement

When every Wave 4 enemy from both routes has been resolved and carrot HP remains greater than 0:

1. Determine whether Wave 4 qualifies for Perfect Wave.
2. If qualified, grant the +30 Gold reward.
3. Display the Perfect Wave feedback as applicable.
4. Enter `victory`.

If carrot HP reaches 0 or below at any point, including while the final Wave 4 enemy is being resolved, the game enters `failure` immediately instead.

## 5.7 Victory & Failure Priority

Failure condition:

`Carrot HP ≤ 0`

Victory condition:

- Wave 4 has fully ended.
- `Carrot HP > 0`

Failure has priority over all later Wave settlement and Victory processing.

Therefore, once carrot HP reaches 0 or below:

- Enter `failure` immediately.
- Stop gameplay.
- Do not grant a later Perfect Wave reward.
- Do not enter Victory.

---

# 6. Game Flow & Progression

At initialization, the game creates the interface areas, 12 × 8 map, shared entrance path, Upper Route, Lower Route, shared final path, carrot, Gold resource, tower list, enemy list, Wave state, route-assignment state, timers, and current selection.

The initial state is:

- Gold: 120
- Carrot HP: 10
- Current Wave: 1
- Towers: none
- Enemies: none
- Selection: `none`
- Game state: `running`

Wave 1 begins with enemies spawning from `(0,3)` in its fixed order at 0.8-second intervals.

The first enemy uses the Upper Route, the second uses the Lower Route, and route assignment continues alternating by sequence position.

During an active Wave:

- Enemies move along their assigned route.
- Towers automatically attack according to their cooldowns.
- The player may place or remove towers.
- The top information area displays `Enemies remaining: N`.

N includes enemies that have not yet spawned and all enemies currently alive on either route.

When an enemy is defeated, it is removed and grants its Gold reward.

When an enemy reaches the carrot, it is removed, damages the carrot, provides no Gold, and makes the current Wave ineligible for Perfect Wave.

If the damage reduces carrot HP to 0 or below, immediately enter `failure` and stop further Wave processing.

If all enemies in Waves 1–3 from both routes are resolved while carrot HP remains above 0:

- Apply the Perfect Wave reward if eligible.
- Enter a 3-second preparation phase.
- Allow tower placement and removal.
- Start the next Wave when preparation ends.

After all Wave 4 enemies from both routes are fully resolved while carrot HP remains above 0:

- Apply the Perfect Wave reward if eligible.
- Enter `victory`.

In `victory`, the map displays:

`You Win!`

`Press R to Restart`

In `failure`, the map displays:

`Game Over`

`Press R to Restart`

After either terminal state:

- Enemy spawning stops.
- Enemy movement stops.
- Tower attacks stop.
- Tower placement and removal stop.
- Selection changes stop.
- Other gameplay updates stop.
- Only R remains active.

Pressing R fully restores the initial game state and begins again from Wave 1.

---

# 7. Goal, Feedback & Termination

The player's goal is to use Gold effectively across all 4 Waves, defend both branch routes, build and adjust defensive towers, prevent enemies from reaching the carrot, and keep carrot HP above 0.

The top information area provides real-time feedback for:

- Gold
- Carrot HP
- Current Wave
- Remaining enemies across both routes
- Preparation countdown
- Perfect Wave rewards

The map visually shows one entrance, one split point, two route branches, one merge point, and one carrot.

Building a tower immediately reduces Gold.

Defeating an enemy immediately grants its fixed reward.

When an enemy from either route reaches the carrot, the carrot flashes, its HP bar decreases, and the top HP value updates.

The bottom control area displays the current operation selection.

Invalid tower placement displays exactly one of:

- `Cannot build on path`
- `Tile occupied`
- `Not enough gold`

Tower attacks display brief attack feedback, enemy HP bars decrease with damage, and slowed enemies display a light-blue visual indicator.

Failure occurs immediately when:

`Carrot HP ≤ 0`

When Failure occurs:

- No later Wave reward or Victory processing is performed.
- The map displays `Game Over`.
- Only R remains active.

Victory occurs only after all Wave 4 enemies from both routes have been resolved while:

`Carrot HP > 0`

If Wave 4 is perfect, its +30 Gold reward is applied before entering Victory.

After Victory:

`You Win!`

`Press R to Restart`

R fully restores Gold, carrot HP, Waves, towers, enemies, timers, route assignments, selection state, path state, and all other gameplay state.

---

# 8. Functional Checkpoints
