# Test Run Naming

Test Design run names are editable independently from generated test content. Renaming a run updates only `generation_runs.title`; it does not start generation, duplicate test cases, or change execution evidence.

Project metadata uses a separate admin-only API. The frontend hides project editing for non-admin users, and the backend enforces the `admin` role independently of the UI.
