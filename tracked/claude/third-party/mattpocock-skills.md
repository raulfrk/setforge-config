# Skills copied from mattpocock/skills

Source: https://github.com/mattpocock/skills, commit
`49dd158d1076134a641b33efb035946536778336` (2026-10-09), MIT licence.

These files are unmodified copies, deployed to `~/.claude/skills/` by the
`claude` profile. Compare with upstream before changing them; re-copy at a new
commit to update.

| Deployed skill | Upstream path | Invocation |
| --- | --- | --- |
| `wait-what` | `skills/productivity/wait-what/SKILL.md` | user only |
| `grill-me` | `skills/productivity/grill-me/SKILL.md` | user only |
| `grilling` | `skills/productivity/grilling/SKILL.md` | model or user |
| `wizard` | `skills/engineering/wizard/{SKILL.md,template.sh}` | model or user |
| `writing-for-agents` | `skills/productivity/writing-for-agents/{SKILL.md,SKILL-MECHANICS.md}` | model or user |
| `retro` | `skills/engineering/retro/SKILL.md` | user only |
| `domain-modeling` | `skills/engineering/domain-modeling/{SKILL.md,ADR-FORMAT.md,GLOSSARY-FORMAT.md}` | model or user |

`grill-me` only calls `grilling`, and `retro` calls `writing-for-agents`, so each
group deploys together. The upstream `agents/openai.yaml` files are for Codex
and are not copied.

```
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
