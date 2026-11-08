# Slicing for width

Independent tickets run at once; every needless edge makes the loop wait.

- `depends_on` names only the slices whose code this slice calls, extends, or edits after they create it. Slices that only share an area need no edge: kengash starts them together and keeps their edits apart.
- Put the shared foundation (a schema, an interface, a design token file) in its own early slice, so many slices can follow it at once.
- `touches` names the narrowest folders or files the slice changes. Never list a top-level folder (`lib/`, `src/`, `test/`) unless the slice rewrites most of it. Put tests under the code's own path, such as `test/rendering/board/` next to `lib/rendering/board/`.
- The planner later narrows `touches` to the exact files it will change.
