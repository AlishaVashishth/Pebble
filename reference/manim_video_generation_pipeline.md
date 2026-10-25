# Manim Video Generation Pipeline (with Audio) — Complete Technical Guide

This document explains **end-to-end detail** of the pipeline used in this repository
(`manim_generator`) to generate an educational explainer video that combines
**LLM-generated Manim visualizations** with **TTS narration audio**, muxed and
stitched into one final MP4.

> This guide covers the **core visualization pipeline only** — scene planning,
> Manim code generation + rendering, narration script writing, TTS audio
> generation, per-scene audio/video muxing, and final stitching. The optional
> avatar/face video stage is intentionally **out of scope**.

---

## 1. High-Level Architecture

The pipeline is a FastAPI service (`app/main.py`) that orchestrates **5 stages**.
Each stage is an independent module under `app/stages/`, and each communicates
with an LLM (Azure OpenAI) or external tools (Manim CLI, Azure TTS, FFmpeg).

```
POST /explain?topic=...&level=school&persona=teacher
                    │
                    ▼
        generate_video_id()   ──►  uuid4().hex  (e.g. "08ae0de5...")
                    │
        ┌───────────────┴────────────────────────────────────────┐
        │                                                        │
        ▼                                                        │
STAGE 1  Scene Planning (scene_planner.txt + LLM)                │
  └─► outputs/scenes.json                                        │
        │                                                        │
        ▼                                                        │
STAGE 2  Manim Code Gen + Render (category prompt + LLM + manim) │
  ├─► outputs/animation.py      (all Scene classes)              │
  ├─► outputs/timestamps.json   (per-animation durations)        │
  └─► outputs/scenes/NN_scene_N.mp4  (one video per scene)       │
        │                                                        │
        ▼                                                        │
STAGE 3  Narration Script (script_writer.txt + LLM)              │
  └─► outputs/script.json                                        │
        │                                                        │
        ▼                                                        │
STAGE 4  TTS Audio (Azure Speech, scene-by-scene)                │
  └─► outputs/audio/<video_id>/scene_N.wav                       │
        │                                                        │
        ▼                                                        │
STAGE 5  Mux + Stitch (FFmpeg)                                   │
  ├─► outputs/videos/<video_id>/scenes_with_audio/NN_scene_N.mp4 │
  └─► outputs/videos/<video_id>/final.mp4                        │
```

### Repository layout

```
.
├── app/
│   ├── main.py                     # FastAPI entrypoint, orchestrates all stages
│   ├── paths.py                    # BASE_DIR / PROMPTS_DIR / OUTPUTS_DIR / MEDIA_DIR
│   ├── stages/
│   │   ├── stage1_scenes.py        # Topic → scenes JSON
│   │   ├── stage2_manim.py         # Scenes → Manim code → rendered MP4s
│   │   ├── stage3_script.py        # Scenes+timestamps → narration script
│   │   ├── stage4_tts.py           # Script → WAV audio per scene
│   │   └── stage5_stitch.py        # Mux audio+video, concat final
│   ├── utils/
│   │   ├── llm.py                  # Azure OpenAI chat-completions wrapper
│   │   ├── json_safe.py            # Robust JSON extraction from LLM output
│   │   ├── timestamps_extractor.py # Regex-parse self.play()/self.wait() durations
│   │   └── generate_uid.py         # uuid4().hex video ID
│   ├── prompts/
│   │   ├── scene_planner.txt       # Shared scene-planning prompt
│   │   ├── maths_manim.txt         # Per-subject Manim codegen prompts
│   │   ├── physics_manim.txt
│   │   ├── chemistry_manim.txt
│   │   ├── biology_manim.txt
│   │   ├── computer_science_manim.txt
│   │   └── script_writer.txt       # Narration prompt
│   └── outputs/                    # Intermediate JSON + media artifacts
├── media/                          # Manim's own scratch dir (cleaned every render)
├── requirements.txt
└── a.py
```

### Key path constants (single source of truth)

`app/stages/stage2_manim.py` and `app/stages/stage5_stitch.py` both resolve the
project root from the module file location, so renders and muxing always land in
the same directories **regardless of the current working directory**:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]   # app/stages/xxx.py → project root
MEDIA_DIR    = PROJECT_ROOT / "media"
OUTPUTS_DIR  = PROJECT_ROOT / "outputs"
```

⚠️ **CRITICAL:** `render_scene()` runs `manim` with `cwd=PROJECT_ROOT`.
If manim were invoked from `app/`, it would write media output to an unwanted
`app/media/` tree and the scene-video "move" step (`MEDIA_DIR.rglob(...)`)
would fail to find the render.

---

## 2. LLM Layer (`app/utils/llm.py`)

All LLM calls go through one wrapper on **Azure OpenAI**:

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    api_version=api_version,             # AZURE_OPENAI_API_VERSION, e.g. "2024-06-01"
    azure_endpoint=endpoint,             # AZURE_OPENAI_ENDPOINT
    api_key=subscription_key,            # AZURE_API_KEY
)

def call_llm(prompt: str, temperature=0):
    response = client.chat.completions.create(
        model=deployment_name,           # AZURE_OPENAI_DEPLOYMENT
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content
```

- `temperature=0` everywhere → deterministic, reproducible output.
- Environment comes from `.env` (loaded via `python-dotenv`). The exact block
  used by this pipeline (values left blank must be filled in with your own
  resource credentials):

```bash
# ── Azure OpenAI (scorer/codegen LLM) ───────────────────────────
AZURE_OPENAI_ENDPOINT=                # e.g. https://<resource>.openai.azure.com/
AZURE_API_KEY=                        # Azure OpenAI subscription key
# Alternate key var accepted by the video service (falls back to AZURE_API_KEY):
# AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini
AZURE_OPENAI_API_VERSION=2024-06-01
# Alternate LLM provider for the video stage codegen (default: azure):
# LLM_PROVIDER=azure

# ── Azure Speech (video TTS) ────────────────────────────────────
AZURE_SPEECH_KEY=
AZURE_SPEECH_REGION=uaenorth
```

| Env var                    | Purpose                                                          |
|----------------------------|------------------------------------------------------------------|
| `AZURE_OPENAI_ENDPOINT`    | Azure resource endpoint URL                                      |
| `AZURE_API_KEY`            | Azure OpenAI subscription key                                    |
| `AZURE_OPENAI_API_KEY`     | *Optional* alternate key var; service falls back to `AZURE_API_KEY` |
| `AZURE_OPENAI_DEPLOYMENT`  | Deployment (model) name — here `gpt-5.4-mini`                    |
| `AZURE_OPENAI_API_VERSION` | API version string — here `2024-06-01`                           |
| `LLM_PROVIDER`             | *Optional*; codegen provider selector, defaults to `azure`        |
| `AZURE_SPEECH_KEY`         | Azure Speech (TTS) subscription                                  |
| `AZURE_SPEECH_REGION`      | Azure Speech region — here `uaenorth`                            |

### JSON safety net (`app/utils/json_safe.py`)

LLMs sometimes wrap JSON in prose/code fences. `extract_json(text)`:

1. First tries `json.loads(text)` directly.
2. On failure, regex-grabs the first `{...}` block (`re.search(r"\{[\s\S]*\}", text)`) and parses that.
3. Raises `ValueError("No JSON object found in LLM output")` if nothing parseable.

Used in **Stage 2** to pull `{"manim_code": ..., "timestamps": ...}` out of the
LLM response.

---

## 3. Stage 1 — Scene Planning (`app/stages/stage1_scenes.py`)

**Input:** raw educational answer/topic (`topic`) + difficulty `level`
**Prompt:** `app/prompts/scene_planner.txt` (shared across subjects)
**Output:** `outputs/scenes.json`

### Flow

```python
prompt = (PROMPTS_DIR / "scene_planner.txt").read_text()
prompt = prompt.format(topic=topic, level=level)
output = call_llm(prompt)
scenes = json.loads(output)
Path("outputs/scenes.json").write_text(json.dumps(scenes, indent=2))
```

### What the scene-planner prompt enforces

- **Output ONLY valid JSON** (no markdown, no prose).
- Each scene = **exactly ONE idea**, following the logical flow of the answer.
- Each scene must describe a **concrete visual action** drawable in Manim
  (shapes, arrows, highlights, transformations, graphs, motion) — 2D style.
- Scene duration target: **5–12 seconds** each.
- **No narration/dialogue** at this stage; no new concepts beyond the answer.
- Pick **one category** per answer: `biology | physics | maths | chemistry | computer_science`.

### Output schema

```json
{
  "category": "physics",
  "scenes": [
    {
      "scene_id": 1,
      "concept": "Introduction to Newton's Laws of Motion",
      "visual": "Display the title 'Newton's Laws of Motion' centered on screen with three numbered bullet points appearing sequentially..."
    }
  ]
}
```

`category` is the critical piece: it selects **which Manim codegen prompt**
Stage 2 uses.

---

## 4. Stage 2 — Manim Code Generation & Rendering (`app/stages/stage2_manim.py`)

The most complex stage. Duties: generate Manim code via LLM, extract
timestamps, validate scene-count parity, render each scene **individually**,
self-heal broken code via LLM, and save one MP4 per surviving scene.

### 4.1 Select the subject prompt

The category from Stage 1 picks the prompt file:

```python
prompt_path = PROMPTS_DIR / f"{scenes_category.lower()}_manim.txt"
prompt = prompt_path.read_text().replace("{scenes_json}", scenes_json)
```

Files: `maths_manim.txt`, `physics_manim.txt`, `chemistry_manim.txt`,
`biology_manim.txt`, `computer_science_manim.txt`.

### 4.2 What the Manim codegen prompt enforces (using `maths_manim.txt` as template)

**Structural rules:**
- **One `Scene` class per `scene_id`**, named exactly `Scene{scene_id}_{ConceptName}(Scene)`.
  This naming is load-bearing: Stage 2 discovers classes with the regex
  `class\s+(Scene\d+_[A-Za-z0-9_]+)\s*\(Scene\)` and renders them one by one.
- Only a constrained vocabulary: `Axes, NumberPlane, plot, Line, Dot, Arrow,
  MathTex, Tex, Text, Create, Write, Transform, FadeIn, FadeOut`.
- **No external images/videos/imports.**
- Each scene must be stretched to target duration via `self.wait()`.
- Output **ONLY JSON**, no markdown fences:

```json
{ "manim_code": "<full python source as string>",
  "timestamps": [ { "scene_id": N, "start": ..., "end": ... } ] }
```

**LaTeX rules (the #1 source of Manim crashes, so they are spelled out):**
- ALWAYS use raw strings: `r"\frac{{a}}{{b}}"`.
- Single braces inside raw strings — `{{}}`, never quadruple `{{{{}}}}`.
- Never double backslashes (`"\\\\frac"` is wrong).
- Matching delimiters (`\left(...\right)`) must stay inside ONE argument.
- `MathTex` = pure math; `Tex` for English text containing inline `$math$`;
  `Text` for plain English.
- **Indexing rule:** a single-argument `MathTex` has no indexed subparts
  (`eq[1]` doesn't exist); split into multiple arguments *only if* you intend
  to animate parts separately.

Correct examples the prompt drills in:
```python
MathTex(r"ax^2 + bx + c = 0")
MathTex(r"\frac{{a}}{{b}}")
MathTex(r"x", "=", r"\frac{{-b \pm \sqrt{{b^2 - 4ac}}}}{{2a}}")
Tex(r"When $\Delta > 0$, there are 2 roots")
Text("Two real roots")
```

Internal note: the prompt file contains literal `{{scene_id}}` double braces
because the file is read with `.replace("{scenes_json}", ...)` rather than
`.format()`, so the placeholders are pre-escaped.

### 4.2.1 Code-visualization prompt (`computer_science_manim.txt`) — data-structure diagram recipes

Since this pipeline is used to generate **code & data-structure visualization**
videos, the CS prompt (selected when Stage 1 returns
`"category": "computer_science"`) carries — on top of the shared structural
and LaTeX rules above — a **diagram recipe section** that pins down exactly
what kind of visual must be drawn for each data structure. The LLM must not
invent its own layout; it must follow these canonical visualizations so the
output is consistent and algorithm-correct.

The following block is the code-visualization section of the CS prompt. All
rules from §4.2 (one class per `scene_id`, `Scene{scene_id}_{ConceptName}`
naming, JSON-only output, `self.wait()` durations, LaTeX discipline) still
apply verbatim — this section **replaces/extends the visualization vocabulary
and adds structure-specific layout rules**:

```text
CODE VISUALIZATION VOCABULARY (in addition to the base set):
You MAY additionally use: Rectangle, RoundedRectangle, Square, VGroup, VDict,
Brace, BraceBetweenPoints, SurroundingRectangle, Underline, Cross, CurvedArrow,
CurvedDoubleArrow, Indicate, Circumscribe, Flash, ApplyWave, LaggedStart,
ValueTracker, always_redraw (only these — no image/latex-file rendering).

UNIVERSAL MEMORY-MODEL RULES (apply to every scene):
- Code/algorithm explanation: LEFT lane = visualization (data structure);
  RIGHT lane = pseudocode lines as a right-aligned VGroup of Text()s, with a
  moveable SurroundingRectangle (highlight) that jumps to the executing line.
- Variable values are Text()/MathTex() placed INSIDE boxes — never floating.
- Every pointer is an Arrow from the pointer's anchor to the referenced
  object; when the pointer moves (assignment/swap), FadeOut the old Arrow and
  Create the new one (Arrows do not animate pivot changes well).
- Every index used (i, j, mid, top, front, rear) is rendered as a labelled
  Arrow or Triangle under/above the exact cell it points to.
- Swap animation: highlight both cells (SurroundingRectangle), show the two
  values Transform into each other's cells with an arc (curved Transform),
  then keep both values in their final cells.

DIAGRAM RECIPES (MANDATORY SPECIFIC STYLES):

1. ARRAY / LIST / STRING:
   One horizontal row of equal 1x1 squares inside a VGroup; value inside each
   cell, index label (0..n-1) ABOVE each cell as Text().
   - Traversal: one index-Arrow moves cell-to-cell as each cell is Indicate()d.
   - Insert: target cells shift(RIGHT*cellW) with the value FadeIn()ing into
     the gap; if the array overflows, show two arrays (old row FadeOut →
     new 2n-sized row FadeIn) — the classic dynamic-array resize.
   - Out-of-bounds access: Flash() red on the cell space beyond the array +
     a red Cross() over the index-Arrow.

2. STACK (LIFO):
   a vertical column of stacked rectangles (height 0.6 each), "Bottom"
   label under the lowest cell, "Top" pointer = a fixed Arrow that slides
   UP/DOWN to always point at the top cell.
   - Push: new Rectangle slides in from OFF-SCREEN ABOVE down into place,
     Top arrow moves up.
   - Pop: top Rectangle slides up out and FadeOut, value Text of the popped
     item moves to the side ("returned value"), Top arrow moves down.
   - Peek: Circumscribe around the top cell (no value removal).
   - Stack overflow: attempt push at fixed capacity → Flash red + "Overflow"
     Text; underflow on pop from empty stack likewise.

3. QUEUE (FIFO):
   horizontal row of cells with "FRONT" Arrow on the left-most occupied cell
   and "REAR" Arrow on the right-most.
   - Enqueue: value slides in from OFF-SCREEN RIGHT behind REAR, REAR moves.
   - Dequeue: FRONT cell FadeOut, remaining cells shift LEFT one slot, FRONT
     and REAR arrows update.
   - Circular queue: cells arranged in a Circle with two pointer Arrows;
     wrap-around is shown by the pointer rotating past the last cell to the
     first, plus the "(i+j) % n" MathTex displayed while it happens.

4. LINKED LIST:
   separate nodes spaced horizontally; each node = paired rectangle
   [data | next] drawn as two 0.8x0.6/0.5x0.6 rectangles side-by-side
   (Divider via a small Line between them), "head" Arrow labelled
   "head"/"curr"/"prev"/"tmp" Points at its node.
   - Traversal: curr Arrow hops node to node, old node drops opacity 0.4.
   - Insert at position k: Indicate target, FadeOut the incoming Arrow,
     insert new node in between, draw its two new Arrows, re-wire.
   - Delete: SurroundingRectangle on node, its incoming and outgoing Arrows
     FadeOut, a bridging Arrow connects prev → next directly, node fades.
   - Doubly linked list: pairs of Arrows between nodes labelled next (above)
     and prev (below)
   - Detect cycle: one CurvedArrow from a later node back to an earlier node
     plus "slow/fast pointers" — two Arrows moving at 1x and 2x speed.

5. HEAP (MIN/MAX):
   BOTH representations, always together: the complete binary tree on top
   (Circle nodes connected by Lines) and its array form as a row of cells
   below (parent at index i ↔ children 2i, 2i+1 written beside the tree as
   MathTex).
   - Insert: value Text placed at the new leaf, then per sift-up step the
     parent–child pair highlights + the two values Transform-swap in BOTH
     tree and array row simultaneously (keep the two views synchronized).
   - Extract root: root value Text moves aside ("min/max popped"), last leaf
     moves to root, then per sift-down step highlight the smaller/larger
     child with SurroundingRectangle before each swap.

6. BINARY SEARCH TREE:
   Circles with integer labels inside; left/right child edges are Lines;
   the "left < node < right" invariant shown once as MathTex at scene start.
   - Insert: a hollow/dashed Circle (new node) drops from the top, stopping
     at the first null child position; traversed path edges highlight green
     step by step.
   - Search: path nodes highlight green when in-range ("go left/right") and
     red when rejected.
   - Delete: draw the 3 cases explicitly (leaf → fade node; one child →
     transform child edge to bridge; two children → Inorder successor node
     then its value Transforms into the deleted node's
     label).

7. GRAPH (BFS / DFS / DIJKSTRA):
   Circle vertices with labels inside; edges = Lines (undirected) or Arrows
   (directed), weight Texts near edge midpoints for weighted graphs.
   - Traversal state colors: unvisited = default, frontier (in queue/stack) =
     YELLOW fill, visited = GREEN fill, current = Circumscribe.
   - BFS: show the queue (per recipe 3) beside the graph; enqueuing draws the
     vertex in, processing pops it; discovery edges highlight.
   - DFS: show the recursion/call stack (recipe 2) beside the graph.
   - Dijkstra/A*: in-progress distance labels (Text) under each vertex update
     via Transform when a shorter path relaxes; the shortest-path edges end
     highlighted thick/red.

8. HASH TABLE / HASHMAP:
   an indexed bucket row on top (cells labelled 0..m-1) and chains hanging
   below (per recipe 4).
   - Show the hash function box (MathTex e.g. h(k) = k % m) with an Arrow
     from the key Text to the bucket cell it maps to.
   - Collision: second entry chains off the same bucket (new node drawn
     below the old one, connected by an Arrow labelled "next").
   - Load factor/resize: show "load factor = n / m" as MathTex; on rehash,
     FadeOut the whole old structure → FadeIn the doubled bucket row with
     entries redistributed.

9. MEMORY MODEL — STACK vs HEAP:
   LEFT panel labelled "Stack", RIGHT panel labelled "Heap" (two
   SurroundingRectangle frames).
   - Local variables = small rectangles (name above, value inside) stacked
     in the stack panel; objects (arrays/lists, those created with new/malloc)
     = rectangles in the heap panel.
   - A reference shows as an Arrow from the variable cell in the stack CROSSING
     OVER to the object in the heap.
   - Function call: new frame (SurroundingRectangle batched around its vars)
     appears lower in stack; return: frame fades and any Arrows from it fade.
   - Dangling pointer/null: the Arrow fades to a red Cross() at "null".

10. SORTING (bubble/selection/insertion/merge/quick):
   array row per recipe 1 (plus optional bar chart: per-value Rectangle
   heights proportional to value on Axes-free VGroup).
   - Compare step: two SurroundingRectangles on the compared pair.
   - Swap: per universal rule (arc Transform between the two cells).
   - Partition/pivot (quick): pivot cell set_fill(RED), smaller/larger value
     movements shown as one-directional slide-arrows; region boundaries drawn with vertical dashed Lines that move.
   - Merge sort: two sorted halves as rows, merged row below; per-merge step
     picks one side's value and slides it down into the merge-sequence.
   - Sorted-suffix marker: green SurroundingRectangle that grows left-to-right
     (or a green underline) over sorted cells.

11. DYNAMIC PROGRAMMING / DP TABLES:
   dp Grid = rows of Rectangle cells (m x n VGroup) with row/col header
   Texts; recurrence written once on top as MathTex.
   - Cell fill order: cells get their values in dependency order, each cell
     briefly Indicate()d as it's computed, with dependency Arrows from the
     cells read.
   - Base cases shaded (fill_opacity 0.2).
   - Final answer cell: Circumscribe at scene end.

12. RECURSION:
   two synchronized views, always paired: call stack (recipe 2, one frame per
   call showing arguments n and "return n*f(n-1)" as Text()) and the recursion
   tree (circles labelled by call with arguments).
   - Call: new frame slides down onto stack AND new circle is created lower in
     tree connected via Line.
   - Return: frame pops and its value Text travels (Transform) up the tree
     edge into the caller's circle; base case: leaf Circumscribe green.

13. TWO POINTERS / SLIDING WINDOW:
   array row per recipe 1 with left and right index-Arrows.
   - Two pointers move via arrow slides + the cells they scan highlighted.
   - Window: a single SurroundingRectangle spanning the active cells of the
     subarray; it shrinks (left++) or grows (right++) as code runs;
     window sum/max Text updates via Transform.

14. BIG-O / COMPLEXITY:
   Axes with curves plotted (n, n log n, n^2, ...) — always include axis
   labels and legend Text; runtime "operation counter" Text top-right that
   increments (Transform between counter values) at every fundamental
   operation shown in the main visualization.

CONSISTENCY REQUIREMENTS:
- Same structure type → same visual style across ALL scenes of the video.
- Color semantics are fixed: YELLOW = current/active, GREEN = success/visited
  or sorted, RED = error/comparison fail or pivot, BLUE = default, GREY =
  done/ignored.
- All cells for one structure are inside ONE VGroup so scale/align stays
  consistent; label every structure once at its first appearance (Text title
  at TOP edge).
- No scene may show a structure without at least one mutating/changing
  operation (insert, delete, traverse, compare, update...) — pure static
  display is prohibited.
```

Consistency rules the pipeline relies on across all categories (matters
especially for CS because a video typically shows the same structure in many
scenes):

- One structure → one canonical diagram; the LLM is NOT free to redesign it
  per scene.
- State colors (yellow/green/red/blue/grey) mean the same thing everywhere,
  so narration in Stage 3 can use the same vocabulary.
- Every scene must animate at least one operation, so the narration always
  has an event to narrate (per Stage 3's rule: don't describe visuals, narrate
  behavior).

### 4.3 Code + timestamp handling

```python
output = call_llm(prompt)
data = extract_json(output)          # robust JSON extraction
manim_code = data["manim_code"]

ANIMATION_PY.write_text(manim_code)                      # outputs/animation.py

timestamps = extract_timestamps(manim_code)              # regex-based, independent of LLM claim
TIMESTAMPS_JSON.write_text(json.dumps(timestamps, indent=2))  # outputs/timestamps.json
```

Note the design choice: the LLM's own `timestamps` array is **discarded**;
timestamps are recomputed locally by a deterministic regex parser
(`app/utils/timestamps_extractor.py`) so they can't be hallucinated:

```python
PLAY_REGEX = re.compile(r"self\.play\(.*?run_time\s*=\s*([0-9.]+)\)", re.DOTALL)
WAIT_REGEX = re.compile(r"self\.wait\(\s*([0-9.]+)\s*\)")

# Walk the code line by line; for each self.play(run_time=...) or self.wait(...):
#   start = running clock, end = start + duration
#   {"scene": i, "start": ..., "end": ..., "duration": ...}
```

Example of `outputs/timestamps.json`:

```json
[
  { "scene": 1, "start": 0.0, "end": 2.0, "duration": 2.0 },
  { "scene": 2, "start": 2.0, "end": 5.0, "duration": 3.0 },
  ...
]
```

### 4.4 Scene-count validation

```python
scene_classes = extract_scene_classes(manim_code)   # regex on "class SceneN_Name(Scene)"
if len(scene_classes) != len(scenes["scenes"]):
    raise RuntimeError("Scene count mismatch between JSON and Manim code")
```

Every planned scene must map to exactly one Manim class before rendering starts.

### 4.5 Per-scene rendering loop (with LLM self-repair)

For each discovered class, in order (`scene_1`, `scene_2`, ...):

```python
for idx, scene_class in enumerate(scene_classes, start=1):
    scene_id = f"scene_{idx}"
    retries = 0
    while retries <= MAX_RETRIES:          # MAX_RETRIES = 2
        try:
            clean_manim_temp()             # wipe media/videos, media/Tex, media/text, media/images
            render_scene(scene_class)      # manim -ql animation.py <SceneClass> (cwd=PROJECT_ROOT)
            extract_scene_video(...)       # media/**/SceneClass.mp4 → outputs/scenes/02_scene_2.mp4
            final_scene_ids.append(scene_id)
            break
        except (CalledProcessError, RuntimeError) as e:
            retries += 1
            if retries <= MAX_RETRIES:
                manim_code = fix_manim_code_with_llm(manim_code, e.stderr)
                ANIMATION_PY.write_text(manim_code)   # entire file is overwritten with the fixed code
            else:
                print(f"🗑 Skipping {scene_class}")   # scene allowed to fail → dropped from output
                break
```

- `manim -ql` renders at **480p 15fps** ("low quality") — fast per-scene
  feedback; good enough for concatenated output.
- Renders one class per invocation, cleaning manim's scratch (`media/`)
  between attempts so stale artifacts can't be mistaken for output.
- `extract_scene_video` uses `MEDIA_DIR.rglob(f"{scene_class}.mp4")` to locate
  the fresh render, then moves it to `outputs/scenes/{idx:02d}_{scene_id}.mp4`.

**The LLM fixer prompt** is deliberately narrow:

```
You are an expert Manim debugger.
Rules:
- Fix ONLY runtime or syntax errors
- Do NOT rename Scene classes     ← preserves the naming contract
- Do NOT add or remove scenes     ← preserves scene-count parity
- Return ONLY valid Python code (no markdown/explanations)

Broken Manim code: {manim_code}
Error: {stderr}
```

### 4.6 The surviving-scene contract (most important invariant)

A scene that **fails twice** is skipped — its class never gets an MP4, and,
critically, it is **removed from the pipeline everywhere downstream**:

```python
return {
    "manim_code": manim_code,                 # last (possibly fixed) code
    "timestamps": extract_timestamps(manim_code),
    "scene_ids": final_scene_ids,             # ONLY scenes that actually rendered
}
```

Every later stage iterates **`scene_ids`** (not the original plan):
Stage 4 synthesizes audio only for `scene_ids`, Stage 5 muxes/stitches only
`scene_ids`. This guarantees the narration track can never reference a scene
that doesn't exist on screen.

### Summary of the fix-loop's file behavior

- On each retry, `ANIMATION_PY.write_text(manim_code)` performs a **whole-file rewrite** of the LLM-fixed code.
- `timestamps.json` is **not** rewritten inside the retry loop; the timestamps returned by `generate_manim()` are re-extracted from the final code.

---

## 5. Stage 3 — Narration Script (`app/stages/stage3_script.py`)

**Inputs:** `scenes` (Stage 1) + `timestamps` (Stage 2) + `persona` + `level`
**Prompt:** `app/prompts/script_writer.txt`
**Output:** `outputs/script.json`

```python
prompt = (PROMPTS_DIR / "script_writer.txt").read_text()
prompt = prompt.format(
    scenes=json.dumps(scenes),
    timestamps=json.dumps(timestamps),
    persona=persona,   # e.g. "teacher"
    level=level,       # e.g. "school"
)
output = call_llm(prompt)
script = json.loads(output)
Path("outputs/script.json").write_text(json.dumps(script, indent=2))
```

### Script-writer prompt rules

- **Spoken narration only**, one narration **per scene**.
- Must **match the scene's duration** (from timestamps: a 5 s scene gets ~5 s
  of speech).
- **Never describe the visuals** in wording that sounds like stage directions
  ("now you see a circle...") — it narrates the *concepts*.
- Persona (e.g., `teacher`) and level (e.g., `school`) are injected from
  the request.

### Output schema (a plain JSON array)

```json
[
  { "scene_id": 1, "script": "Welcome to Newton's Laws of Motion. These three fundamental laws describe how objects move and interact..." },
  { "scene_id": 2, "script": "Newton's First Law states that an object at rest will stay at rest unless acted upon by an external force..." }
]
```

Note: `scene_id` here are the planner's numbering; Stage 4 builds a lookup
map and tolerates entries written as `scene_2` or plain `2`.

---

## 6. Stage 4 — TTS Audio (`app/stages/stage4_tts.py`)

**Input:** `script`, `video_id`, `scene_ids` (survivors only)
**Provider:** Azure Cognitive Services Speech SDK
**Output:** `outputs/audio/<video_id>/scene_N.wav`

### Flow

```python
output_dir = OUTPUTS_DIR / "audio" / video_id   # per-run isolation via uuid4().hex

speech_key = os.getenv("AZURE_SPEECH_KEY")
region     = os.getenv("AZURE_SPEECH_REGION")   # RuntimeError if unset

speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)
speech_config.speech_synthesis_voice_name = "en-IN-NeerjaNeural"   # fixed voice

script_map = {   # tolerant key normalization
    (f"scene_{s['scene_id']}" if not str(s["scene_id"]).startswith("scene_") else s["scene_id"]): s["script"]
    for s in script
}

for scene_id in scene_ids:                        # ← ONLY surviving scenes
    if scene_id not in script_map:
        raise RuntimeError(f"No script found for {scene_id}")

    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(audio_path))
    synthesizer  = speechsdk.SpeechSynthesizer(speech_config, audio_config)
    result = synthesizer.speak_text_async(text).get()

    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        raise RuntimeError(f"TTS failed for {scene_id}")
```

Key points:

- **Voice is hardcoded:** `en-IN-NeerjaNeural` (Indian English, female).
- A **new `SpeechSynthesizer` is created per scene**, each writing to its own
  WAV — flushes cleanly and isolates per-scene failure handling.
- `result.reason` is checked; any non-`SynthesizingAudioCompleted` is an error
  (the `.get()` call waits synchronously).
- Output WAVs are the bridge between Stage 3 text and Stage 5 muxing keyed by
  `scene_id` + `video_id`.

---

## 7. Stage 5 — Audio/Video Merge & Final Stitch (`app/stages/stage5_stitch.py`)

Three independent operations, all via FFmpeg/FFprobe. Paths mirror Stage 2's
constants exactly (`PROJECT_ROOT`, `MEDIA_DIR`, `OUTPUTS_DIR`).

### 7.1 Mux per-scene (`mux_audio`)

For each surviving `scene_id` (index-order 1..N):

- Video:  `outputs/scenes/{idx:02d}_{scene_id}.mp4`   (from Stage 2)
- Audio:  `outputs/audio/<video_id>/{scene_id}.wav`   (from Stage 4)
- Out:    `outputs/videos/<video_id>/scenes_with_audio/{idx:02d}_{scene_id}.mp4`

Both go through `ffprobe -show_entries format=duration` for exact durations,
then an **equalize-by-extension** policy:

| Case (A = audio dur, V = video dur) | Video filter                          | Audio filter            | Effect                          |
|-------------------------------------|----------------------------------------|-------------------------|---------------------------------|
| `A > V` (narration longer)          | `tpad=stop_mode=clone:stop_duration=A-V` | `anull`               | **Freeze last frame** until narration ends |
| `V > A` (visual longer)             | `null`                                 | `apad=pad_dur=V-A`      | **Silence padding** until visuals end |
| `V == A`                            | `null`                                 | `anull`                 | Straight join                   |

Then:

```bash
ffmpeg -y -i scene.mp4 -i scene.wav \
  -filter_complex "[0:v]<vf>[v];[1:a]<af>[a]" \
  -map "[v]" -map "[a]" \
  -c:v libx264 -c:a aac \
  scenes_with_audio/NN_scene_N.mp4
```

Re-encoding with libx264/AAC here is what later enables the concat demuxer's
`-c copy` to work: after this stage every scene shares **identical codecs,
resolution, fps and sample rate** (all renders are `-ql` 480p15).

Missing video or audio for any `scene_id` raises immediately — because the
loop iterates only surviving scene_ids, both files must exist by contract.

### 7.2 Stitch (`stitch`)

Lossless concat demuxer over the muxed scenes:

```bash
# concat_list.txt (built dynamically, absolute paths, then deleted)
file '/abs/path/scenes_with_audio/01_scene_1.mp4'
file '/abs/path/scenes_with_audio/02_scene_2.mp4'
...

ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy final.mp4
```

`-c copy` = stream copy, zero re-encode; correctness depends entirely on the
homogenized encoding done in `mux_audio`. Output:
`outputs/videos/<video_id>/final.mp4`.

### 7.3 Serving (`app/main.py`)

```python
@app.get("/video/{video_id}")
def get_video(video_id): ...
    path = PROJECT_ROOT / "outputs" / "videos" / video_id / "final.mp4"
    return FileResponse(path, media_type="video/mp4")
```

### 7.4 Final response of `POST /explain`

```json
{
  "status": "complete",
  "video_id": "08ae0de52f7a40789cf068b1572a0afe",
  "video_path": ".../outputs/videos/08ae0de52f7a40789cf068b1572a0afe/final.mp4",
  "face_enabled": false
}
```

---

## 8. Run It

```bash
# 1. Environment
python -m venv venv
source venv/bin/activate                 # (Windows: venv\Scripts\activate)
pip install -r requirements.txt          # manim, fastapi, openai, azure-cognitiveservices-speech, python-dotenv

# 2. System deps
#   - ffmpeg + ffprobe on PATH (required by Stage 5)
#   - manim's native deps: LaTeX (MiKTeX/TeX Live) for MathTex/Tex, Pango, ffmpeg (bundled via imageio-ffmpeg usually)
brew install ffmpeg basictex             # macOS example

# 3. Secrets in app/.env — the pipeline is built on exactly these keys:
#   Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_API_KEY (or the alternate
#     AZURE_OPENAI_API_KEY), AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini,
#     AZURE_OPENAI_API_VERSION=2024-06-01 (optional LLM_PROVIDER=azure)
#   Azure Speech: AZURE_SPEECH_KEY, AZURE_SPEECH_REGION=uaenorth

# 4. Start the API
uvicorn main:app --reload                # run from app/ (or wire sys.path)

# 5. Generate a video
curl -X POST "http://localhost:8000/explain?topic=Newton%27s%20Laws%20of%20Motion&level=school&persona=teacher"

# 6. Fetch result
curl -o out.mp4 http://localhost:8000/video/<video_id>
```

Artifacts you should see after a successful run:

```
outputs/
├── scenes.json                                    # Stage 1
├── animation.py                                   # Stage 2 (Manim source)
├── timestamps.json                                # Stage 2 (regex-extracted)
├── scenes/01_scene_1.mp4 ... NN_scene_N.mp4       # Stage 2 (silent renders)
├── script.json                                    # Stage 3
├── audio/<video_id>/scene_1.wav ... scene_N.wav   # Stage 4
└── videos/<video_id>/
    ├── scenes_with_audio/01_scene_1.mp4 ...       # Stage 5 (muxed)
    ├── final.mp4                                  # Stage 5 (stitched)
    └── concat_list.txt                            # deleted after stitch
```

---

## 9. Gotchas, Invariants & Hard-Earned Lessons (from the code)

1. **`cwd=PROJECT_ROOT` for manim is non-negotiable.** Running manim from
   anywhere else scatters renders into the wrong `media/` tree and
   `extract_scene_video()` finds nothing.
2. **`scene_ids` is the single source of truth downstream.** Plan-vs-render
   mismatch is normal and expected; skipping a scene is handled at Stage 2
   and propagated via `scene_ids` (used verbatim in Stages 4 and 5).
3. **Never trust LLM-computed timestamps.** They are re-derived by
   `timestamps_extractor.py` from the actual source (self.play run_time /
   self.wait durations), accumulated in order. Works because every animated
   step in the emitted code carries an explicit `run_time` or comes after a
   `wait`.
4. **Never let the fixer rename scene classes.** The regex discovery
   (`SCENE_CLASS_RE`) and downstream naming (`{idx:02d}_{scene_id}.mp4`) depend
   on the `SceneN_*` naming contract.
5. **Mux must happen per-scene with normalizing filters.** Audio may be
   longer or shorter than the visual; freeze-frame padding (`tpad`) and
   silence padding (`apad`) resolve both without cutting content. Without
   per-scene re-encoding, the concat `-c copy` step would produce broken,
   duration-skipped output.
6. **Clean manim scratch dirs before each attempt**
   (`media/videos`, `media/Tex`, `media/text`, `media/images`) so stale
   renders/tex artifacts from a previous run can't be picked up by `rglob`.
7. **IDs are uuid4().hex per run** (e.g. `outputs/audio/`, `outputs/videos/…`
   subfolders), so parallel runs don't collide; silent renders
   (`outputs/scenes/`) are shared per-request rather than per-ID.
8. **LLM fixes overwrite the WHOLE animation.py file** (`fix…with_llm(manim_code, stderr)`)
   — a fix for scene 5 potentially also "fixes" code not yet rendered, so
   subsequent scenes render against the updated file.
9. Stage 2 validation happens before rendering: scene-count parity between
   scenes.json and Manim class names (regex `class\s+(Scene\d+_[A-Za-z0-9_]+)\s*\(Scene\)`).
10. **A slightly stale `Scene` naming or missing `Scene(...)` imports**
    renders as "no video found" — the exception path is a `RuntimeError`
    caught by the same retry loop as actual manim failures (so it's fixable by
    the same LLM pass).

---

## 10. End-to-End Data Contracts (cheat sheet)

| Stage | Consumes | Produces | Format |
|-------|----------|----------|--------|
| 1. Scenes | topic, level | `outputs/scenes.json` | `{"category": str, "scenes": [{"scene_id",  "concept", "visual"}]}` |
| 2. Manim | scenes.json | `animation.py`, `timestamps.json`, `outputs/scenes/NN_scene_N.mp4`, `{manim_code, timestamps, scene_ids}` | Scenes classes `SceneN_Name(Scene)` |
| 3. Script | scenes + timestamps + persona/level | `outputs/script.json` | `[{"scene_id": N, "script": str}]` |
| 4. TTS | script + scene_ids + video_id | `outputs/audio/<video_id>/scene_N.wav` | 16-bit WAV per scene |
| 5. Mux+Stitch | scenes MP4s + WAVs + scene_ids | `outputs/videos/<video_id>/final.mp4` | H.264 + AAC MP4 |
| Serve | video_id | `GET /video/{video_id}` → `final.mp4` | HTTP file response |

END OF GUIDE.
