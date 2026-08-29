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
  "difficulty": "easy",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Asteroids",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1
}
---
# Game Specification

## Game Name
Asteroids

---



# 1. Game Overview
Asteroids is a single-screen shooting and avoidance game. The player controls a triangular spaceship within a fixed gameplay area, rotates the ship to change its facing direction, moves forward, fires bullets, and destroys drifting asteroids while avoiding collisions.
Each destroyed asteroid increases the score by 1. If the spaceship collides with any asteroid, the game immediately ends.

The game does not use direct up/down/left/right translation. The player uses the left and right arrow keys to rotate the spaceship, holds the up arrow key to move forward in the current facing direction, and presses Space to fire from the front of the ship.
The spaceship does not use inertia: it moves only while the up arrow key is held and stops immediately when the key is released.

The game has no fixed victory score, completion condition, victory state, or level transition. The player's objective is to destroy as many asteroids as possible and achieve the highest possible score before colliding with an asteroid.

A custom rule in this game is four-edge wrapping. The spaceship, bullets, and asteroids all wrap across the boundaries of the main gameplay area. When an object's center crosses one edge, it immediately re-enters from the corresponding position on the opposite edge.

---



# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into three areas:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays the current score using the fixed format `Score: X`, where X is the number of asteroids destroyed.
At the start of the game, it displays `Score: 0`.

The score text uses a font size of 40 px and should be clearly displayed either on the left side or horizontally centered within the top information area.

## 2.2 Main Gameplay Area
The main gameplay area has a size of 600 × 600 px and covers:
- Top-left: `(0, 100)`
- Bottom-right: `(600, 700)`

The area uses continuous pixel coordinates and does not display grid lines. The spaceship, bullets, and asteroids all move within this area and use four-edge wrapping based on their center positions.

### Spaceship
The spaceship is displayed as a triangle.
Its initial properties are:
- Center: `(300, 400)`
- Facing direction: up
- Approximate visual size: 40 × 40 px
- Collision radius: 18 px

When initially facing upward, the triangle may use the following vertices:
- Front tip: `(300, 380)`
- Rear-left: `(286, 416)`
- Rear-right: `(314, 416)`

When the spaceship rotates, the entire triangle rotates around its center.

### Bullets
Bullets are displayed as small circles with a radius of 4 px. Each bullet is spawned from the front tip of the spaceship and travels in the facing direction recorded at the moment of firing.
The bullet color should clearly contrast with both the background and the asteroids.

### Asteroids
Asteroids are displayed as gray circles with a radius of 25 px.
The game begins with 3 fixed asteroids:

| Asteroid | Initial Center | Initial Velocity |
|---|---|---|
| Asteroid 1 | `(120, 220)` | `(56, 56) px/s` |
| Asteroid 2 | `(500, 300)` | `(-56, 56) px/s` |
| Asteroid 3 | `(250, 620)` | `(56, -56) px/s` |

These velocity vectors correspond to an overall speed of approximately 80 px/s. The initial asteroids are positioned far enough from the spaceship to avoid an immediate collision.
Only subsequently spawned asteroids appear from the edges of the gameplay area. Asteroids do not split and do not actively chase the spaceship.

## 2.3 Bottom Instruction Area
While the game is in the `playing` state, the bottom instruction area displays:
`Rotate: ← / →    Move: ↑`
`Shoot: Space    Restart: R`

Both lines use a font size of 28 px and should be centered.

After the game enters `game_over`, the bottom instruction area displays:
`Game Over`
`Press R to Restart`

`Game Over` uses a font size of 40 px, and `Press R to Restart` uses a font size of 28 px. Both lines should be centered.

The top and bottom areas use a light-gray background, while the main gameplay area uses a black or dark-colored background. The spaceship may use blue, cyan, or white; bullets may use yellow or white; asteroids use gray. All text should use a high-contrast color.

At the start of the game, the spaceship is centered at `(300, 400)` and faces upward, the 3 initial asteroids are present, no bullets are present, the score is 0, and the normal gameplay instructions are displayed.

---



# 3. Game Objects & States
The main game objects and state variables include the spaceship, bullets, asteroids, score, firing cooldown, asteroid spawn timer, and game state.

## 3.1 Spaceship
The spaceship has the following properties:
- Initial center: `(300, 400)`
- Initial facing direction: up
- Collision radius: 18 px
- Rotation speed: 180°/s
- Forward movement speed: 220 px/s

Its state includes the current center position, current facing direction, and whether forward movement input is active.
The spaceship cannot move backward, directly translate left or right, directly translate vertically, or use inertia or drifting movement.

## 3.2 Bullets
Each bullet:
- Has a radius of 4 px.
- Moves at 350 px/s.
- Travels in a fixed direction determined at spawn time.
- Exists for at most 1.5 seconds.
- Uses four-edge wrapping.
- Disappears when it hits an asteroid.
- Does not change direction when the spaceship rotates after firing.

A bullet that reaches the end of its 1.5-second lifetime disappears without changing the score.

## 3.3 Asteroids
Each asteroid:
- Has a radius of 25 px.
- Moves at approximately 80 px/s.
- Moves along a fixed velocity direction after spawning.
- Uses four-edge wrapping.
- Does not chase the player.
- Does not split when destroyed.

The game begins with 3 fixed asteroids, and at most 4 asteroids may exist simultaneously.
Subsequent asteroids are spawned from the edges of the gameplay area according to the rules in Section 5.

## 3.4 Score
Score represents the number of asteroids successfully destroyed by bullets.
The initial value is:
`Score = 0`

Each successfully destroyed asteroid increases the score by 1.
Score does not increase because of survival time, asteroid wrapping, or bullet expiration. The game does not record a separate high score.

## 3.5 Game State
The game contains two states:
- `playing`
- `game_over`

The initial state is `playing`.
The game enters `game_over` when the spaceship collides with any asteroid. After entering `game_over`, all gameplay updates stop and only R is accepted to restart.

---



# 4. Player Interaction
The player uses the left arrow key, right arrow key, up arrow key, Space, and R.

## 4.1 Rotation
The left arrow key rotates the spaceship counterclockwise, while the right arrow key rotates it clockwise.
Rotation speed is fixed at:
`180°/s`

Rotation changes only the spaceship's facing direction and does not directly change its position.

## 4.2 Forward Movement
While the up arrow key is held, the spaceship moves forward along its current facing direction at:
`220 px/s`

When the up arrow key is released, the spaceship immediately stops moving.
The game does not use inertia, acceleration, friction, or drifting. The down arrow key is unused, and the spaceship cannot move backward.

## 4.3 Shooting
Space is used to fire. A shot succeeds only when the 0.25-second firing cooldown has ended.

When a shot succeeds:
- Exactly one bullet is spawned from the spaceship's front tip.
- The bullet records the spaceship's current facing direction.
- The bullet begins moving at 350 px/s.
- The 0.25-second firing cooldown begins.

Pressing Space during the cooldown does not spawn a bullet and does not restart the cooldown.

## 4.4 Restart
After the game enters `game_over`, rotation, forward movement, and shooting inputs have no effect.
Pressing R restarts the game and fully resets the spaceship, asteroids, bullets, score, timers, interface state, and game state.

---



# 5. Core Rules & Mechanics

## 5.1 Spaceship Movement
While the up arrow key is held, the spaceship moves at 220 px/s along its current facing direction. Releasing the key stops movement immediately.
Rotation and forward movement may occur simultaneously while the corresponding keys are held.

The spaceship does not use inertia and cannot move backward or directly translate along the horizontal or vertical axes.

## 5.2 Four-Edge Wrapping
The spaceship, bullets, and asteroids all use the same center-based wrapping rule:
- If `x < 0`, set `x = 600`.
- If `x > 600`, set `x = 0`.
- If `y < 100`, set `y = 700`.
- If `y > 700`, set `y = 100`.

The other coordinate remains unchanged.
Wrapping applies only to the main gameplay area and does not extend into the top information area or bottom instruction area.

## 5.3 Bullet Mechanics
Each successful shot creates exactly one bullet with the following properties:
- Radius: 4 px
- Speed: 350 px/s
- Lifetime: 1.5 seconds
- Firing cooldown: 0.25 seconds

A bullet travels in the direction recorded when it is fired. Later spaceship rotation does not affect existing bullets.
When a bullet reaches the end of its 1.5-second lifetime, it is removed without changing the score.

## 5.4 Initial Asteroids
The game begins with exactly 3 fixed asteroids:
- `(120, 220)`, velocity `(56, 56) px/s`
- `(500, 300)`, velocity `(-56, 56) px/s`
- `(250, 620)`, velocity `(56, -56) px/s`

These asteroids do not use the edge-spawn rules during initialization.

## 5.5 Asteroid Spawn Mechanism
While `playing`, the game checks the current asteroid count once every 1.5 seconds.
At each check:
- If fewer than 4 asteroids exist, spawn exactly 1 new asteroid.
- If 4 asteroids already exist, spawn nothing.

The maximum number of active asteroids is therefore 4.

A newly spawned asteroid is centered 25 px inward from the selected gameplay boundary:

| Spawn Edge | Center Coordinate |
|---|---|
| Left | `x = 25`, `125 ≤ y ≤ 675` |
| Right | `x = 575`, `125 ≤ y ≤ 675` |
| Top | `125 ≤ x ≤ 575`, `y = 125` |
| Bottom | `125 ≤ x ≤ 575`, `y = 675` |

The spawn edge is selected randomly, and the unrestricted coordinate may be selected anywhere within the corresponding range.

## 5.6 Spawned Asteroid Direction & Safety
Every newly spawned asteroid must initially move generally toward the interior of the gameplay area:
- Left-edge spawn: horizontal velocity points right.
- Right-edge spawn: horizontal velocity points left.
- Top-edge spawn: vertical velocity points down.
- Bottom-edge spawn: vertical velocity points up.

The other velocity component may be randomized, but the overall speed should remain approximately 80 px/s.

At spawn time, the distance between the new asteroid center and the spaceship center must be at least 120 px.
If a randomly selected spawn position violates this requirement, reject it and repeatedly select another edge and position until the minimum distance is satisfied.

## 5.7 Bullet-Asteroid Collision
Bullet-asteroid collision uses circular distance-based detection.
A collision occurs when:
`distance(bullet_center, asteroid_center) < 29 px`

When a valid bullet hit is resolved:
- The bullet is removed.
- The asteroid is removed.
- Score increases by 1.
- The score display updates immediately.

A destroyed asteroid does not split, drop items, or immediately respawn. A replacement may appear later only through the normal 1.5-second asteroid-count check.

## 5.8 Spaceship-Asteroid Collision
Spaceship-asteroid collision also uses circular distance-based detection.
A collision occurs when:
`distance(spaceship_center, asteroid_center) < 43 px`

A valid spaceship-asteroid collision immediately causes `game_over`.

If the same asteroid is simultaneously eligible for both a bullet hit and a spaceship collision during the same frame, the spaceship collision has priority. The game enters `game_over`, and that asteroid is not counted as successfully destroyed during that frame.

## 5.9 Excluded Mechanics
The game does not include asteroid splitting, UFO enemies, enemy bullets, HP, shields, items, level transitions, or increasing difficulty.

---



# 6. Game Flow & Progression
At initialization, the game creates the window and interface areas, places the spaceship at `(300, 400)` facing up, sets the score to 0, clears the bullet list, creates the 3 fixed initial asteroids, initializes the firing cooldown and asteroid spawn-check timer, and enters `playing`.

The initial asteroids are:
- Asteroid 1: `(120, 220)`, velocity `(56, 56) px/s`
- Asteroid 2: `(500, 300)`, velocity `(-56, 56) px/s`
- Asteroid 3: `(250, 620)`, velocity `(56, -56) px/s`

While `playing`, the game continuously processes player rotation, forward movement, and shooting input. It updates spaceship, bullet, and asteroid positions, applies four-edge wrapping, advances bullet lifetimes and timers, and performs the 1.5-second asteroid-count check.

After all active object positions have been updated for the frame, collision resolution follows this priority:
1. Detect spaceship-asteroid collisions using the current positions.
2. If any spaceship-asteroid collision exists, immediately enter `game_over`.
3. Otherwise, resolve bullet-asteroid collisions, remove hit bullets and asteroids, and increase the score for each successfully destroyed asteroid.

This ordering ensures that a simultaneous spaceship collision and bullet hit involving the same asteroid is treated as Game Over rather than allowing the asteroid to disappear before the fatal collision is recognized.

After entering `game_over`:
- The spaceship stops moving and rotating.
- Asteroids and bullets stop moving.
- No new bullets or asteroids are created.
- Score stops changing.
- Gameplay inputs no longer affect active objects.
- Final object positions remain displayed.
- The bottom area displays `Game Over` and `Press R to Restart`.

Pressing R fully reinitializes the game. The spaceship returns to `(300, 400)` facing up, score returns to 0, all bullets are cleared, the 3 fixed initial asteroids are restored, all relevant timers are reset, the normal gameplay instructions return, and the game state becomes `playing`.

The following values remain fixed throughout the game:
- Spaceship movement speed: 220 px/s
- Rotation speed: 180°/s
- Bullet speed: 350 px/s
- Bullet lifetime: 1.5 seconds
- Firing cooldown: 0.25 seconds
- Asteroid speed: approximately 80 px/s
- Asteroid spawn-check interval: 1.5 seconds
- Maximum asteroid count: 4

---



# 7. Goal, Feedback & Termination
The player's goal is to destroy as many asteroids as possible before colliding with one and achieve the highest possible score.
The game has no fixed completion score, victory threshold, victory state, or level transition.

The top information area displays `Score: X`, beginning with `Score: 0`. Each asteroid successfully destroyed by a bullet increases X by 1.
Successful shooting creates one bullet at the front of the spaceship. A bullet disappears when it hits an asteroid or reaches its 1.5-second lifetime.

Movement feedback is directly visible through spaceship rotation, forward motion, immediate stopping when the up arrow key is released, and four-edge wrapping of the spaceship, bullets, and asteroids.

During `playing`, the bottom instruction area displays:
`Rotate: ← / →    Move: ↑`
`Shoot: Space    Restart: R`

When the spaceship collides with an asteroid, the game immediately enters `game_over` and displays:
`Game Over`
`Press R to Restart`

The only terminal gameplay condition is:
`distance(spaceship_center, asteroid_center) < 43 px`

If a spaceship collision and bullet hit involving the same asteroid occur during the same frame, the spaceship collision takes priority and the game ends.
After `game_over`, all gameplay updates stop and only R is accepted to restart.

---



# 8. Functional Checkpoints
