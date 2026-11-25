# Moteur d'évaluation et de décision — MVP

Mise en œuvre de `FATIN_Evaluation_Decision_Making_Engine_MVP.docx`.
Les réponses existantes restent compatibles (`action`, `chunk`, `session`, `is_correct`,
`feedback`, `redirect`, `mastered_now`, `next_skill`) ; les champs ci-dessous sont nouveaux.

## Cycle

```
Groupe d'exercices -> Évaluation -> Décision -> Intervention -> Nouveau groupe -> Réévaluation
```

| Situation | Décision (`decision`) |
|---|---|
| Moins de `min_attempts` réponses dans le groupe | `continue` : le groupe est complété |
| Low / Medium + erreur dominante concept / procedure / careless | `intervention` (séquence fixe, section 6) |
| High, streak insuffisant | `verify_streak` : un exercice de plus, puis réévaluation |
| High + streak atteint | `mastered` |
| Exercices épuisés, non maîtrisé, prérequis lié à l'erreur | `prerequisite_return` |
| Exercices épuisés, pas de prérequis adapté (ou erreur careless) | `teacher_review` + intervention + nouveau cycle |

- Mastery = justes / total **du dernier groupe** (`progress.mastery`).
- Égalité d'erreurs : Careless > Procedure > Concept.
- Un exercice n'est jamais reproposé pendant un cycle d'apprentissage de la skill.
- Aucune décision au milieu d'un groupe ni au milieu d'une intervention.

## `GET /api/students/{id}/next-action/?skill=`

```json
{
  "action": "show_chunk",
  "mode": "learn | group | intervention | verify",
  "chunk": {...},
  "instruction": "أكمل الخطوات الناقصة في الحل.",
  "group": {"id": 12, "answered": 2, "total": 5},
  "intervention": {"id": 4, "error_type": "procedure", "reason": "...", "step": "guided_exercise",
                    "step_label": "تمرين بإكمال خطوات ناقصة", "step_index": 3, "steps_total": 4},
  "context": {...}, "session": {..., "group": {...}, "intervention": {...}}
}
```

Un contenu d'intervention (`rule`, `example`, `hint`) est considéré vu dès qu'il est servi :
le bouton « التالي » rappelle `next-action`. Un exercice d'intervention avance après `/answer/`.
`action: "redirect_to_prerequisite"` est inchangé (`new_skill.reason` ajouté).

## `POST /api/students/{id}/answer/`

Nouveaux champs :

- `error_source` : `option` (Error Mapping du choix), `chunk` (catégorie par défaut de l'exercice)
  ou `heuristic` (contenu pas encore mappé).
- `answer_context` : `group`, `intervention` ou `free`.
- `feedback.continue` / `feedback.short_message` : erreur au milieu d'un groupe, l'élève continue.
- `decision` et `evaluation` (fin de groupe uniquement) :

```json
{
  "group_id": 12, "total_attempts": 5, "correct_answers": 3, "mastery": 0.6,
  "mastery_level": "medium", "judged": true,
  "error_frequency": {"concept": 0, "procedure": 2, "careless": 0},
  "dominant_error_type": "procedure", "correct_streak": 2, "decision": "intervention",
  "mistakes": [{"chunk_id": 55, "content": "...", "answer": "...", "error_type": "procedure", "feedback": "..."}],
  "intervention": {"id": 4, "error_type": "procedure", "reason": "...", "steps": ["...", "..."]},
  "teacher_review": false
}
```

## Nouveaux endpoints

| Endpoint | Rôle |
|---|---|
| `GET /api/students/{id}/learning-trace/?skill=` | Learning Trace : évaluations (mastery avant/après, amélioration) et retours aux prérequis |
| `GET / PATCH /api/assessment/engine-settings/` | Seuils (lecture : enseignant ; modification : admin) |
| `GET /api/assessment/review-cases/?status=` | Cas à revoir par l'enseignant (par défaut `teacher_review`) |
| `PATCH /api/assessment/review-cases/{id}/` | `{"review_note": "..."}` -> statut `reviewed` |

## Contenu (Error Mapping)

- `chunk.options[]` : `{"id", "text", "is_correct", "error_category": "concept|procedure|careless", "feedback"}`.
- `chunk.default_error_category` : catégorie d'une mauvaise réponse libre (non QCM).
- `chunk.is_guided` : exercice « compléter les étapes manquantes » (intervention procedure).
- `prerequisite.related_error_types` : `["concept"]`, `["procedure"]` ou vide (les deux).
- Une 2ᵉ règle (`rule`) sert de « nouvelle explication » dans l'intervention concept ;
  un `hint` sert d'« explication détaillée des étapes » dans l'intervention procedure.
