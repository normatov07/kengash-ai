# Slicing for width

Independent tickets run at once; every needless edge makes the loop wait.

- `depends_on` names only the slices whose code this slice calls, extends, or edits after they create it, and `needs` says what it uses, such as `{core: the BoardRenderer interface}`. Slices that only share an area need no edge: kengash starts them together and keeps their edits apart. If you cannot name what it uses, drop the edge.
- A slice others depend on lists `provides`: each interface, data format or file they use, with its exact signature or shape, such as `BoardRenderer.paint(Canvas, Size) -> void`. Parallel work fails on vague contracts, so be exact here; each provided line also needs an Acceptance line.
- Put the shared foundation (a schema, an interface, a design token file) in its own early slice, so many slices can follow it at once.
- `touches` names the narrowest folders or files the slice changes. Never list a top-level folder (`lib/`, `src/`, `test/`) unless the slice rewrites most of it. Put tests under the code's own path, such as `test/rendering/board/` next to `lib/rendering/board/`.
- The planner later narrows `touches` to the exact files it will change.

What `--check` prints, and what to do:

- `chokepoint`: many slices wait on one in the middle. Move what they use (an interface, a contract, a stub) into an early foundation slice and depend on that.
- `one at a time`: two slices share files. Move the shared change into a slice both follow, or accept the wait.
- `too broad`: claim the folders the slice really changes.
- `hot file`: many past tickets changed it. Put its change in one slice and have the others follow it.
