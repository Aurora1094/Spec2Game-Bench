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
  "game_name": "Mini Zelda-like Room Adventure",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      700
    ]
  },
  "schema_version": 1,
  "family_slug": "mini_zelda",
  "variant_id": "var01",
  "instance_id": "mini_zelda_var01"
}
---

# Game Specification

## Game Name

Mini Zelda-like Room Adventure

---

# 1. Game Overview

Mini Zelda-like Room Adventure is a top-down spatial exploration and action-adventure game. The player explores a fixed map consisting of 5 rooms, moves between rooms through doors, defeats enemies, obtains Keys, unlocks new areas, and ultimately reaches the final room to obtain the treasure.

The fixed room roles are:

- Room A: starting room
- Room C: central connecting room
- Room B: Key 1 combat room
- Room D: Key 2 combat room
- Room E: final treasure room

The intended progression is:

`Room A → Room C → Room B → obtain Key 1 → Room C → unlock Room D → obtain Key 2 → Room C → unlock Room E → open the treasure chest → Victory`

The player uses WASD for movement and Space for a short-range melee attack in the current facing direction.

The game contains two enemy types:

- Slime: continuously tracks the player.
- Guard: initially patrols along a fixed vertical route and permanently enters chase once the player comes within range.

The player starts with 7 HP.

Room state is persistent. Defeated enemies do not respawn when the player leaves and re-enters a room.

Spawned or collected Keys, unlocked doors, surviving enemy HP and positions, Guard behavior states and patrol directions, and the treasure chest state are preserved across room transitions.

A custom rule is the sequential dependency between Key 1 and Key 2. The player must first clear Room B to obtain Key 1 and unlock Room D, then clear Room D to obtain Key 2 and unlock Room E.

The game does not include random maps, random enemies, random drops, multiple floors, camera scrolling, a minimap, fog of war, ranged attacks, magic, bombs, blocking, rolling, dashing, stamina, Mana, equipment, weapon switching, Inventory, Gold, shops, XP, upgrades, NPCs, dialogue, Bosses, saving, Checkpoints, healing items, automatic healing, a time limit, Score, Lives, enemy respawning, knockback, or complex pathfinding.

---

# 2. Game Scene & Interface

The game window is 800 × 700 px. From top to bottom, it contains:

1. Top information area: 800 × 80 px
2. Main room area: x = 50–750, y = 100–600
3. Bottom instruction area: 800 × 80 px

Every room uses the same 700 × 500 px main room area.

Room transitions occur instantly, without scrolling or camera animation.

## 2.1 Top Information Area

The top area displays:

| Item | Position | Initial Display |
|---|---|---|
| HP | `(30, 28)` | `HP: 7/7` |
| Keys | `(200, 28)` | `Keys: 0` |
| Room | `(360, 28)` | `Room: A` |
| Status | `(560, 28)` | `Status: Playing` |

All text uses a font size of 28 px.

Room displays:

- A
- B
- C
- D
- E

Status displays:

- `Playing`
- `Victory`
- `Game Over`

## 2.2 Bottom Instruction Area

During `playing`, the bottom area displays:

`WASD: Move Space: Attack`

`Explore rooms, find keys, and reach the treasure`

Both lines use a font size of 22 px and should be centered.

During `victory`:

`Treasure Found!`

`Press R to Restart`

During `game_over`:

`Game Over`

`Press R to Restart`

The result line uses a font size of 36 px.

`Press R to Restart` uses a font size of 26 px.

## 2.3 Visual Objects

Player:

- Blue circle
- Radius: 18 px
- Approximate 20 px facing-direction line

Slime:

- Green circle
- Radius: 16 px

Guard:

- Visual size: 32 × 32 px purple square
- Logical collision shape: circle with radius 16 px

Each living enemy displays a 32 × 5 px HP bar.

Keys use clearly visible gold key graphics.

Fixed obstacles use dark-gray rectangles.

Normal doors are displayed as open entrances.

Locked doors are visually distinct closed barriers with a lock symbol.

The final treasure chest uses a brown or gold appearance and has two visually distinct states:

- `closed`
- `opened`

---

# 3. Game Objects & States

The main game objects and state variables include the player, Slimes, Guards, obstacles, doors, Key 1, Key 2, treasure chest, HP, Keys, attack state, damage invulnerability, room state, and game state.

## 3.1 Player

The player has:

- Collision shape: circle
- Radius: 18 px
- Movement speed: 200 px/s
- Maximum HP: 7
- Initial HP: 7
- Initial facing: `right`
- Initial room: Room A
- Initial center: `(180, 350)`

## 3.2 Room Connection Structure

The fixed room structure is:

```text
       Room B
         |
Room A — Room C — Room D
         |
       Room E
```

Door relationships:

- Room A ↔ Room C: normal
- Room B ↔ Room C: normal
- Room C ↔ Room D: initially locked, requires Key 1
- Room C ↔ Room E: initially locked, requires Key 2

## 3.3 Room A

Room A is the starting room.

Right-side door to Room C:

- Boundary: x = 750
- Opening: y = 320–380

Returning from Room C places the player at:

`(705, 350)`

Obstacles:

| Obstacle | Top-Left Coordinate | Size |
|---|---|---|
| A1 | `(290, 220)` | `100 × 60 px` |
| A2 | `(420, 420)` | `120 × 60 px` |

Room A contains no enemies, Keys, locked doors, or treasure chest.

## 3.4 Room B

Room B is the Key 1 combat room.

Bottom door to Room C:

- Boundary: y = 600
- Opening: x = 370–430

Entering from Room C places the player at:

`(400, 555)`

Initial enemies:

- Slime B1: `(220, 250)`
- Slime B2: `(580, 250)`

Obstacles:

| Obstacle | Top-Left Coordinate | Size |
|---|---|---|
| B1 | `(300, 300)` | `80 × 120 px` |
| B2 | `(420, 300)` | `80 × 120 px` |

A 40 px passage remains between the two obstacles.

After both Slimes are defeated, Key 1 spawns at:

`(400, 350)`

## 3.5 Room C

Room C is the central connecting room and contains no enemies.

Doors:

- Left to Room A: x = 50, y = 320–380
- Top to Room B: y = 100, x = 370–430
- Right to Room D: x = 750, y = 320–380, initially locked by Key 1
- Bottom to Room E: y = 600, x = 370–430, initially locked by Key 2

Obstacles:

| Obstacle | Top-Left Coordinate | Size |
|---|---|---|
| C1 | `(250, 220)` | `80 × 60 px` |
| C2 | `(470, 220)` | `80 × 60 px` |
| C3 | `(250, 420)` | `80 × 60 px` |
| C4 | `(470, 420)` | `80 × 60 px` |

Spawn positions when entering Room C:

- From Room A: `(95, 350)`
- From Room B: `(400, 145)`
- From Room D: `(705, 350)`
- From Room E: `(400, 555)`

## 3.6 Room D

Room D is the Key 2 combat room.

Left door to Room C:

- Boundary: x = 50
- Opening: y = 320–380

Entering from Room C places the player at:

`(95, 350)`

Initial enemies:

- Slime D1: `(600, 450)`
- Guard D1: `(320, 220)`
- Guard D2: `(320, 480)`

Obstacles:

| Obstacle | Top-Left Coordinate | Size |
|---|---|---|
| D1 | `(410, 190)` | `70 × 110 px` |
| D2 | `(410, 400)` | `70 × 110 px` |
| D3 | `(535, 310)` | `90 × 80 px` |

After all 3 enemies are defeated, Key 2 spawns at:

`(600, 240)`

## 3.7 Room E

Room E is the final room and contains no enemies.

Top door to Room C:

- Boundary: y = 100
- Opening: x = 370–430

Entering from Room C places the player at:

`(400, 145)`

Obstacles:

| Obstacle | Top-Left Coordinate | Size |
|---|---|---|
| E1 | `(220, 260)` | `100 × 60 px` |
| E2 | `(480, 260)` | `100 × 60 px` |

Treasure chest:

- Center: `(400, 480)`
- Size: 60 × 45 px
- Initial state: `closed`

## 3.8 Game State

The game contains:

- `playing`
- `victory`
- `game_over`

Both `victory` and `game_over` are terminal states.

---

# 4. Player Interaction

The player uses W, A, S, D, Space, and R.

## 4.1 Movement

Controls:

- W: up
- S: down
- A: left
- D: right

Opposite inputs on the same axis cancel.

If one valid horizontal and one valid vertical direction are active simultaneously, normalize the movement vector so that diagonal speed remains:

`200 px/s`

The player physically collides with:

- Room outer walls
- Fixed obstacles
- Closed locked doors
- Closed treasure chest

Movement collision uses the player's complete circle.

Axis order:

1. Process x movement.
2. Cancel x displacement if blocked.
3. Process y movement.
4. Cancel y displacement if blocked.

## 4.2 Facing

The player has four facing directions:

- `up`
- `down`
- `left`
- `right`

Initial facing:

`right`

Facing updates according to the most recently pressed valid directional key and remains unchanged when all movement keys are released.

For diagonal input, the most recently pressed valid direction determines facing.

If one horizontal and one vertical direction are first pressed simultaneously in the same frame and order cannot be determined, vertical input has priority:

- W + A → up
- W + D → up
- S + A → down
- S + D → down

## 4.3 Melee Attack

Space triggers an attack only on a new key-down event.

Holding Space does not repeatedly trigger attacks.

Attack duration:

`0.20 seconds`

Minimum interval between attack starts:

`0.45 seconds`

When an attack begins:

- Lock the current facing direction.
- Keep that direction for the entire attack.

The player may continue moving during the attack.

The attack area follows the player's current center position while keeping the locked direction.

---

# 5. Core Rules & Mechanics

## 5.1 Sword Attack Area

The sword uses a rectangular logical attack area.

Dimensions:

- Length along attack direction: 42 px
- Width perpendicular to attack direction: 34 px

The rectangle begins at the edge of the player's circular collision shape and extends forward.

Each frame during an active attack:

- Recalculate the attack rectangle from the player's current position.
- Keep the attack direction locked to the direction recorded at attack start.

The visual effect may use a rectangle, arc, or sword graphic, but logical collision uses the defined rectangle.

## 5.2 Sword Damage

Each attack can damage each enemy at most once during its full 0.20-second duration.

A single attack:

- May damage multiple different enemies.
- Deals exactly 1 HP to each successfully hit enemy.
- Does not damage the player.
- Does not damage obstacles.
- Does not affect doors.
- Does not affect Keys.
- Does not open the treasure chest.

Enemies do not block the sword from reaching other enemies.

## 5.3 Sword Blocking

Room walls and fixed obstacles block sword attacks.

For the locked attack direction, the effective attack area is clipped at the nearest blocking wall or fixed obstacle boundary.

An enemy behind a blocking obstacle cannot be damaged even if it overlaps the unclipped attack rectangle.

## 5.4 Slimes

Each Slime has:

- Radius: 16 px
- HP: 2
- Movement speed: 90 px/s
- Contact damage: 1 HP

Each frame, a Slime calculates the normalized direction toward the player's current center and moves at 90 px/s.

Movement uses x-first, y-second collision against room walls and fixed obstacles.

If one axis is blocked, the other may continue.

Slimes do not use A* or other complex pathfinding.

## 5.5 Guards

Each Guard has:

- Visual size: 32 × 32 px
- Logical radius: 16 px
- HP: 3
- Patrol speed: 70 px/s
- Chase speed: 110 px/s
- Contact damage: 1 HP

Guard behavior states:

- `patrol`
- `chase`

Guard D1:

- Initial center: `(320, 220)`
- Patrol x: 320
- Patrol y range: 170–300
- Initial direction: down

Guard D2:

- Initial center: `(320, 480)`
- Patrol x: 320
- Patrol y range: 400–530
- Initial direction: up

During `patrol`, the Guard moves vertically along its fixed route and reverses immediately at the endpoints.

If:

`distance(guard_center, player_center) ≤ 180 px`

the Guard immediately enters `chase`.

Once a Guard enters `chase`, it never returns to `patrol`.

During `chase`, it moves toward the player at:

`110 px/s`

Chase movement uses x-first, y-second collision.

If blocked, the Guard does not search for an alternative route.

## 5.6 Enemy Cross-Room & Physical Collision Rules

Enemies remain permanently assigned to their original rooms.

They:

- Cannot use doors.
- Cannot transition between rooms.
- Remain constrained by the full room boundary.

The player and enemies do not physically block one another.

Enemies also do not physically block one another.

Therefore:

- Slime-Slime overlap is allowed.
- Slime-Guard overlap is allowed.
- Guard-Guard overlap is allowed.
- Player-enemy overlap is allowed.

Character-character overlap is used only for contact damage.

## 5.7 Player Damage & Invulnerability

The player starts with:

`HP = 7`

Slime or Guard contact deals:

`1 HP`

After valid damage:

- HP decreases by 1.
- HP is clamped to a minimum of 0.
- Start 0.8 seconds of damage invulnerability.

During invulnerability:

- Additional enemy contact cannot reduce HP.
- The player flashes between normal and semi-transparent display every approximately 0.1 seconds.

The player can lose at most 1 HP per frame.

If invulnerability ends while the player is still touching an enemy, contact may deal damage again.

## 5.8 Enemy Hits & Death

Sword hits deal:

`1 HP`

Enemy HP:

- Slime: 2
- Guard: 3

After a valid hit, the enemy displays a brief hit highlight for approximately 0.1 seconds.

When enemy HP reaches 0:

- Remove the enemy immediately from active objects.
- Stop movement.
- Stop contact damage.
- Stop collision participation.
- Preserve its dead state permanently until Restart.

If one attack kills multiple enemies, each death is processed independently.

## 5.9 Key State

Key 1 and Key 2 independently track:

- Whether they have spawned.
- Whether they have ever been collected.
- Whether they are currently held.

The persistent state distinguishes at least:

- `key1_collected`
- `key1_held`
- `door_d_unlocked`
- `key2_collected`
- `key2_held`
- `door_e_unlocked`

`collected` prevents a Key from spawning again.

`held` indicates current possession.

When a Key is used:

- `held = false`
- `collected` remains true

The top `Keys` value counts only currently held, unconsumed Keys.

## 5.10 Key Spawning

Key 1:

- Spawn condition: both Room B Slimes are dead
- Position: `(400, 350)`

Key 2:

- Spawn condition: Room D Slime and both Guards are dead
- Position: `(600, 240)`

Each Key:

- Collision rectangle: 28 × 28 px
- Centered at its fixed spawn coordinate
- Remains stationary after spawning

If the player already overlaps the Key collision area in the same frame the Key spawns, it may be collected immediately.

## 5.11 Key Collection

A Key is collected automatically when the player's circle overlaps its 28 × 28 px rectangle.

Collecting Key 1:

- Remove Key 1 from Room B.
- `key1_collected = true`
- `key1_held = true`
- Keys += 1

Collecting Key 2:

- Remove Key 2 from Room D.
- `key2_collected = true`
- `key2_held = true`
- Keys += 1

Keys do not block the player, enemies, or sword attacks.

## 5.12 Locked Doors

The C-D door requires Key 1.

The C-E door requires Key 2.

When the player attempts to pass through a locked door, the corresponding `held` state is checked before physical blocking.

If the required Key is not held:

- Keep the door locked.
- Treat the door as a physical barrier.
- Do not allow transition.
- Keep Keys unchanged.
- Display `Locked`.

If the required Key is held:

- Consume the Key.
- Set the corresponding `held = false`.
- Decrease Keys by 1.
- Set the corresponding door unlocked.
- Permit transition through that door during the same frame.

The actual room transition is still performed during the unified room-transition stage.

After unlocking:

- The door remains permanently open.
- It is passable in both directions.
- The Key is never checked or consumed again.

Keys cannot become negative.

## 5.13 Locked Feedback

`Locked` uses a font size of 24 px.

It appears approximately 40 px inward from the blocked doorway:

- Right-side door message appears to the left.
- Bottom-side door message appears above.

The message remains for approximately 1 second.

Continuously pushing against the same locked door does not need to restart the timer every frame.

## 5.14 Terminal Priority

Victory is marked when the treasure chest is successfully opened.

Game Over occurs when:

`HP = 0`

Terminal priority is:

1. Game Over
2. Victory
3. Continue

Therefore, if HP reaches 0 and the final treasure is obtained during the same frame, the game enters `game_over`.

---

# 6. Game Flow & Progression

## 6.1 Room Transitions

Only the player can transition between rooms.

All doorway openings are 60 px wide.

Left/right doors:

- Opening: y = 320–380
- Safe player-center range: y = 338–362

Top/bottom doors:

- Opening: x = 370–430
- Safe player-center range: x = 388–412

A transition occurs only if:

1. The player's complete circle fits within the doorway.
2. The player's outer edge reaches or attempts to cross the room boundary.
3. Valid movement input points outward through the door.
4. The door is passable.

Merely standing inside the doorway does not trigger transition.

Spawn mapping:

| Transition | Target Spawn |
|---|---|
| Room A → Room C | `(95, 350)` |
| Room C → Room A | `(705, 350)` |
| Room C → Room B | `(400, 555)` |
| Room B → Room C | `(400, 145)` |
| Room C → Room D | `(95, 350)` |
| Room D → Room C | `(705, 350)` |
| Room C → Room E | `(400, 145)` |
| Room E → Room C | `(400, 555)` |

After a successful transition:

- Set the player to the target spawn point.
- Cancel remaining player movement for that frame.
- Prevent a second transition during the same frame.

If the player is attacking:

- End the current attack immediately.
- Preserve the existing 0.45-second attack cooldown.

## 6.2 Persistent Room State

Across transitions, preserve:

- Player HP
- Keys
- Key collected/held states
- Door unlocked states
- Damage invulnerability and remaining duration
- Attack cooldown
- Enemy deaths
- Surviving enemy HP
- Surviving enemy positions
- Guard patrol/chase state
- Guard patrol direction
- Spawned but uncollected Keys
- Treasure chest state

Enemy hit highlights are purely visual and are cleared when leaving the room.

## 6.3 Non-Current Room Freeze

Only the current room updates in real time.

When the player leaves a room:

- Surviving enemies stop moving.
- Enemy HP remains unchanged.
- Enemy positions remain unchanged.
- Guard state remains unchanged.
- Guard patrol direction remains unchanged.
- No background AI continues.

When the player returns, those objects resume from their stored state.

After a successful room transition, the previous room receives no further updates during that frame.

Enemies in the previous room cannot deal contact damage after the transition.

## 6.4 Treasure Chest & Victory Trigger

The final treasure chest in Room E:

- Center: `(400, 480)`
- Size: 60 × 45 px
- Initial state: `closed`

While closed, the chest is a physical obstacle.

If the player's proposed movement first touches or overlaps the closed chest rectangle:

- Block movement into the chest.
- Record `treasure_contact` for the current frame.

The player's final position does not need to overlap the chest.

Later in the same frame, if `treasure_contact` is recorded:

- Set chest state to `opened`.
- Grant the final treasure.
- Mark Victory as a candidate terminal result.

Sword attacks cannot open the chest.

The opened chest remains visible.

## 6.5 Fixed Frame Update Order

While `playing`, each frame follows this fixed order:

1. Process directional input, movement direction, and facing.
2. Process a new Space key-down event and begin an attack if the attack cooldown allows it.
3. Process player x/y movement and collision:
   - Room outer walls
   - Fixed obstacles
   - Locked doors
   - Closed treasure chest
   - For locked doors, check required Key before applying physical blocking.
   - For the chest, block entry and record `treasure_contact`.
4. Check and execute room transition:
   - Normal doors
   - Previously unlocked doors
   - Doors unlocked through Key consumption during this frame
   - If transition succeeds, cancel remaining movement and terminate the current attack while preserving its cooldown.
5. If the attack remains active, update the attack area and process enemy hits, HP reduction, and deaths.
6. Check combat-room completion and spawn the corresponding Key if required.
7. Check player-Key overlap and collect Keys.
8. Update AI and movement for surviving enemies in the current room.
9. Process enemy contact damage using the 0.8-second invulnerability rule, with at most 1 HP lost during the frame.
10. If `treasure_contact` was recorded, open the chest and mark Victory.
11. Update attack cooldown, damage invulnerability, player flashing, `Locked` feedback, and other visual timers.
12. Determine the terminal result using Game-Over-before-Victory priority.

An enemy killed in Step 5 does not participate in Step 8 AI or Step 9 contact damage.

Terminal resolution in Step 12:

1. If HP = 0, enter `game_over`.
2. Otherwise, if Victory was marked in Step 10, enter `victory`.
3. Otherwise, remain `playing`.

## 6.6 Normal Progression

The game begins in Room A.

Expected progression:

1. Move from Room A to Room C.
2. Enter Room B.
3. Defeat Slime B1 and Slime B2.
4. Spawn and collect Key 1.
5. Return to Room C.
6. Use Key 1 to permanently unlock Room D.
7. Enter Room D.
8. Defeat Slime D1, Guard D1, and Guard D2.
9. Spawn and collect Key 2.
10. Return to Room C.
11. Use Key 2 to permanently unlock Room E.
12. Enter Room E.
13. Contact the final treasure chest.
14. Open the chest and obtain the treasure.
15. Enter Victory if HP remains above 0.

---

# 7. Goal, Feedback & Termination

The player's final goal is to obtain the treasure in Room E.

Required progression:

- Explore Room B.
- Defeat both Slimes.
- Obtain Key 1.
- Unlock Room D.
- Defeat the Room D Slime and both Guards.
- Obtain Key 2.
- Unlock Room E.
- Contact and open the final treasure chest.

Enemy hit feedback:

- Enemy HP decreases immediately.
- HP bar shortens.
- Brief approximately 0.1-second hit highlight appears.

Enemy death:

- Enemy is removed immediately.
- Dead state persists across room transitions.

Player damage:

- HP decreases by 1.
- Top HP display updates as `HP: X/7`.
- 0.8-second damage invulnerability begins.
- Player flashes.

Key feedback:

- Spawned Keys use gold graphics.
- Collection removes the Key immediately.
- Keys updates immediately.
- Keys represents only currently held, unconsumed Keys.

Locked-door feedback:

- Missing required Key → display `Locked`.
- Successful unlock → change the door to an open entrance.
- Once unlocked, the door remains permanently passable.

Victory candidate:

- The player contacts the final closed treasure chest.
- The chest becomes `opened`.
- The treasure is obtained.

Game Over:

`HP = 0`

If HP reaches 0 in the same frame in which the final treasure is obtained, Game Over takes priority.

After `victory`:

- Freeze the player.
- Freeze current-room objects.
- Keep the chest opened.
- Stop attacks.
- Stop damage.
- Stop room transitions.
- Stop Key collection.
- Set Status to `Victory`.
- Display `Treasure Found!`.
- Display `Press R to Restart`.
- Accept only R.

After `game_over`:

- End the current attack.
- Freeze the player and current-room enemies.
- Stop damage.
- Stop room transitions.
- Stop Key spawning and collection.
- Stop door unlocking.
- Prevent chest opening from creating Victory.
- Preserve the world state at the moment of death.
- Set Status to `Game Over`.
- Display `Game Over`.
- Display `Press R to Restart`.
- Accept only R.

R is effective only in `victory` and `game_over`.

Restart fully resets the five-room world:

- Current room → Room A
- Player center → `(180, 350)`
- HP → 7
- Keys → 0
- Facing → `right`
- Attack state and cooldown cleared
- Damage invulnerability cleared
- Locked feedback cleared
- Room B Slimes restored at initial positions with 2 HP
- Room D Slime restored at `(600, 450)` with 2 HP
- Guard D1 restored to `(320, 220)`, 3 HP, `patrol`, moving down
- Guard D2 restored to `(320, 480)`, 3 HP, `patrol`, moving up
- Key 1 returned to unspawned, uncollected, unheld
- Key 2 returned to unspawned, uncollected, unheld
- `door_d_unlocked = false`
- `door_e_unlocked = false`
- C-D and C-E doors restored to locked
- Treasure chest restored to `closed`
- Room display → A
- Status → `Playing`
- Game state → `playing`

---

# 8. Functional Checkpoints
