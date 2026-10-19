# en-zh-translation

A Claude Code skill for English ↔ Chinese translation (英译汉 / 汉译英).

- Covers both directions and most genres: fiction, essays, news and commentary, political and official documents, speeches, science, law, letters, tourism, poetry, drama.
- Short texts are translated in a single pass, followed by a checklist self-review.
- Long texts and files (PDF / EPUB / DOCX / TXT) go through a multi-agent pipeline: translator → term & sense check → **blind** target-language editor (never sees the source) → bilingual reviewer who returns targeted fixes only.

## Install

```bash
git clone <this repo> ~/.claude/skills/en-zh-translation
pip install python-docx ebooklib beautifulsoup4 pymupdf lxml   # only needed for file input
```

Then ask Claude Code to translate something, e.g. "把这段译成英文" or "translate this chapter into Chinese".

## Layout

| Path | Contents |
|---|---|
| `SKILL.md` | Workflow, routing table, agent prompts |
| `references/` | Operational rules distilled from the books below (in Chinese) |
| `scripts/extract.py` | Text extraction from PDF / EPUB / DOCX / TXT, with chunking |

## Sources

The rules in `references/` are study notes distilled from these textbooks. They are not substitutes for the books; please buy them.

- 孙致礼《新编英汉翻译教程》（第 2 版），上海外语教育出版社 → `sun-zhili-e2c.md`
- 冯庆华《实用翻译教程（英汉互译）》（第 3 版），上海外语教育出版社，2010 → `feng-qinghua-techniques.md`, `feng-qinghua-style-genres.md`
- Joan Pinkham《中式英语之鉴》(*The Translator's Guide to Chinglish*)，外语教学与研究出版社 → `pinkham-chinglish.md`
- 范守义、郭立秋、贾令仪《英汉语篇翻译教程》，高等教育出版社，2011 → `discourse-cohesion.md`
- 郭立秋、徐英、骆忠武、王红利《英汉时文翻译教程——语篇视角》，世界知识出版社，2017 → `current-affairs-e2c.md`
