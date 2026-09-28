# Write the docs of the module `${module}`

You document one module of an existing codebase for its module registry. Read the module's code
first, then write the files below into the staging directory `${staging_dir}/` — nothing else,
nowhere else.

## The module

- Name: `${module}`
- Code: ${paths} ${files_note}
- Neighbours (modules its code imports from):
${neighbours}

Files:
${files}

## What to write into `${staging_dir}/`

Each doc from its template below: keep the headings, fill every `<…>` placeholder, replace the
HTML comments with what they ask for.

${docs}
### `entry.json`

A JSON object with exactly these keys:

- `description`: one sentence of ${description_min}–${description_max} characters — what the module does, why
  it exists, when a task belongs here;
- `keywords`: at least ${min_keywords} distinct words or short phrases a developer would use in a task
  about this module (domain words, not file names);
- `related_modules` (optional): edges `{"module": "<name>", "relation": "<relation>",
  "description": "<one sentence>"}` to the neighbours above or to other modules of the
  registry; a relation is one of: ${relations}.${ask_fields}

## Rules

- Describe only components that exist: every path you name exists in the repository, and every
  symbol you name occurs in the file you cite. When unsure, leave it out.
- Put every repository path in backticks, root-relative (`src/app/main.py`).
- In `MODULE.md`, list the components in the table `| Name | Path | Purpose |`: `Name` holds one
  symbol in backticks (a function, class, type or constant defined in that file) or plain words
  for a whole file, `Path` the file in backticks.
- Under `## Purpose`, write in your own words what the module is for, as a paragraph that stands
  on its own — do not repeat the description.
- Leave no template placeholder behind (a dollar sign followed by an opening brace).
- Never write outside `${staging_dir}/`; never edit code, the registry or another module's docs;
  never commit.
