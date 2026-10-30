# Importance rubric

Pick the first row that fits; importance chooses the ticket's workflow.

| Importance | When the slice |
|---|---|
| critical | touches authentication, secrets, payments, data migrations, infrastructure, or anything that cannot be undone |
| standard | spans several modules, or changes a public interface (an API, a CLI, a file format, a schema) |
| simple | anything else |

When in doubt between two rows, take the higher one and say why in the list you show the user.
