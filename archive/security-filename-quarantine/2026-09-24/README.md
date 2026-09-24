# Security filename quarantine — 2026-09-24

These tracked files were renamed from secret-shaped CSV filenames so the repository security scan no longer treats them as committed credential exports.

Potential credential values in the archived copies are redacted in-repo. Do not restore credential-shaped filenames. If the original contents are later determined to contain live credentials, rotate those credentials and handle history cleanup as a separate security incident.
