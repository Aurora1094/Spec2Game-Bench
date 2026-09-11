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
  "game_name": "Top-down Arena Shooter",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      700
    ]
  },
  "schema_version": 1,
  "family_slug": "arena_shooter",
  "variant_id": "var03",
  "instance_id": "arena_shooter_var03"
}
---

# Game Specification

## Game Name

Top-down Arena Shooter_V4

---

# 1. Game Overview

Top-down Arena Shooter is a top-down combat game played in a fixed single-screen arena. The player moves freely using WASD, aims with the mouse, fires bullets with the left mouse button, and fights two enemy types with different behavior patterns.

The game contains exactly 6 fixed enemies:

- 3 Chasers
- 3 Shooters

Chasers continuously move toward the player and deal damage through body contact.

Shooters adjust their movement according to their distance from the player and attempt to fire at the player every 1.5 seconds when direct line of sight is available.

The player starts with 5 HP and a 6-round magazine.

Reloading is an active mechanic: pressing R while Ammo is below 6 begins a 1.5-second Reload. During Reload, the player may continue moving and aiming but cannot shoot.

The player's objective is to defeat all 6 enemies before HP reaches 0.

If all enemies are defeated while the player remains alive, the game enters Victory. If HP reaches 0, the game enters Game Over.

Player shooting uses a 0.18-second cooldown between successful shots.

A custom feature of this game is that the three fixed walls affect multiple systems simultaneously. They block player movement, enemy movement, player bullets, enemy bullets, and Shooter line of sight.

The game does not include random maps, random spawn positions, multiple levels, weapon switching, reserve-ammunition limits, item drops, armor, critical hits, headshots, random damage, enemy respawning, complex pathfinding, A*, experience points, upgrades, or Score.

---

# 2. Game Scene & Interface

The game window is 800 × 700 px. From top to bottom, it is divided into:

1. Top information area: 800 × 80 px
2. Main combat area: 800 × 540 px
3. Bottom instruction area: 800 × 80 px

## 2.1 Top Information Area

The top information area displays:

| Item | Position | Initial Display |
|---|---|---|
| HP | `(30, 28)` | `HP: 5/5` |
| Ammo | `(200, 28)` | `Ammo: 6/6` |
| Enemies | `(400, 28)` | `Enemies: 6` |
| Status | `(600, 28)` | `Status: Playing` |

All text uses a font size of 28 px and must remain clearly readable without overlapping.

Status displays:

- `Playing` during normal combat
- `Reloading...` during Reload
- `Victory` after Victory
- `Game Over` after Failure

Enemies represents the number of living enemies and decreases immediately when an enemy dies.

## 2.2 Main Combat Area

The main combat area occupies:

- x = 0–800
- y = 80–620

The arena is completely visible and does not scroll.

The player:

- Blue circle
- Radius: 18 px
- Initial center: `(400, 560)`

A dark aiming line approximately 25 px long extends from the player center toward the current mouse position.

Chasers:

- Red circles
- Radius: 16 px
- Center label: `C`

Shooters:

- Orange circles
- Radius: 16 px
- Center label: `S`

Each living enemy displays a 32 × 5 px HP bar above it. The HP bar length is proportional to current HP / maximum HP.

Player bullets:

- White circles
- Radius: 4 px

Enemy bullets:

- Red circles
- Radius: 5 px

The arena contains three fixed walls:

| Wall | Top-Left Coordinate | Size |
|---|---|---|
| Wall A | `(180, 190)` | `180 × 45 px` |
| Wall B | `(385, 285)` | `55 × 150 px` |
| Wall C | `(510, 430)` | `170 × 45 px` |

Wall labels are not displayed in the game scene.

## 2.3 Bottom Instruction Area

During `playing`, the bottom area displays:

`WASD: Move Mouse: Aim Left Click: Shoot`

`R: Reload Defeat all enemies`

Both lines use a font size of 22 px and should be centered.

During `victory`:

`Victory!`

`Press R to Restart`

During `game_over`:

`Game Over`

`Press R to Restart`

The result line uses a font size of 36 px.

`Press R to Restart` uses a font size of 26 px.

---

# 3. Game Objects & States

The main game objects and state variables include the player, Chasers, Shooters, player bullets, enemy bullets, fixed walls, HP, Ammo, Reload state, firing-cooldown state, damage-invulnerability state, Enemies, and game state.

## 3.1 Player

The player has:

- Collision shape: circle
- Radius: 18 px
- Initial center: `(400, 560)`
- Maximum HP: 5
- Initial HP: 5
- Movement speed: 220 px/s
- Magazine capacity: 6
- Initial Ammo: 6

There is no reserve-ammunition limit.

The player may Reload an unlimited number of times, but each completed Reload restores Ammo only to 6.

## 3.2 Chasers

The game contains exactly 3 Chasers.

Each Chaser has:

- Radius: 16 px
- HP: 2
- Movement speed: 120 px/s
- Attack type: body contact only

Initial centers:

- Chaser 1: `(110, 145)`
- Chaser 2: `(690, 145)`
- Chaser 3: `(135, 500)`

Chasers continuously track the player's current position and do not fire bullets.

## 3.3 Shooters

The game contains exactly 3 Shooters.

Each Shooter has:

- Radius: 16 px
- HP: 3
- Movement speed: 90 px/s
- Firing-attempt interval: 1.5 seconds

Initial centers:

- Shooter 1: `(610, 245)`
- Shooter 2: `(210, 335)`
- Shooter 3: `(665, 500)`

Shooters approach, remain stationary, or retreat according to their distance from the player.

A firing attempt produces a bullet only if direct line of sight is available.

All characters begin without overlapping each other or any wall.

## 3.4 Fixed Walls

The three walls are fixed, immovable, and indestructible.

They block:

- Player movement
- Chaser movement
- Shooter movement
- Player bullets
- Enemy bullets
- Shooter line of sight

## 3.5 Game State

The game contains three states:

- `playing`
- `victory`
- `game_over`

During `playing`, movement, shooting, Reload, enemy AI, bullet updates, collisions, and damage systems operate normally.

Both `victory` and `game_over` are terminal states.

After entering either terminal state, combat stops and only R is accepted to restart.

---

# 4. Player Interaction

The player uses W, A, S, D, the mouse, the left mouse button, and R.

## 4.1 Movement

Controls:

- W: up
- S: down
- A: left
- D: right

If W and S are held together, vertical input becomes 0.

If A and D are held together, horizontal input becomes 0.

If one horizontal and one vertical direction are active simultaneously, normalize the movement vector so that diagonal speed remains 220 px/s.

The player's complete circular collision shape must remain inside:

- x = 0–800
- y = 80–620

Player-wall collision uses axis-separated movement:

1. Process x displacement.
2. Resolve x-axis wall and arena-boundary collisions.
3. Process y displacement.
4. Resolve y-axis wall and arena-boundary collisions.

If one axis is blocked, the other may still proceed.

## 4.2 Aiming

The mouse position determines the player's current aiming direction.

The aiming vector is:

- From player center
- Toward current mouse position
- Normalized

The mouse may be anywhere in the full game window.

If the mouse position exactly equals the player center, no valid aiming direction exists.

## 4.3 Shooting

The left mouse button fires player bullets.

A shot succeeds only if:

- Game state is `playing`.
- Ammo > 0.
- Player is not Reloading.
- At least 0.18 seconds have elapsed since the previous successful shot.
- A valid aiming direction exists.

On a successful shot:

- Ammo decreases by 1.
- One bullet spawns 22 px in front of the player.
- The bullet travels at 500 px/s.
- The bullet keeps the aiming direction recorded at spawn time.
- The 0.18-second firing cooldown restarts.

If the bullet spawn position overlaps a wall, the bullet disappears immediately.

The left mouse button may be held continuously.

While held, shooting repeats whenever all conditions are satisfied, giving a theoretical maximum rate of approximately 5.56 shots per second.

The firing rate is still limited by Ammo and Reload. A full 6-round magazine therefore does not permit continuous firing indefinitely.

If Ammo = 0 or the mouse exactly overlaps the player center:

- No bullet is created.
- Ammo is not consumed.
- The firing cooldown is not reset.

A failed firing attempt for any other unmet shooting condition also does not count as a successful shot and does not restart the firing cooldown.

## 4.4 Reload

During `playing`, R starts Reload only if:

- Ammo < 6
- The player is not already Reloading

Reload duration:

`1.5 seconds`

During Reload:

- Movement remains active.
- Aiming remains active.
- Shooting is disabled.
- Ammo remains unchanged.
- Status displays `Reloading...`.

When Reload completes:

- Ammo becomes 6.
- Reload ends.
- Status returns to `Playing`.

Pressing R with Ammo = 6 has no effect.

Pressing R again during Reload does not restart the Reload timer.

The player may keep holding the left mouse button during Reload. After Reload completes, shooting may resume immediately if the remaining shooting conditions are satisfied, including the 0.18-second firing cooldown.

If valid Reload input and valid shooting input occur in the same frame:

- Reload has priority.
- Reload begins.
- No player bullet is fired during that frame.

In `victory` or `game_over`, R is Restart rather than Reload.

---

# 5. Core Rules & Mechanics

## 5.1 Character & Wall Collision

The arena uses fixed geometry and does not scroll.

The player, Chasers, and Shooters physically collide only with:

- Fixed walls
- Arena boundaries

Characters do not physically block one another.

Therefore:

- Chasers may overlap other Chasers.
- Shooters may overlap other Shooters.
- Chasers and Shooters may overlap.
- Enemies may visually overlap the player.

Chaser-player overlap is used only for contact damage.

All character-wall collision uses the character's full circular collision shape rather than only its center point.

## 5.2 Player Bullets

Each player bullet:

- Radius: 4 px
- Speed: 500 px/s
- Damage: 1
- Direction: fixed at spawn

A bullet disappears when it:

- Hits a wall.
- Leaves the main combat area.
- Hits an enemy.

A player bullet can damage at most one enemy and does not collide with other bullets.

If one bullet overlaps multiple enemies during the same update:

1. Damage the enemy first encountered along the bullet's direction of travel.
2. If discrete-frame collision cannot determine this order, choose the closest overlapping enemy to the bullet center.

Multiple player bullets may independently damage the same enemy during the same frame.

Once an enemy reaches 0 HP, it is removed immediately and cannot be hit by later bullets.

## 5.3 Chaser Behavior

Each Chaser continuously calculates the normalized direction from its own center to the player's current center and moves at:

`120 px/s`

Movement uses x-first, y-second axis-separated collision.

If one axis is blocked by a wall or boundary, the other may still move, allowing wall sliding.

Chasers do not use A*, route planning, or alternative-path search.

Chaser contact occurs when:

`distance(chaser_center, player_center) ≤ 34 px`

A valid contact damage event deals 1 HP.

## 5.4 Shooter Movement

A Shooter uses distance `d` from the player:

- `d > 300 px` → move toward the player.
- `180 ≤ d ≤ 300 px` → remain stationary.
- `d < 180 px` → move away from the player.

Approach and retreat use normalized direction vectors at:

`90 px/s`

Shooter movement also uses x-first, y-second collision handling.

If movement is blocked, the Shooter does not search for an alternative route.

## 5.5 Shooter Firing & Line of Sight

Each Shooter has an independent 1.5-second firing timer.

Each timer starts at 0, so the first firing attempt occurs only after a full 1.5 seconds.

The timer advances regardless of Shooter movement state.

At each firing attempt:

1. Check the line segment from Shooter center to player center.
2. Test that segment against all fixed wall rectangles.
3. If any part of the segment intersects or even touches a wall boundary, line of sight is blocked.

Only walls block line of sight.

Other characters do not.

If line of sight is clear:

- Fire exactly one enemy bullet.
- Aim at the player's current center.
- Spawn the bullet 22 px in front of the Shooter.
- Reset the firing timer.

If the bullet spawn position overlaps a wall, the bullet disappears immediately.

If line of sight is blocked:

- No bullet is created.
- The firing timer still resets for another full 1.5-second interval.

A Shooter killed earlier in the same frame cannot move or fire later in that frame.

## 5.6 Enemy Bullets

Enemy bullets:

- Radius: 5 px
- Speed: 280 px/s
- Damage: 1
- Direction: fixed at spawn

They disappear when they:

- Hit a wall.
- Leave the main combat area.
- Collide with the player.

Enemy bullets do not collide with player bullets or other enemy bullets.

If an enemy bullet collides with the player during damage invulnerability, the bullet still disappears even though HP does not decrease.

## 5.7 Enemy HP & Death

Player bullets deal exactly 1 damage.

Enemy HP:

- Chaser: 2
- Shooter: 3

After a valid hit, the enemy briefly displays a hit highlight for approximately 0.1 seconds.

When HP reaches 0:

- Remove the enemy immediately.
- Decrease Enemies by 1.
- Stop its movement.
- Stop its attacks.
- Remove it from later collision processing.
- Stop its firing timer if it is a Shooter.

Enemies never respawn.

## 5.8 Player Damage & Invulnerability

The player starts with:

`HP = 5`

Damage sources:

- Chaser contact
- Enemy bullet hit

Each valid damage event deals:

`1 HP`

After valid damage:

- HP decreases by 1.
- HP is clamped to a minimum of 0.
- Start 0.8 seconds of damage invulnerability.

During invulnerability:

- Additional Chaser contacts cannot reduce HP.
- Enemy bullets cannot reduce HP.
- Enemy bullets that collide still disappear.

The player flashes between normal and semi-transparent appearance every approximately 0.1 seconds during invulnerability.

The player can lose at most 1 HP per frame.

All valid damage contacts for the current frame may be detected, but after one damage instance is applied, no later damage source in that frame can reduce HP again.

If a Chaser remains in contact after the 0.8-second invulnerability expires, it may damage the player again.

## 5.9 Terminal Priority

Terminal conditions are evaluated after the current frame's enemy deaths and player damage have been resolved.

Failure condition:

`HP = 0`

Victory condition:

`Enemies = 0`

Terminal priority is:

1. Game Over
2. Victory
3. Continue

Therefore, if HP and Enemies both become 0 during the same frame, the game enters `game_over`.

---

# 6. Game Flow & Progression

At initialization, the game creates the interface areas, player, 3 Chasers, 3 Shooters, 3 fixed walls, bullet lists, timers, and all state variables.

Initial state:

- Player center: `(400, 560)`
- HP: 5
- Ammo: 6
- Reloading: false
- Firing cooldown: ready for the first valid shot
- Damage invulnerability: inactive
- Chasers: 3, each at 2 HP
- Shooters: 3, each at 3 HP
- Shooter firing timers: 0
- Player bullets: none
- Enemy bullets: none
- Enemies: 6
- Game state: `playing`

While `playing`, each frame follows this fixed update order:

1. Process player input, movement, Reload input, and player shooting using the 0.18-second firing cooldown.
2. Update player bullets and process collisions with walls, arena boundaries, and enemies. Apply enemy damage and immediately remove dead enemies.
3. Update surviving Chaser and Shooter movement, Shooter firing timers, line-of-sight checks, and enemy-bullet spawning.
4. Update enemy bullets and process collisions with walls, arena boundaries, and the player. Record enemy-bullet hits and remove colliding bullets.
5. Process player damage from recorded enemy-bullet hits and Chaser contact, allowing at most 1 HP loss for the frame.
6. Update Reload, firing-cooldown timing, damage-invulnerability, player flashing, and enemy hit-highlight timers.
7. Determine terminal state using Failure-before-Victory priority.

This ordering ensures that a Shooter killed during Step 2 cannot move or fire during Step 3.

If Reload is active when a terminal state is entered:

- Reload is canceled immediately.
- Ammo remains at its current value.
- Reload does not complete afterward.

Terminal evaluation:

1. If HP = 0, enter `game_over`.
2. Otherwise, if Enemies = 0, enter `victory`.
3. Otherwise, continue `playing`.

If HP = 0 and Enemies = 0 in the same frame, Game Over takes priority.

After entering `victory`:

- Clear all player bullets.
- Clear all enemy bullets.
- Preserve the player's final position.
- Preserve the walls.
- Stop all combat updates.
- Cancel Reload.
- Set Status to `Victory`.
- Display `Victory!` and `Press R to Restart`.
- Accept only R.

After entering `game_over`:

- Clear all player bullets.
- Clear all enemy bullets.
- Preserve the player's final position.
- Preserve surviving enemies at their final positions.
- Freeze all characters.
- Stop enemy movement and attacks.
- Cancel Reload.
- Stop further damage.
- Set Status to `Game Over`.
- Display `Game Over` and `Press R to Restart`.
- Accept only R.

Pressing R fully restores:

- Player position, HP, Ammo, Reload state, firing-cooldown state, and invulnerability state.
- All Chaser positions and HP.
- All Shooter positions, HP, and firing timers.
- Bullet lists.
- Enemies = 6.
- Status = `Playing`.
- Game state = `playing`.

After Restart, the player is immediately eligible to fire if all normal shooting conditions are satisfied.

---

# 7. Goal, Feedback & Termination

The player's goal is to defeat all 6 enemies while keeping HP above 0.

The top information area continuously displays:

- `HP: X/5`
- `Ammo: X/6`
- `Enemies: X`
- `Status: X`

A successful shot may occur only after at least 0.18 seconds have elapsed since the previous successful shot.

Shooting immediately decreases Ammo and creates visible white bullets.

While the left mouse button is held, successful shots may repeat at a theoretical maximum rate of approximately 5.56 shots per second, subject to Ammo, Reload, valid aiming direction, and all other shooting conditions.

Reload displays `Reloading...` and restores Ammo to 6 only after the full 1.5-second Reload completes.

Enemy hits shorten their HP bars and produce a brief hit highlight.

Enemy death immediately removes the enemy and decreases Enemies by 1.

Valid player damage immediately decreases HP by 1 and starts the 0.8-second flashing invulnerability period.

The player can lose at most 1 HP in a single frame.

Shooter bullets are visually distinct from player bullets.

Walls block all character movement, all bullets, and Shooter line of sight. Other characters do not block Shooter line of sight.

Failure condition:

`HP = 0`

Victory condition:

`Enemies = 0` while HP remains above 0.

If HP and Enemies both become 0 during the same frame, Game Over takes priority.

After `victory`:

`Victory!`

`Press R to Restart`

After `game_over`:

`Game Over`

`Press R to Restart`

Both terminal states stop all combat updates, clear all bullets, preserve the arena's final configuration, and accept only R to restart.

---

# 8. Functional Checkpoints
