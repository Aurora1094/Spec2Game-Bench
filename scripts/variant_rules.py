"""Reviewed rule edits for the final V2--V10 source documents.

IDs below are base checkpoint suffixes. An edit replaces the assertion and its
rubric, not just its visible label. Added probes cover mechanics absent in the
canonical checklist. DOCX excerpts and affected IDs are recorded by the importer.
"""
from __future__ import annotations

from copy import deepcopy
import re


def probe(dimension, initial, trigger, expected):
    return dict(dimension=f"D2.{dimension}", initial_state=initial, trigger=trigger,
                expected_transition=expected)


def static(expected):
    return probe(1, "Fresh initialization", "N/A (static check)", expected)


def rule(*, replacements=(), edits=None, additions=(), types=("parameter",)):
    return dict(replacements=list(replacements), edits=edits or {}, additions=list(additions), types=list(types))


def edit(ids, expected, initial=None, trigger=None):
    value = {"expected_transition": expected}
    if initial is not None:
        value["initial_state"] = initial
    if trigger is not None:
        value["trigger"] = trigger
    return {key: value for key in ids.split()}


def combine(*rules):
    result = rule(types=())
    for value in rules:
        result["replacements"].extend(value["replacements"])
        result["edits"].update(value["edits"])
        result["additions"].extend(value["additions"])
        result["types"].extend(value["types"])
    result["types"] = list(dict.fromkeys([*result["types"], "combination"]))
    return result


def timed(old, new):
    return (rf"(?<![\d.]){re.escape(str(old))}(?![\d.])", str(new))


SNAKE_OBSTACLES = rule(types=("object_count", "map", "rule"), edits={
    **edit("1.03 3.07 5.07", "One food occupies a valid board cell outside the snake and every fixed obstacle."),
}, additions=[
    static("The fixed obstacle cells exactly match the coordinate list in Section 3.3; obstacles are grid-aligned and dark gray."),
    probe(3, "Playing; place the head one movement cell before a fixed obstacle, away from the body", "Advance one movement tick into the obstacle", "Immediately enter game_over before food, growth or scoring; obstacle remains in place."),
    probe(5, "Game over after an obstacle collision; alter the snake and food", "Press R", "Restore the specified initial snake and the complete fixed obstacle layout; food never overlaps either."),
])
SNAKE_TWO = rule(types=("object_count",), edits={
    **edit("1.03", "Exactly two food items occupy distinct cells outside the snake."),
    **edit("3.06", "Remove only the collected item and spawn one replacement; the other food remains unchanged and total returns to two."),
    **edit("3.07", "Replacement food is in the board, outside the updated snake, and distinct from the other food."),
    **edit("5.07", "Restart creates exactly two valid food items on distinct unoccupied cells."),
}, additions=[probe(3, "Playing with two distinct food items; head adjacent to the first", "Eat the first, then approach and eat the second", "Each collection gives one growth cell and one point; after each update exactly two distinct valid food items remain.")])
RULES = {}
RULES["snake"] = [
    rule(edits={**edit("1.02 5.04", "Length is 5; head-to-tail cells are (16,15),(15,15),(14,15),(13,15),(12,15), facing right.")}),
    rule(replacements=[(r"8 times", "10 times")]),
    deepcopy(SNAKE_OBSTACLES), deepcopy(SNAKE_TWO),
    rule(types=("rule",), edits={
        **edit("3.03", "With no food and no pending growth the tail is removed and length stays unchanged.", "Playing; safe path with pending_growth=0"),
        **edit("3.04", "A food adds two pending growth cells: retain tail now and once on the next non-food tick, for total length n+2.", "Playing; no pending growth; head adjacent to food", "Collect food and advance one additional safe non-food tick"),
    }, additions=[static("Pending growth is initially zero."), probe(3, "Playing with one pending growth cell and the head adjacent to the currently occupied tail", "Move into that tail cell", "The tail remains occupied during growth, so this produces self-collision and game_over."), probe(5, "Game over with pending growth", "Press R", "Pending growth resets to zero; the initial three-cell snake is restored.")]),
    rule(types=("rule",), edits={
        **edit("3.08", "Left and right crossings wrap into the opposite column of the same row.", "Head faces outward at left/right edges", "Advance one tick on each edge"),
        **edit("3.09", "Top and bottom crossings immediately cause game_over.", "Head faces outward at top/bottom edges", "Advance one tick on each edge"),
        **edit("5.01", "Top/bottom boundary or self-collision causes game_over; left/right wrap does not.", "Playing; prepare top, bottom and self-collision cases", "Advance into each lethal target"),
    }),
    deepcopy(SNAKE_OBSTACLES),
    rule(types=("object_type", "rule"), edits={**edit("3.05", "Normal food gives +1 point and golden food +2 points; each gives one growth cell.", "Playing; test normal and golden food separately", "Move onto each food type in separate trials")}, additions=[static("One food exists; its initial type follows the same 80% normal / 20% golden selection as respawns."), probe(3, "Playing; controllable random stream covers both food types", "Collect and respawn food repeatedly", "Each spawn independently selects normal with 80% or golden with 20%; normal is brown, golden gold/yellow; no extra simultaneous food is created.")]),
    combine(SNAKE_OBSTACLES, SNAKE_TWO),
]
# Combined obstacles and two foods must satisfy both exclusion rules.
RULES["snake"][8]["edits"].update(edit("1.03 3.07 5.07", "Exactly two distinct valid food cells remain outside the snake and every fixed obstacle."))

DODGE_PAIR = rule(types=("object_count",), edits={**edit("3.01 4.03", "Each 1-second spawn event creates exactly two non-overlapping 40x40 obstacles at y=100, with integer x in [0,560].")}, additions=[probe(3, "Playing; control random positions so the second obstacle would overlap the first", "Advance the spawn timer to its event", "Resample the second x until the two initial rectangles do not overlap; retain both obstacles.")])
DODGE_DASH = rule(replacements=[(r"80\s*px", "120px")])
RULES["dodge_blocks"] = [
    rule(replacements=[(r"300\s*px/s", "360 px/s")]),
    rule(replacements=[(r"200\s*px/s", "260 px/s")]),
    rule(edits={**edit("3.01 4.03", "One obstacle spawns every 0.75 seconds at y=100; interval stays fixed.")}),
    DODGE_DASH,
    rule(replacements=[(r"2 seconds", "1 second"), (r"2-second", "1-second")]),
    DODGE_PAIR,
    rule(types=("object_type", "parameter"), edits={**edit("3.02", "Independently select 40x40 or 60x40 with probability 50% each; normal x in [0,560], wide x in [0,540], y=100.")}, additions=[probe(3, "Playing; a wide obstacle overlaps the player only in its extra 20px width", "Advance collision detection", "Use its actual 60x40 rectangle and trigger game_over.")]),
    rule(types=("object_type", "parameter"), edits={**edit("3.03 4.04", "Normal red obstacles fall at 200px/s, fast dark-red/purple obstacles at 300px/s; remove when top>700.")}, additions=[probe(3, "Playing with a controlled random stream", "Generate normal and fast obstacles and advance one second", "Each type has 50% probability and keeps its assigned speed; normal moves 200px and fast 300px.")]),
    combine(DODGE_PAIR, DODGE_DASH),
]

MOLE_PAIR = rule(types=("object_count", "rule"), edits={
    **edit("3.06", "Each spawn creates exactly two moles in distinct holes, independently selecting each type."),
    **edit("3.07", "Wait 0.3 seconds initially and after both active moles disappear; do not replace an individual mole early."),
    **edit("3.09", "Award the clicked mole's type-specific score and remove only it; keep the other mole and its timer unchanged."),
    **edit("1.02 2.06 5.02", "The active-mole collection is empty."),
}, additions=[probe(3, "A normal and a golden mole are simultaneously active with different elapsed lifetimes", "Hit one and let the other expire", "The hit adds its reward once without resetting the survivor; only after the last disappears does the pair waiting timer begin.")])
MOLE_WAIT = rule(replacements=[(r"0\.3(?!\d)", "0.15")])
RULES["whack_a_mole"] = [
    rule(replacements=[timed(30,45)]), rule(replacements=[timed(1.0,0.8),timed(0.6,0.5)]), MOLE_WAIT,
    rule(replacements=[(r"20%", "35%")]),
    rule(replacements=[(r"\b9 (fixed )?holes", r"16 \1holes")], additions=[static("Exactly sixteen holes form the specified 4x4 layout at the centers listed in Section 2; all are available to random spawning.")]),
    MOLE_PAIR,
    rule(types=("rule",), edits={
        **edit("2.02 2.03", "Every invalid left-button down deducts 1 point; if score becomes negative, immediately enter game_over.", "Playing; choose empty/background/toolbar/waiting-period clicks at score 1 and score 0", "Send one invalid left click per case"),
        **edit("3.10", "A second click after removing a mole is invalid and deducts 1; it can cause score-based game_over."),
    }, additions=[probe(5, "Playing; score=0, time>0, active mole", "Click outside the active mole", "Enter game_over and clear the mole; preserve the remaining time and freeze further score changes."), probe(5, "Playing; time expires in the same frame as a click", "Advance time and send the click in that update", "Countdown expiration takes precedence; neither award nor deduct score.")]),
    rule(types=("rule",), edits={**edit("3.08", "First mole may use any of nine holes; every later spawn chooses one of the eight holes different from the immediately previous one.")}, additions=[probe(3, "Playing; record the previous mole's hole", "Let a mole expire, then spawn the next; repeat with a hit", "Both expiry and hit update previous-hole memory; the next hole differs, but a hole from two spawns ago is permitted."), probe(5, "Game over with previous-hole memory", "Press R and spawn the first mole", "Previous-hole memory is cleared; all nine holes are eligible again.")]),
    combine(MOLE_PAIR, MOLE_WAIT),
]
# Replacements run before assertion edits; use the final interval in pair edits.
RULES["whack_a_mole"][8]["edits"].update(edit("3.07", "Wait 0.15 seconds initially and after both active moles disappear; do not replace either mole early."))

ASTEROIDS_SPEED = rule(replacements=[(r"80\s*px/s", "120 px/s")], edits={**edit("1.02 5.06", "Three initial asteroids have positions (120,220),(500,300),(250,620), velocities (85,85),(-85,85),(85,-85)px/s.")})
ASTEROIDS_FIRE = rule(replacements=[timed(0.25,0.15)])
RULES["asteroids"] = [
    rule(replacements=[(r"220\s*px/s", "280 px/s")]), rule(replacements=[(r"180\s*°/s", "240°/s")]), ASTEROIDS_FIRE,
    rule(types=("rule",), edits={**edit("2.04", "A shot creates a 350px/s bullet only when cooldown permits and fewer than three player bullets exist.")}, additions=[probe(2, "Playing; three active player bullets, cooldown ready", "Press Space, expire one bullet, then press Space again", "At the cap no bullet or cooldown change occurs; below the cap a shot succeeds and starts cooldown.")]),
    ASTEROIDS_SPEED,
    rule(types=("object_count",), edits={**edit("1.02 5.06", "Four initial asteroids: (120,220),(500,300),(250,620),(430,580); the added asteroid has velocity (-56,-56)px/s."), **edit("3.07", "Every1.5-second check spawns exactly one asteroid only when fewer than5 exist; cap is5.")}),
    rule(replacements=[(r"43\s*px", "53px")], additions=[static("All asteroids have radius 35px; circle collision tests and rendering use this radius."), probe(3, "Bullet near a radius-35 asteroid", "Test center distances below, equal to and above 39px", "A bullet hit occurs only below the sum of radii, 39px; asteroid removal awards one point without splitting.")]),
    rule(types=("object_type", "rule"), edits={**edit("3.10", "Ship collision occurs below 43px for normal radius-25 asteroids and below 53px for large radius-35 asteroids.")}, additions=[static("The three initial asteroids are Normal Asteroids of radius 25px."), probe(3, "Playing; control replacement spawning", "Destroy asteroids and inspect the replacements", "Independently select normal/large with50% probability each; bullet collision requires distance<29/39px respectively; award one point regardless of size.")]),
    combine(ASTEROIDS_SPEED, ASTEROIDS_FIRE),
]

MAZE_TIME = rule(replacements=[timed(30,45)])
MAZE_MAP = rule(types=("map",), edits={**edit("1.01", "The complete 15x15 maze exactly matches this instance's fixed map in Section 2."), **edit("1.03", "Exit=(row13,col13); the exit is enterable and reachable from the start.")})
RULES["maze_runner"] = [
    MAZE_TIME, rule(replacements=[timed(0.15,0.10)]),
    rule(replacements=[(r"\(1,\s*1\)", "(5,1)")], additions=[static("The player starts at row5,col1, center(60,320); the fixed maze otherwise stays unchanged.")]),
    rule(replacements=[(r"\(13,\s*12\)", "(12,7)")]), MAZE_MAP,
    rule(types=("rule",), edits={**edit("5.01", "Entering the exit while time>0 and resulting steps<=50 wins; step51 loses even at the exit.")}, additions=[static("Steps starts at 0 and the fixed limit is 50; display Steps:0/50."), probe(5, "Playing adjacent to exit, time>0; independently set steps to49 and50", "Move into the exit", "The first case wins at step50; the second loses at step51. Failed movement never increments steps."), probe(5, "A new trial after step-limit loss", "Press R", "Restore time30, steps0, original map/player, and the 50-step limit.")]),
    rule(types=("rule",), edits={**edit("3.04", "Each wall or out-of-bounds attempt deducts one second, leaves position/steps unchanged and clamps time at zero.")}, additions=[probe(4, "Playing, direction held against wall", "Advance repeated attempts at 0.15-second intervals", "Each failed repeat incurs one additional second penalty on top of elapsed time; steps remains unchanged."), probe(5, "Playing; remaining time below one second, next target is wall", "Attempt movement into wall", "Clamp time to zero and immediately enter lost.")]),
    rule(types=("object_count",), edits={**edit("1.03", "Two fixed exits at (row13,col12) and (row11,col13)."), **edit("5.01", "Reaching either exit while time>0 is sufficient for won; both need not be visited.")}),
    combine(MAZE_MAP, MAZE_TIME),
]
# Final DOCX consistently processes countdown expiration before movement.
for value in RULES["maze_runner"]:
    value["edits"].update(edit("5.02", "When time expires in the same frame as attempted exit entry, lost takes priority.", "Playing beside exit with time expiring this frame", "Advance time and attempt exit entry together"))

SPACE_BULLET = rule(replacements=[(r"250\s*px/s", "320 px/s")], additions=[probe(4, "Playing with one unobstructed enemy bullet", "Advance 0.5 seconds", "The enemy bullet moves downward by160px, independently of the enemy that fired it.")])
RULES["space_invaders"] = [
    rule(edits={**edit("2.01", "A/D moves the ship horizontally at380px/s and clamps it to the battlefield boundaries.")}),
    rule(replacements=[timed(0.2,0.15)], edits={**edit("2.03", "Shots are at least0.15 seconds apart, approximately6.67/s; use timestamps rather than a five-shot cap.")}),
    rule(replacements=[(r"(?i)lives\s*=\s*3", "Lives=5")]), SPACE_BULLET,
    rule(replacements=[(r"1 second", "1.5 seconds"), (r"1-second", "1.5-second")]),
    rule(types=("object_count", "map"), edits={**edit("1.05 5.09", "Wave1 is3x5(15 enemies) at(265,110); restore independent enemies and empty bullet collections."), **edit("3.09", "Wave2 is3x7(21) at(205,110), Wave3 is4x6(24) at(235,110); clear bullets on transition.")}, additions=[probe(5, "Clear the first two waves normally", "Defeat all24 enemies of Wave3", "Win after60 total enemies; at10 points per enemy maximum score is600; no fourth wave.")]),
    rule(types=("object_count",), edits={**edit("4.01", "At each fixed firing event choose two distinct surviving enemies if at least two remain; one survivor fires one bullet and no survivors fire none.")}),
    rule(types=("object_type", "rule"), edits={**edit("3.03", "A player bullet removes one enemy HP and is consumed; normal HP1 gives10 on death, armored HP2 gives20 only on death.")}, additions=[static("Armored formation cells use one-based(row,col): wave1(1,2),(1,5); wave2(1,2),(1,5),(3,2),(3,5); wave3(1,2),(1,6),(2,4),(3,2),(3,6). Other cells are normal."), probe(3, "One armored enemy has2HP", "Hit it twice with separate bullets", "First hit leaves1HP and no score; second removes it and awards20 once; both bullets disappear.")]),
    combine(SPACE_BULLET, rule(edits={**edit("4.01", "Enemy firing intervals are1.3,1.1,0.9 seconds in waves1,2,3; bullets fall at320px/s.")})),
]

PLATFORM_JUMP = rule(replacements=[timed(-420,-500)])
PLATFORM_SPEED = rule(replacements=[(r"80\s*px/s", "120 px/s")])
RULES["simple_platformer"] = [
    rule(replacements=[(r"220\s*px/s", "280 px/s")]), PLATFORM_JUMP,
    rule(replacements=[(r"900\s*px/s", "1100px/s")]), PLATFORM_SPEED,
    rule(replacements=[(r"260", "220"), (r"430", "470")]),
    rule(types=("object_count", "map"), additions=[static("Retain the original spikes and add Spike4 at(455,520),40x20 and Spike5 at(700,520),40x20."), probe(5, "Playing, player above either added spike", "Land on each added spike separately", "Apply the same lethal spike collision as the original spikes.")]),
    rule(types=("object_count", "map"), edits={**edit("1.05 5.11", "Platform1=(300,315) right at80px/s; Platform2=(500,280) left at70px/s."), **edit("3.06", "Platform1 ranges x260..430 at y315; Platform2 ranges x460..620 at y280 with independent direction/timers.")}, additions=[probe(3, "Player standing on top of Platform2, away from walls", "Advance its horizontal motion", "Only a supported player receives Platform2's horizontal displacement; platform reverses at460/620 and keeps y280.")]),
    rule(types=("rule",), edits={**edit("2.04", "A new Space press jumps only while on_ground and Jumps<8; increment Jumps once and set vy=-420.")}, additions=[static("Jumps starts at0; the HUD shows Jumps:0/8."), probe(2, "Playing; on_ground; Jumps=8", "Press Space repeatedly", "No jump or counter increment occurs; using all8 jumps does not end the game."), probe(5, "A trial with8 used jumps", "Press R", "Reset Jumps to0 and all canonical player/platform state.")]),
    combine(PLATFORM_JUMP, PLATFORM_SPEED),
]

TETRIS_FALL = rule(replacements=[timed(0.6,0.45)])
TETRIS_REPEAT = rule(replacements=[timed(0.12,0.08)])
RULES["tetris"] = [
    TETRIS_FALL, TETRIS_REPEAT,
    rule(replacements=[(r"\(-1,\s*3\)", "(-1,2)")]),
    rule(types=("rule",), edits={**edit("2.04", "Soft drop validates two sequential cells: move2 if both valid, move1 without lock if only first valid, lock only if first fails."), **edit("3.02", "Lock when an automatic downward step or the first soft-drop step fails; failure only at soft-drop step2 does not lock.")}, additions=[probe(2, "Playing; exactly one empty row below the piece before an obstruction", "Send one Down action", "Move down one row without locking or resetting the automatic fall timer.")]),
    rule(types=("interface",), edits={**edit("1.05", "No Next label, preview box, outline or other future-piece indication is visible; internal next_piece still exists."), **edit("3.08", "Generate a new internal next_piece without displaying it."), **edit("5.09", "Regenerate current and internal next_piece while keeping every Next preview hidden.")}),
    rule(types=("rule",), edits={**edit("3.05", "For0/1/2/3/4 rows cleared in one lock, add0/100/250/450/700 points respectively; no other move adds score."), **edit("3.06", "Lines increases by the actual simultaneous cleared-row count.")}, additions=[probe(3, "Prepare independent valid locks clearing1,2,3,4 rows", "Lock each prepared piece", "Award100,250,450,700 respectively, without treating each row as a separate100-point event.")]),
    rule(types=("object_count", "interface"), edits={**edit("1.04 5.09", "Generate current_piece plus independent next_piece_1 and next_piece_2."), **edit("1.05", "Show Next1 and Next2 in their two specified4x4 preview boxes."), **edit("3.07", "Promote old next_piece_1 into current at(-1,3)."), **edit("3.08", "Promote old next_piece_2 into next_piece_1, generate a new next_piece_2 and update both previews.")}),
    rule(types=("rule", "interface"), edits={**edit("2.01", "Legal horizontal moves remain unrestricted; non-O rotation succeeds only if fewer than4 successful rotations have been used."), **edit("2.03", "O rotation changes neither shape nor counter; no wall kick is performed.")}, additions=[static("Current-piece rotation count starts0; HUD shows Rotations:0/4."), probe(2, "Non-O piece in open space with3 successful rotations", "Press Up twice, with key release between presses", "Fourth valid rotation succeeds and sets count4; fifth attempt is ignored. Invalid rotations do not consume count."), probe(3, "Current piece has used4 rotations", "Lock it and promote next_piece", "The new current piece starts with rotation count0 and updated HUD.")]),
    combine(TETRIS_FALL, TETRIS_REPEAT),
]

MATCH_FOUR = rule(types=("rule",), edits={
    **edit("1.03", "Initial board has no horizontal/vertical runs of4 or more; triples are permitted."),
    **edit("3.01", "Keep a swap only when the resulting board has a horizontal/vertical run of4+; triples alone cause rollback."),
    **edit("3.06", "Detect all horizontal/vertical runs of at least4; exclude exact triples."),
    **edit("4.02 5.03", "Board is full8x8 with no runs of4 or more; exact triples can remain stable."),
}, additions=[probe(3, "Stable board; create separate swaps yielding exactly3 and exactly4 equal types", "Perform each swap separately", "Triple-only swap rolls back with unchanged Score/Moves; a run of4 is accepted and cleared.")])
MATCH_SIX = rule(types=("object_type",), edits={**edit("1.02", "Six logical types: Red,Blue,Green,Yellow,Purple,Orange; Orange uses#E67E22 and triangle shape."), **edit("3.10", "Refill using all six specified logical types, including Orange.")})
RULES["match3"] = [
    rule(replacements=[(r"64", "49"), (r"8\s*[×x]\s*8", "7x7")], additions=[static("The7x7 board has49 cells,60px each, top-left(90,190); cell coordinates range0..6.")]),
    MATCH_SIX, rule(replacements=[(r"\+10", "+15")]),
    rule(types=("rule",), edits={**edit("1.03 5.03", "Full8x8 board has no initial horizontal, vertical or either diagonal run of3+ identical types."), **edit("3.06", "Detect horizontal, vertical, ascending-diagonal and descending-diagonal runs of3+."), **edit("4.02", "Stop resolving only when no3+ run in any of the four directions remains and the8x8 board is full.")}, additions=[probe(3, "Stable board; an orthogonal swap creates a diagonal run of3", "Perform the swap", "Keep it and clear the diagonal; intersecting gems count only once. Diagonal selection itself still does not swap.")]),
    MATCH_FOUR,
    rule(types=("interface",), additions=[static("Logical Purple remains a fifth distinct type but is rendered orange#E67E22 with a five-pointed-star shape."), probe(3, "Playing; logical Purple gems are displayed orange", "Create a Purple match and refill", "Match by logical type; preserve the orange star appearance in new Purple gems without adding an Orange type.")]),
    rule(types=("interface",), additions=[static("Red is a diamond, Blue a square and Green a circle; their original colors remain. Yellow is a hexagon and Purple a star."), probe(3, "Stable board with the changed gem shapes", "Swap and resolve a match", "Logical-type matching is unchanged and refill retains the specified color/shape mappings.")]),
    rule(types=("rule",), edits={**edit("2.05", "Only orthogonally adjacent gems of different logical types proceed to swap validation.")}, additions=[probe(2, "Waiting; one selected cell has an adjacent gem of the same type", "Click that adjacent same-type gem", "Clear selection and remain waiting; board,Score,Moves unchanged; do not swap or start resolving.")]),
    combine(MATCH_FOUR, MATCH_SIX),
]

SHOP_PRICES = rule(edits={**edit("3.05 4.04", "Selling prices are Apple5, Bread8, Milk10; a fulfilled sale removes one stock and adds the corresponding price.")})
SHOP_INITIAL = rule(edits={**edit("1.01 2.06", "Initial stock is Apple5,Bread3,Milk1.")})
RULES["simple_shop"] = [
    rule(types=("object_type", "interface"), edits={**edit("1.01 2.06", "Apple,Bread,Milk,Orange start with3 units each."), **edit("3.02", "Customer selects one of four products with1/4 probability each.")}, additions=[static("Four shelves and buttons follow the final layout; Orange has maximum9, restock+3 costing8 and selling price5."), probe(2, "Open shop; Orange stock3, Money>=8", "Restock Orange and then fulfill an Orange request", "Restock adds3 and deducts8; sale removes1 and adds5; other products stay unchanged.")]),
    rule(replacements=[(r"Milk", "Orange"), (r"milk", "orange")], types=("object_type",)),
    SHOP_PRICES, rule(edits={**edit("2.01", "Successful restocking adds3 and costs Apple5,Bread8,Milk11; only affordable non-overflowing actions succeed.")}), SHOP_INITIAL,
    rule(edits={**edit("1.02 3.10", "Each product's maximum stock is12."), **edit("2.01 3.09", "Restock only when affordable and stock<=9; add3 and charge the unchanged product cost.")}),
    rule(types=("rule",), edits={**edit("2.01 3.09 4.03", "Apple restock+2 requires stock<=7 and Gold>=6; Bread+3 requires stock<=6 and Gold>=9; Milk+4 requires stock<=5 and Gold>=12.")}),
    rule(types=("parameter", "rule"), edits={**edit("1.01 2.06", "Initial stocks: Apple2,Bread4,Milk6."), **edit("1.02 3.10", "Maximum stocks: Apple8,Bread10,Milk12."), **edit("2.01 3.09 4.03", "Restock amounts Apple2,Bread3,Milk4; require current stock<=6/7/8 respectively and Money>=6/9/12; reject overflow without partial refill.")}),
    combine(SHOP_INITIAL, SHOP_PRICES),
]

CARROT_MAP = rule(types=("map",), edits={**edit("1.01", "Use every path cell and buildable cell from this instance's final map; tower placement excludes all path cells.")}, additions=[probe(4, "Playing; an enemy at this instance's entrance", "Advance along the full route", "Visit the specified path-cell centers in order, reaching this instance's carrot endpoint; no teleport or base-map shortcut."), probe(5, "Altered route progress and towers", "Press R", "Restore the complete variant map, entry/exit and enemy routing state.")])
RULES["carrot_defense"] = [
    rule(edits={**edit("1.02 2.04", "Gold=150"), **edit("3.01", "Build Basic for60 or Freeze for80 on eligible cells, deducting exactly that cost.")}),
    rule(edits={**edit("4.02", "Normal/Fast/Tank move at60/110/40px/s; Fast has30HP and Tank130HP.")}, additions=[static("Enemy types retain Normal defaults; Fast HP30 speed110, Tank HP130 speed40; rewards and carrot damage are unchanged.")]),
    rule(types=("object_count", "rule"), edits={**edit("5.02", "Victory occurs after Wave5 is fully cleared with carrotHP>0; clearing Wave4 alone does not win.")}, additions=[probe(4, "Wave4 cleared with HP>0", "Wait through preparation and advance Wave5 spawning", "Spawn Normal,Fast,Tank,Fast,Normal,Tank,Fast,Normal,Fast,Tank,Normal,Fast,Tank,Fast at0.8s intervals; total14, no overlapping waves.")]),
    combine(CARROT_MAP, rule(edits={**edit("4.01", "Enemies spawn from(0,0) every0.8 seconds in prescribed type order and follow the upper-left route to(11,3).")}, types=("map",))),
    combine(CARROT_MAP, rule(edits={**edit("4.01", "Enemies spawn from(0,2) every0.8 seconds and follow the final route to carrot(11,6).")}, types=("map",))),
    combine(CARROT_MAP, rule(types=("object_count", "rule"), edits={**edit("4.01", "Odd-index enemies per wave enter at A(0,1), even at B(0,6),0.8s apart; both routes merge at(3,3) and end(11,3).")}, additions=[probe(3, "Enemies on both entrance routes have different remaining route distances", "Let a tower choose among in-range targets", "Apply the specified progress-to-carrot targeting consistently across both assigned routes; all path cells forbid tower construction.")])),
    combine(CARROT_MAP, rule(types=("rule",), edits={**edit("4.01", "Spawn at(0,3); odd-index enemies per wave take Upper, even take Lower; split(3,3), merge(8,3), carrot(11,3).")}, additions=[probe(4, "Enemies of alternating sequence parity approach split(3,3)", "Advance through split and merge", "Each stays on its fixed assigned route; no random reassignment; both complete routes contain16 cells.")])),
    rule(edits={**edit("3.05", "Basic deals20 every0.8s within140px."), **edit("3.06", "Freeze deals8 every1.2s and reduces movement to50% for1.5s."), **edit("3.07", "Repeated Freeze hits reset slow duration to1.5s without multiplying the50% speed reduction.")}),
    rule(edits={**edit("3.09", "Reaching carrot removes enemy without kill reward; Normal/Fast deal1HP, Tank3HP."), **edit("3.10", "A fully perfect wave awards50 Gold exactly once; show Perfect Wave! +50 Gold.")}),
]

RULES["farming_lite"] = [
    rule(edits={**edit("1.02 5.06", "Gold=100"), **edit("3.01", "Plant Carrot/Pumpkin stage0 only in empty plots with enough Gold; deduct10/22 respectively.")}),
    rule(edits={**edit("3.07", "Harvest mature Carrot for22 Gold or Pumpkin for60."), **edit("5.02", "Final automatic harvest gives22 per mature Carrot and60 per mature Pumpkin, updating total/category counts.")}),
    rule(replacements=[timed(30,25)]),
    rule(replacements=[(r"8th", "10th"), (r"Day ?8", "Day10"), (r"day ?8", "day10"), (r"1/8", "1/10")], additions=[probe(4, "Day8 Time about to expire", "Advance to the next day", "Continue to Day9, then10; only after Day10 growth does final automatic harvest and settlement occur.")]),
    rule(edits={**edit("4.04", "Carrot matures at stage3, after3 effective growth events."), **edit("4.05", "Pumpkin matures at stage5, after5 effective growth events.")}, additions=[probe(3, "Carrot stage2 and Pumpkin stage4, watered today", "Try premature harvest, then complete the day", "Neither can be harvested before growth; after settlement they reach mature3/5 and use the specified mature graphics.")]),
    rule(types=("rule",), edits={**edit("4.06", "Each unwatered immature crop regresses one stage at day end, clamped at0; mature crops never regress.")}, additions=[probe(4, "Unwatered immature stage1, unwatered stage0, mature unwatered and watered immature crops", "Complete a day", "Stage1 regresses to0, stage0 stays0, mature stays mature, watered immature grows1; no Gold change from regression.")]),
    rule(types=("rule",), edits={**edit("3.03", "An eligible immature unwatered crop can be watered only with Gold>=1; set watered=true and deduct1.")}, additions=[probe(3, "Gold0; independently prepare empty, mature, already-watered and eligible plots", "Select water and click each", "Check failures in that order: No crop here; mature no effect; Already watered today; eligible Not enough gold. No failed action charges Gold.")]),
    rule(types=("object_type",), replacements=[(r"Pumpkin", "Corn"), (r"pumpkin", "corn")], edits={**edit("3.01", "Plant Carrot for8 or Corn for14, creating stage0."), **edit("3.07", "Harvest mature Carrot for18 or Corn for36."), **edit("4.05", "Corn matures at stage3 after3 effective growth events."), **edit("5.02", "Final automatic harvest adds18 for mature Carrot and36 for mature Corn and counts both categories.")}, additions=[static("Available crops are Carrot and Corn; Corn replaces Pumpkin, uses key2, costs14, matures at3 and rewards36.")]),
    rule(types=("rule",), edits={**edit("5.02", "After Day8 growth, do not automatically harvest any crop; grant no Gold or harvest counts for remaining crops."), **edit("5.03", "Both remaining mature and immature crops provide no final earnings or statistics.")}, additions=[probe(5, "Day8 Time expires with mature, newly maturing and immature crops; record Gold and harvest counters", "Run final growth settlement", "Apply growth once, then enter settlement without auto-harvesting; all recorded Gold/counts reflect manual harvests only; no post-expiry manual action succeeds.")]),
]

PIPE_MAP = rule(types=("map",), edits={**edit("1.04 2.07 5.04", "Restore this instance's exact6x6 grid, cell types, fixed objects and initial pipe orientations from Section5.1.")})
RULES["pipe_connection"] = [
    rule(replacements=[timed(30,24)]),
    rule(replacements=[(r"(?<!counter)clockwise", "counterclockwise")], additions=[probe(2, "Editing; CNE and TNES pipes, Moves<30", "Click each once", "CNE becomes CWN and TNES becomes TWNE; moves+1 each. Straight alternates, fixed cells do not rotate.")]),
    rule(types=("rule",), edits={**edit("2.06", "Won is terminal; an invalid submission remains editing and allows rotation or resubmission."), **edit("3.09", "An invalid submission leaves editing, orientations and Moves unchanged; keep current water/leak visualization."), **edit("4.01 4.02", "Failed results remain visible while editing; a successful rotation clears them to WaterOff/Leaks0; resubmit replaces results."), **edit("5.02 5.03", "Only successful won is frozen and accepts only R; invalid submissions are nonterminal.")}, additions=[probe(2, "Editing after an invalid submission with30 moves", "Press Space again, then try rotating", "Reevaluate without changing Moves or pipe orientations; rotation remains blocked at30; no automatic failure."), probe(2, "Editing after invalid submission with fewer than30 moves and visible errors", "Rotate an eligible pipe", "Apply one rotation and Moves+1; clear all previous blue highlights, red X, leak count and sink results.")]),
    combine(PIPE_MAP, rule(edits={**edit("1.02", "Sinks are at the two fixed positions specified in this instance's final map, with west-facing entrances.")}, types=("map",))),
    combine(PIPE_MAP, rule(edits={**edit("1.03", "Fixed Leak=(2,0); (3,2) is an ordinary pipe."), **edit("3.06", "Each source-reachable outlet into Leak(2,0) counts once; (3,2) has ordinary bidirectional pipe semantics.")}, types=("map",))),
    combine(PIPE_MAP, rule(types=("map",), additions=[probe(2, "Editing; inspect the six exchanged Block/Pipe cells", "Click(1,2),(3,5),(4,2), then(1,4),(4,1),(5,2)", "First three Blocks do not rotate or spend Moves; last three TESW,CES,SV pipes rotate normally.")])),
    combine(PIPE_MAP, rule(edits={**edit("1.01", "Source=(0,2), east-facing; (0,0) is an ordinary SV pipe."), **edit("3.01", "Water begins at Source(0,2) E outlet toward(0,3), which needs a W connection.")}, types=("map",))),
    combine(PIPE_MAP, rule(types=("map", "object_type"), additions=[probe(2, "Editing; (2,3)=TESW,(2,4)=CNE,(3,3)=TNES", "Rotate each once", "Use T,Corner,T rotation cycles respectively; matching the old base types is incorrect."), probe(3, "Arrange source-reachable branches that rejoin", "Press Space", "Evaluate every reached branch, avoid infinite revisits and count each independent invalid outlet once.")])),
    rule(types=("rule",), edits={**edit("3.08", "Win when at least one sink is reached and Leaks<=1; a winning result may retain one red X."), **edit("3.09", "Fail when no sink is reached or Leaks>=2.")}, additions=[probe(3, "Prepare four submissions: one sink/0 leaks, one sink/1 leak, no sinks/0 leaks, both sinks/2 leaks", "Submit each configuration separately", "First two win; last two fail. Only source-reachable invalid outlets contribute leaks.")]),
]

RULES["arena_shooter"] = [
    rule(edits={**edit("1.02 5.10", "HP=7; maximum7." )}),
    rule(edits={**edit("1.03 2.08 5.11", "Ammo=8; capacity8."), **edit("2.06", "R starts1.5-second Reload only when Ammo<8; full-magazine R has no effect.")}),
    rule(replacements=[timed(0.25,0.18)]),
    rule(types=("object_count",), edits={**edit("1.05", "Four Chasers with2HP at(110,145),(690,145),(135,500),(665,500)."), **edit("1.06", "Two Shooters with3HP at(610,245),(210,335), independent1.5s firing timers."), **edit("5.13", "Restore the four specified Chasers and two specified Shooters with their original HP and positions.")}),
    rule(edits={**edit("3.06", "Chasers pursue at150px/s using wall/boundary collision.")}),
    rule(edits={**edit("3.07", "At speed90px/s, approach for d>340, stay for220<=d<=340, retreat for d<220; boundary equality stays stationary.")}, additions=[probe(3, "Shooter without collision obstruction; set distances219,220,340,341 in separate cases", "Advance AI movement", "Retreat,stay,stay,approach respectively; line-of-sight shooting remains independent.")]),
    rule(types=("map",), edits={**edit("1.07", "Walls: A(150,210)190x45, B(390,300)55x140, C(490,445)145x45." )}, additions=[probe(3, "Prepare movement, bullet spawn, bullet flight and shooter line-of-sight cases against each new wall", "Advance each case", "Player/enemy collision, both bullet types and line-of-sight all use the same three variant rectangles, including immediate bullet removal if spawned inside a wall.")]),
    rule(replacements=[timed(0.8,0.5)], additions=[probe(3, "Player in continuous Chaser contact, initially vulnerable", "Apply damage, then advance to0.49 and0.50 seconds", "No extra damage before0.5 seconds; damage becomes possible on expiry; at most1HP lost per frame.")]),
    rule(types=("rule",), edits={**edit("5.05", "If the last enemy dies in the same frame HP reaches0, victory takes priority after all prescribed damage processing.")}, additions=[probe(5, "Last enemy at1HP and player at1HP with simultaneous valid damage events", "Advance the complete update through terminal evaluation", "Both reach0 but state becomes victory; if any enemy survives atHP0, game_over instead.")]),
]

RULES["mini_zelda"] = [
    rule(edits={**edit("1.03 5.08", "HP=7; maximum7.")}),
    rule(replacements=[timed(0.45,0.30)]),
    rule(types=("parameter",), additions=[probe(3, "Player locked facing an enemy, with and without a nearer wall", "Start a sword attack and sample its rectangle", "Sword extends54px from the player's circle edge, width34, active0.20s; clip at nearest blocking wall before testing hits.")]),
    rule(types=("object_type",), edits={**edit("1.08", "RoomB has SlimeB1(220,250)2HP and GuardB1(580,250)3HP, initially patrol down along x580,y170..280."), **edit("3.12", "Spawn Key1 at(400,350) only after SlimeB1 and GuardB1 are dead." )}, additions=[probe(4, "GuardB1 has moved or entered chase in RoomB", "Leave RoomB and return", "Preserve GuardB1 position/HP/AI; no room crossing or duplicate enemy/key creation.")]),
    rule(edits={**edit("3.06", "A patrolling Guard enters chase at player distance<=220px; once chasing, it never returns to patrol.")}, additions=[probe(3, "Patrolling Guard; player at exactly220px then farther away", "Advance AI and move player beyond220px", "Guard enters chase at equality and never returns to patrol; chase speed110px/s.")]),
    rule(types=("rule",), edits={**edit("3.18 3.19", "Unlock C-D with Key1 without consuming it; C-E requires both Key1 and Key2 and consumes both, Keys decreases2.")}, additions=[probe(3, "Hold only Key1 at C-D, then obtain Key2", "Unlock C-D and later C-E", "Keys follows0->1->2->0; key1 remains held after C-D; both collected flags stay true after C-E consumes the keys; neither key respawns.")]),
    rule(types=("map",), additions=[static("RoomD obstacles are D1(390,180)80x90,D2(390,430)80x90,D3(540,310)100x70; other rooms retain their maps."), probe(3, "Player/enemies/sword near each RoomD obstacle", "Move and attack toward each obstacle", "All movement and sword clipping use the variant rectangles; entry(95,350) and Key2(600,240) remain unobstructed.")]),
    rule(types=("rule",), edits={**edit("3.13", "Spawn Key2 at(600,240) after both GuardsD1/D2 die, regardless of SlimeD1; do so once only.")}, additions=[probe(3, "Both Guards dead, SlimeD1 alive in RoomD", "Collect Key2, leave and return", "SlimeD1 stays alive and active; preserve its HP/position, and Key2 never respawns.")]),
    rule(types=("rule",), edits={**edit("3.03", "Sword does not affect keys or doors; a valid clipped active sword rectangle can open the closed RoomE chest."), **edit("5.01", "A valid sword hit opens the RoomE chest and produces victory only ifHP>0.", "Playing inRoomE with closed chest andHP>0", "Attack so the active clipped sword rectangle overlaps the chest")}, additions=[probe(3, "Player inRoomE adjacent to closed chest, no active attack", "Move into the chest", "Chest blocks physical movement and remains closed; touching it never wins."), probe(3, "Closed chest behind a blocking wall relative to the attack", "Swing the sword", "Clipped attack cannot open the chest through the wall; chest itself does not prematurely block its own valid sword hit.")]),
]
# The corrected base dataset and the final documents use HP failure priority.
# Keep that behavior in every Mini Zelda variant, except where another rule
# explicitly changes the chest interaction itself.
for value in RULES["mini_zelda"]:
    value["edits"].update(edit("5.02", "If HP reaches0 in the same frame the chest opens, game_over takes priority.", "HP1 and a valid chest-opening event coincide with lethal damage", "Advance the complete frame through terminal resolution"))

# These coupled assertions share setup text in the canonical checklist. Update
# their setup as well as the scored outcome when the mechanic changes.
for index in (4, 8):
    RULES["match3"][index]["replacements"].extend([
        (r"three horizontal and vertical connections", "four horizontal or vertical connections"),
    ])
RULES["farming_lite"][3]["replacements"].append((r"Day=8", "Day=10"))
RULES["farming_lite"][4]["replacements"].append((r"2/4 of", "3/5 of"))
RULES["farming_lite"][7]["replacements"].append((r"2/4 of", "2/3 of"))
RULES["mini_zelda"][4]["replacements"].append((r"180px range", "220px range"))
RULES["simple_shop"][1]["additions"].extend([
    static("Orange replaces Milk: initial3, maximum9, restock+3 costing8, sale price5; product selection remains one of three with equal probability."),
    probe(2, "Open; Orange stock3 and Money8", "Restock Orange, then fulfill one Orange request", "Money becomes0 and stock6 after restocking; the sale produces Money5 and stock5. No Milk product remains."),
])
RULES["asteroids"][6]["edits"].update(edit("3.08", "Spawn radius35 asteroids inward from the selected edge: left x35/y135..665, right x565/y135..665, top y135/x135..565, bottom y665/x135..565."))
RULES["asteroids"][7]["edits"].update(edit("3.08", "Normal radius25 spawns at x25/575 or y125/675; large radius35 at x35/565 or y135/665; the other coordinate stays inside that radius-adjusted edge range."))
RULES["pipe_connection"][3]["edits"].update(edit("1.02", "Sink1=(0,5), Sink2=(4,5), both west-facing; (5,5) is Block and (4,4) is SV."))
for value in RULES["arena_shooter"][:8]:
    value["edits"].update(edit("5.05", "If HP and Enemies both reach0 in one frame, game_over takes priority.", "Player and last enemy each have1HP; valid simultaneous damage", "Complete the frame through terminal resolution"))


def apply_rule(base_rows, family, variant_number):
    selected = RULES[family][variant_number - 1]
    rows = deepcopy(base_rows)
    changed = []
    for row in rows:
        suffix = row["id"].split(".D2.")[1]
        original = deepcopy(row)
        # Apply replacements only to prose, never IDs or score keys.
        def replace(value):
            if isinstance(value, str):
                for pattern, replacement in selected["replacements"]:
                    value = re.sub(pattern, replacement, value)
                return value
            if isinstance(value, dict):
                return {k: replace(v) for k, v in value.items()}
            return value
        for field in ("objective", "initial_state", "trigger", "expected_transition", "score_rubric"):
            row[field] = replace(row[field])
        if suffix in selected["edits"]:
            row.update(selected["edits"][suffix])
            row["objective"] = "Verify: " + row["expected_transition"]
            row["score_rubric"] = rubric(row["expected_transition"])
        row["base_checkpoint_id"] = original["id"]
        if any(row[k] != original[k] for k in original):
            changed.append(row["id"])
    expected_ids = set(selected["edits"])
    if expected_ids - {row["id"].split(".D2.")[1] for row in rows}:
        raise ValueError(f"{family}: an edit references an unknown base checkpoint")
    for addition in selected["additions"]:
        dimension = addition["dimension"]
        ordinal = sum(row["dimension"] == dimension for row in rows) + 1
        row = {**addition, "id": f"{family}.{dimension}.{ordinal:02d}", "game_slug": family,
               "item": base_rows[0]["item"], "base_checkpoint_id": None,
               "objective": "Verify: " + addition["expected_transition"],
               "detection_method": "State snapshots, controlled input/time, and corresponding visual evidence",
               "score_rubric": rubric(addition["expected_transition"])}
        rows.append(row)
        changed.append(row["id"])
    rows.sort(key=lambda row: row["id"])
    return rows, changed, selected["types"]


def rubric(expected):
    return {"0": "The required state/trigger cannot be established or the required behavior is absent.",
            "1": "The behavior is partly implemented, but at least one specified condition, value, ordering or boundary is wrong.",
            "2": "The required state, trigger and complete expected behavior are satisfied: " + expected}
