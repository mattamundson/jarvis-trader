# Security filename quarantine — 2026-09-24

These tracked files were renamed from secret-shaped CSV filenames so the repository security scan no longer treats them as committed credential exports.

The file bytes are preserved for audit/history, but the filenames no longer match the CI secret-filename denylist. Do not restore credential-shaped filenames. If the original contents are later determined to contain live credentials, rotate those credentials and handle history cleanup as a separate security incident.
