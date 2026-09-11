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
  "difficulty": "medium",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Space Invaders",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      800,
      600
    ]
  },
  "schema_version": 1,
  "family_slug": "space_invaders",
  "variant_id": "var04",
  "instance_id": "space_invaders_var04"
}
---

# Game Specification

## Game Name
Space Invaders

---

# 1. Game Overview
Space Invaders is a single-player fixed-screen shooting game. The player controls a spaceship near the bottom of the screen, moves it horizontally, and fires bullets upward to defeat alien enemies that advance from the upper part of the gameplay area.

Enemies appear in three fixed waves. Each wave consists of multiple independent enemies arranged in a formation. The formation moves slowly downward as a whole while surviving enemies periodically fire bullets toward the player.

The player starts with 3 Lives. When an enemy bullet hits the player, one Life is lost and the player receives a temporary 1-second invulnerability period.

The player wins after defeating all enemies in Wave 3. The game ends in failure if Lives reaches 0, if any surviving enemy reaches the advancement failure line, or if an enemy directly collides with the spaceship.

Unlike classic Space Invaders, enemy formations do not move horizontally and do not reverse direction at screen boundaries. Each formation only advances downward at a fixed speed determined by the current wave.

The game does not include shields, items, additional weapons, horizontal enemy movement, score bonuses for clearing waves, or additional levels.

---

# 2. Game Scene & Interface
The game window is 800 × 600 px and uses a horizontal layout. From top to bottom, it is divided into:
1. Top information area: 800 × 80 px
2. Main gameplay area: 800 × 520 px

## 2.1 Top Information Area
The top information area occupies y = 0–80 and displays two fixed lines.

The first line displays:
`Score: X Lives: Y Wave: Z/3`

where:
- X is the current score.
- Y is the player's remaining Lives.
- Z is the current Wave.

At the start of the game:
`Score: 0 Lives: 3 Wave: 1/3`

The second line displays:
`Move: A/D Shoot: Space`

Both lines use a font size of 28 px.

The top information area uses a dark or dark-blue background, and the text uses white or another high-contrast light color.

## 2.2 Main Gameplay Area
The main gameplay area occupies:
- x = 0–800
- y = 80–600

It displays the player spaceship, player bullets, enemy formations, enemy bullets, and end-state messages.

The area uses continuous pixel coordinates and does not display grid lines.

A dark background should be used to represent space. A small number of static white or light-colored stars may be added for decoration. These stars are visual only and do not participate in collision detection or affect any gameplay object.

## 2.3 Player Spaceship
The player spaceship is represented by a blue rectangle with:
- Size: 50 × 30 px
- Initial center: `(400, 560)`

The spaceship remains near the bottom of the gameplay area and can move only horizontally.

While temporarily invulnerable, it may flash or display a highlighted border.

## 2.4 Player Bullets
Player bullets are represented by yellow narrow rectangles with:
- Size: 6 × 15 px
- Spawn position: top center of the spaceship
- Movement direction: vertically upward

At spawn time, the bullet's horizontal center aligns with the spaceship's horizontal center and its bottom edge is positioned near the top edge of the spaceship.

## 2.5 Enemies
Enemies are represented by purple circles. Each enemy:
- Has a diameter of 30 px.
- Uses a 30 × 30 px bounding rectangle for collision detection.
- Is treated as an independent target.

Enemy formations must not be treated or drawn as a single rectangular object.

The top-left position of a formation refers to the top-left coordinate of the bounding rectangle of the enemy in the first row and first column.

## 2.6 Enemy Bullets
Enemy bullets are represented by orange narrow rectangles with:
- Size: 6 × 15 px
- Spawn position: bottom center of the selected enemy
- Movement direction: vertically downward

## 2.7 End-State Display
After Failure, the center of the main gameplay area displays:
`Game Over`
`Press R to Restart`

After Victory, it displays:
`You Win`
`Press R to Restart`

`Game Over` and `You Win` use a font size of 48 px.

`Press R to Restart` uses a font size of 28 px.

---

# 3. Game Objects & States
The main game objects and state variables include the player spaceship, player bullets, enemies, enemy bullets, score, Lives, Wave, temporary invulnerability state, firing timers, and game state.

## 3.1 Player Spaceship
The spaceship has the following properties:
- Size: 50 × 30 px
- Initial center: `(400, 560)`
- Horizontal movement speed: 300 px/s
- Initial Lives: 3

The spaceship can move only left and right. It cannot move vertically or leave the horizontal boundaries of the main gameplay area.

## 3.2 Player Bullets
Each player bullet:
- Has a size of 6 × 15 px.
- Moves upward at 500 px/s.
- Is removed after leaving the top of the gameplay area.
- Can defeat at most one enemy.
- Does not penetrate enemies.
- Does not collide with enemy bullets.

## 3.3 Enemies
Each enemy has two logical states:
- `alive`
- `defeated`

When a player bullet hits an `alive` enemy, that enemy is immediately defeated and removed, the bullet is removed, and Score increases by 10.

Enemy formations do not move horizontally. Surviving enemies retain their relative formation positions while the formation advances downward at the current wave's fixed speed.

## 3.4 Enemy Bullets
Each enemy bullet:
- Has a size of 6 × 15 px.
- Moves downward at 320 px/s.
- Is removed after leaving the bottom of the gameplay area.
- Continues moving independently after being spawned.
- Remains active even if the enemy that fired it is later defeated.
- Does not collide with player bullets.

## 3.5 Score
The initial score is:
`Score = 0`

Each defeated enemy awards:
`+10`

Wave completion provides no additional score.

The three waves contain:
- Wave 1: 12 enemies
- Wave 2: 18 enemies
- Wave 3: 21 enemies

Total enemies: 51

Maximum possible score: 510

## 3.6 Lives & Invulnerability
The player starts with:
`Lives = 3`

When an enemy bullet overlaps the player while the player is not invulnerable:
- The bullet disappears.
- Lives decreases by 1.
- A 1-second invulnerability period begins.

During invulnerability, an enemy bullet that overlaps the spaceship still disappears, but Lives does not decrease and the existing invulnerability period continues.

All gameplay objects continue updating normally during invulnerability.

If Lives reaches 0, Failure is triggered.

## 3.7 Wave
The game contains exactly 3 Waves.

After every enemy in the current wave has been defeated:
- All player bullets are cleared.
- All enemy bullets are cleared.
- Score is preserved.
- Lives are preserved.
- The spaceship's current horizontal position is preserved.
- The next wave is spawned.

After every enemy in Wave 3 has been defeated, Victory is triggered unless a Failure condition is also satisfied in the same frame.

## 3.8 Game State
The game contains three internal states:
- `running`
- `victory`
- `failure`

During `running`, movement, shooting, enemy movement, firing, bullet updates, and collision detection remain active.

During `victory` or `failure`, gameplay updates stop, A/D/Space have no effect, and only R is accepted to restart.

---

# 4. Player Interaction
The player uses A, D, Space, and R.

## 4.1 Horizontal Movement
A moves the spaceship left and D moves it right.

Movement speed is fixed at:
`300 px/s`

The spaceship can move only horizontally. Its full 50 × 30 px rectangle must remain inside the gameplay area:
- Left edge ≥ 0
- Right edge ≤ 800

Movement and shooting may occur simultaneously.

## 4.2 Shooting
Space fires player bullets.

The player may press Space once, press it repeatedly, or hold it continuously. All methods are limited by the same maximum firing rate:
`5 bullets per second`

Equivalent minimum interval between successful shots:
`0.2 seconds`

Each successful shot:
- Spawns exactly one bullet.
- Spawns it from the top center of the spaceship.
- Sends it vertically upward at 500 px/s.

A bullet cannot be spawned every frame.

## 4.3 Restart
After `victory` or `failure`, pressing R restarts the game.

Restart resets:
- Score to 0.
- Lives to 3.
- Wave to 1.
- Spaceship center to `(400, 560)`.
- Player bullets to empty.
- Enemy bullets to empty.
- Invulnerability state.
- Player firing state.
- Enemy firing timer.
- Wave 1 formation.
- Game state to `running`.

---

# 5. Core Rules & Mechanics

## 5.1 Player Movement & Firing
The spaceship moves horizontally at 300 px/s and cannot leave the gameplay area.

Player bullets have:
- Size: 6 × 15 px
- Speed: 500 px/s upward
- Maximum firing rate: 5 bullets per second
- Minimum successful-shot interval: 0.2 seconds

A player bullet is removed when it leaves the top of the gameplay area or successfully hits one enemy.

## 5.2 Wave Configuration
The game contains three fixed waves:

| Wave | Formation | Enemies | Top-left Position | Downward Speed | Firing Interval |
|---:|---|---:|---|---:|---:|
| 1 | 2 × 6 | 12 | `(120, 110)` | 6 px/s | 1.6 s |
| 2 | 3 × 6 | 18 | `(230, 110)` | 7 px/s | 1.4 s |
| 3 | 3 × 7 | 21 | `(205, 110)` | 8 px/s | 1.2 s |

Each enemy uses a 30 × 30 px bounding rectangle.

Formation spacing is fixed:
- Horizontal gap: 30 px
- Vertical gap: 25 px

The formation moves only downward. Enemies do not move horizontally, reverse direction, or move independently from the formation.

## 5.3 Enemy Firing
Enemy firing is controlled by one wave-level timer.

Whenever the current wave's firing interval is reached:
1. Select one surviving enemy uniformly at random.
2. Spawn exactly one enemy bullet from the bottom center of that enemy.
3. Reset the wave firing timer.

Only one enemy fires during each firing event.

If no surviving enemies remain, no enemy bullet is fired.

Enemy bullets move downward at 320 px/s and continue independently after spawning.

## 5.4 Player Bullet–Enemy Collision
Collision is checked between the player bullet rectangle and an enemy's 30 × 30 px collision rectangle.

When a bullet hits a surviving enemy:
- The enemy is removed.
- The bullet is removed.
- Score increases by 10.

One bullet can defeat at most one enemy and cannot penetrate enemies.

## 5.5 Enemy Bullet–Player Collision
When an enemy bullet overlaps the spaceship:
- If the player is not invulnerable, remove the bullet, decrease Lives by 1, and start 1 second of invulnerability.
- If the player is already invulnerable, remove the bullet without changing Lives.

Player bullets and enemy bullets do not interact with each other.

## 5.6 Wave Transition
A wave ends only after every enemy in that wave has been defeated.

For Wave 1 and Wave 2:
1. Clear all remaining player bullets.
2. Clear all remaining enemy bullets.
3. Preserve Score.
4. Preserve Lives.
5. Preserve the spaceship's current horizontal position.
6. Advance the Wave number.
7. Spawn the next fixed formation.
8. Update the Wave display.

No additional score is awarded for clearing a wave.

## 5.7 Failure Conditions
Failure occurs if any of the following becomes true:
1. Lives reaches 0.
2. The bottom edge of any surviving enemy reaches y = 520.
3. Any surviving enemy overlaps the spaceship.

The advancement failure line at y = 520 represents enemies breaking through the player's defense. Direct overlap with the spaceship is not required for this condition.

## 5.8 Victory Condition
Victory occurs when every enemy in Wave 3 has been defeated.

The player does not need to wait for remaining bullets to leave the screen.

## 5.9 Terminal Priority
Failure has priority over Victory when terminal conditions are satisfied in the same frame.

After gameplay updates and collision results for the frame have been determined:
1. Check whether any Failure condition is satisfied.
2. If Failure is satisfied, immediately enter `failure`.
3. Otherwise, if Wave 3 has no surviving enemies, enter `victory`.
4. Otherwise, continue `running` or perform a normal Wave 1/2 transition if the current wave has been cleared.

Therefore, if the final Wave 3 enemy is destroyed in the same frame that Lives reaches 0, an enemy reaches y = 520, or an enemy collides with the spaceship, the result is Failure rather than Victory.

---

# 6. Game Flow & Progression
At initialization, the game creates the interface, player spaceship, score, Lives, Wave, bullet lists, invulnerability state, firing timers, Wave 1 formation, and game state.

The initial state is:
- Spaceship center: `(400, 560)`
- Score: 0
- Lives: 3
- Wave: 1
- Player bullets: none
- Enemy bullets: none
- Game state: `running`

Wave 1 begins as a 2 × 6 formation at `(120, 110)`.

While `running`, the game processes player movement and shooting, updates player bullets, moves the current enemy formation downward, advances the wave-level firing timer, spawns enemy bullets when required, and updates active enemy bullets at 320 px/s.

Bullets that leave the gameplay area are removed.

The game then resolves player bullet–enemy collisions and enemy bullet–player collisions. Defeated enemies are removed and award 10 points each. Valid enemy bullet hits reduce Lives according to the 1-second invulnerability rule.

After collision resolution, terminal conditions are evaluated using Failure-first priority:
1. Lives = 0.
2. Any surviving enemy bottom edge reaches y = 520.
3. Any surviving enemy overlaps the spaceship.
4. If none of the above applies, check whether the current wave has been cleared.

If Wave 1 or Wave 2 is cleared, all bullets are removed and the next wave begins while Score, Lives, and player horizontal position are preserved.

If Wave 3 is cleared and no Failure condition is active, the game enters `victory`.

After `victory` or `failure`:
- Spaceship movement stops.
- Enemy movement and firing stop.
- Player and enemy bullets stop updating.
- No new bullets are spawned.
- Score, Lives, and Wave stop changing.
- A, D, and Space have no effect.
- The corresponding end-state message is displayed.
- Only R is accepted.

Pressing R restores the entire game to its initial state.

---

# 7. Goal, Feedback & Termination
The player's goal is to defeat all enemies across all three Waves without entering a Failure state.

The top information area continuously displays:
`Score: X Lives: Y Wave: Z/3`
`Move: A/D Shoot: Space`

Each defeated enemy increases Score by 10. Wave completion provides no bonus score.

The player begins with 3 Lives. A valid enemy bullet hit removes one Life and starts 1 second of invulnerability.

Enemy bullets move downward at 320 px/s.

After all enemies in Wave 1 or Wave 2 are defeated, all bullets are cleared and the next wave begins while Score, Lives, and player horizontal position are preserved.

After all enemies in Wave 3 are defeated, the game enters Victory only if no Failure condition is also satisfied.

Victory feedback:
`You Win`
`Press R to Restart`

Failure occurs if:
- Lives reaches 0.
- A surviving enemy's bottom edge reaches y = 520.
- A surviving enemy overlaps the spaceship.

Failure feedback:
`Game Over`
`Press R to Restart`

If Victory and Failure would occur in the same frame, Failure takes priority.

After either terminal state, gameplay updates stop and only R can restart the game.

---

# 8. Functional Checkpoints
