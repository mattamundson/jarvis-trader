# Bundled fonts

Latin, normal-style variable WOFF2 files, vendored from the npm packages
`@fontsource-variable/inter@5.3.0`,
`@fontsource-variable/jetbrains-mono@5.3.0`, and
`@fontsource-variable/orbitron@5.3.0`:

- `Inter-latin.woff2`: `files/inter-latin-wght-normal.woff2` (weights 100–900).
- `JetBrainsMono-latin.woff2`: `files/jetbrains-mono-latin-wght-normal.woff2` (weights 100–800).
- `Orbitron-latin.woff2`: `files/orbitron-latin-wght-normal.woff2` (weights 400–900).

All are distributed under the SIL Open Font License 1.1; the corresponding
license and copyright notices are included alongside the fonts.

`app/layout.tsx` and `app/command-center/page.tsx` load these files with
`next/font/local` so builds do not fetch or parse Google Fonts responses. Tailwind's `font-sans` and `font-mono`
utilities use the generated CSS variables, including on the home page.
