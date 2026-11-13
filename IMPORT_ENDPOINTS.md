# Content Import — Endpoints & Fields


## Endpoints used (in call order)

### 1. Create unit
`POST api/curriculum/units/`

```json
{
  "subject": 12,
  "code": "U11",
  "title": "Unit title",
  "description": "string | null",
  "main_goal_description": "string | null",
  "central_question": "string | null",
  "main_skill_domain": "string",
  "term": "string (max 50)",
  "competency_ref": "string (max 100)",
  "order_index": 5
}
```

### 2. Create lesson
`POST api/curriculum/lessons/`

```json
{
  "unit": 23,
  "code": "U11-L01",
  "title": "Lesson title",
  "description": "string",
  "order_index": 1,
  "programme_ref": "string (max 100)",
  "week": 3,
  "programme_weeks": [3, 4],
  "book_exercises": ["any JSON value", "..."]
}
```
`week` is a positive integer or `null`. `programme_weeks` and `book_exercises`
are stored as-is (any JSON list), so the source structure is kept unchanged.

### 3. Create goal
`POST api/curriculum/goals/`

```json
{
  "lesson": 87,
  "goal_type": "conceptual | operational",
  "title": "Goal title",
  "description": "string",
  "order_index": 1
}
```
`order_index` is always `1` for `conceptual`, `2` for `operational`.

### 4. Create skill
`POST api/skills/skills/`

```json
{
  "goal": 142,
  "skill_type": "conceptual | operational",
  "code": "SK-U11-L01-C01",
  "name": "Skill name",
  "description": "string",
  "difficulty": 2,
  "mastery_threshold": 0.8,
  "required_consecutive_correct": 3,
  "order_index": 1
}
```

### 5. Create content chunk
`POST api/skills/chunks/` (JSON)

```json
{
  "skill": 310,
  "code": "SK-U11-L01-C01-CH01",
  "chunk_type": "rule | example | practice | error | hint | real_life",
  "title": "string | null",
  "content": "string",
  "difficulty": 1,
  "points": 1,
  "correct_answer": "string | null (practice only)",
  "options": [
    {
      "id": "a",
      "text": "string",
      "is_correct": true,
      "error_category": "string | null",
      "feedback": "string | null"
    }
  ],
  "time_limit": 60,
  "order_index": 1,
  "needs_image": true,
  "image_note": "string | null"
}
```
Each item of `options` is either a plain string or an object with at least
`text`. Objects are stored as sent: `id`, `is_correct` (boolean),
`error_category` and `feedback` are kept, as well as any extra key.

### 6. Upload chunk image
`PATCH api/skills/chunks/{id}/` (`multipart/form-data`)

| Form field | Value |
|---|---|
| `image` | image file (e.g. `images/M1AF-u1-l1-s1-c1.jpg`) |

Send the chunk as JSON first (step 5), then upload its image with this call.
The response returns the image URL in `image` (stored under `media/chunks/`).

### 7. Link prerequisites (second pass)
`POST api/skills/prerequisites/`

```json
{ "skill": 310, "prerequisite": 305 }
```
Call this **after all skills are created**, so that every prerequisite code
from the source file can be resolved to a skill id. The API rejects
self-links, inverse duplicates and cycles.

## What the API returns

- **Teachers / admins** get every field back, including `correct_answer` and
  the full `options` objects.
- **Students** never receive `correct_answer`, and `options` is reduced to
  the list of option texts (`["text 1", "text 2"]`), so `is_correct`,
  `error_category` and `feedback` never reach the browser.

## Field coverage by level

Source reference: `M1AF/M1AF.json` (digitized math textbook, grade 1).

### Unit
| Source field | Supported? |
|---|---|
| `description` | ✅ |
| `main_skill_domain` | ✅ |
| `term` | ✅ new |
| `competency_ref` | ✅ new |
| `thumbnail` (image) | ✅ (multipart, field `thumbnail`) — source file has no unit image |

### Lesson
| Source field | Supported? |
|---|---|
| `programme_ref` | ✅ new |
| `week` | ✅ new (integer) |
| `programme_weeks` | ✅ new (JSON list) |
| `book_exercises` | ✅ new (JSON list) |

### Goal
No gaps — all meaningful source fields are supported.

### Skill
| Source field | Supported? |
|---|---|
| `prerequisites` | ✅ via `POST api/skills/prerequisites/` (step 7) — the importer must call it |

### Content chunk
| Source field | Supported? |
|---|---|
| `image` | ✅ new (step 6) |
| `needs_image` | ✅ new (boolean, default `false`) |
| `image_note` | ✅ new |
| `options[]` rich structure (`{id, text, is_correct, error_category, feedback}`) | ✅ kept as-is — the importer must stop flattening it to `string[]` |

## Remaining work on the importer side

The API now accepts every field above; the importer still has to:
- send the new unit / lesson / chunk fields;
- send `options` as objects instead of plain strings;
- upload the 663 chunk images (step 6);
- create prerequisite links in a second pass (step 7).
