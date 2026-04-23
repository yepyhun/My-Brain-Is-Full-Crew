# Transcriber

> Turns raw recordings and transcripts into structured, actionable meeting intelligence.

## What it does

All transcription processing is now handled by the `/transcribe` skill, which runs as a guided, multi-turn conversation. The skill takes raw audio transcripts (meetings, lectures, podcasts, interviews, voice memos) and transforms them into richly structured Obsidian notes. It does not just clean up text. It extracts the intelligence: decisions made, action items with owners and deadlines, key insights, emotional dynamics, and follow-up needs.

Paste a messy Zoom transcript full of filler words and speaker labels, and the `/transcribe` skill will produce a polished meeting note with an executive summary, a decisions log, an action items table with confidence scores, and even a draft follow-up email you can send to attendees. Paste lecture notes, and it creates study-ready material with key concepts, definitions, and exam-relevant highlights.

The `/transcribe` skill works with whatever you give it, whether that is output from Whisper, Otter.ai, Google Meet auto-transcription, or your own handwritten notes from a call. It adapts its parsing to the source format and asks just enough context questions to produce the best possible output.

The Transcriber agent itself is kept for edge cases and direct follow-ups not covered by the skill.

## Capabilities

All of the following capabilities are delivered through the `/transcribe` skill:

- **Meeting notes**: full meeting processing with executive summary, key points, decisions log, action items table (with confidence scores), detailed notes by topic, open questions, next steps, and a follow-up email draft
- **Lecture notes**: structured academic notes with key concepts, definitions, exam-relevant points, and connections to previous material
- **Podcast summaries**: TL;DR, numbered key insights, notable quotes, detailed breakdown by topic, and resources mentioned
- **Interview extraction**: structured Q&A format, key takeaways, notable quotes, and follow-up questions
- **Voice journal**: personal reflections with mood detection, structured themes, and insights
- **General transcription**: clean transcript with executive summary and key points for anything that does not fit the above
- **Multi-speaker detection**: identifies and labels different speakers throughout the transcript
- **Action item extraction**: catches explicit, implicit, and conditional actions with confidence levels
- **Sentiment analysis**: flags emotionally charged segments (heated debates, frustration, enthusiasm)
- **Glossary generation**: extracts domain-specific terms and jargon into a glossary table
- **Follow-up email generator**: creates a ready-to-send email summarizing meeting outcomes

## How to use it

Paste a transcript or describe what you want to process. All of these phrases invoke the `/transcribe` skill:

- "Transcribe this meeting: [paste transcript]"
- "Process these meeting notes"
- "Summarize this podcast transcript"
- "Create lecture notes from this: [paste]"
- "Process my voice memo"
- "What came out of the meeting? [paste]"
- "Interview notes: [paste transcript]"

In Italian: "Trascrivi", "Sbobina", "Note del meeting", "Riassumi la call"
In French: "Transcrire", "Notes de reunion", "Resume du podcast"
In Spanish: "Transcribir", "Notas de reunion", "Resumen del podcast"
In German: "Transkribieren", "Besprechungsnotizen", "Podcast-Zusammenfassung"

## Example conversations

### Meeting transcript processing

**You:** Process this meeting transcript: [pastes a 40-minute Zoom meeting transcript]

**Transcriber:** Before I process this, let me gather some context:

1. Date of the meeting? (I will default to today if not specified)
2. Can you confirm the participants? I detected 4 speakers: Marco, Sarah, you, and someone labeled "Speaker D"
3. Does this relate to a specific project?

**You:** Yesterday, Speaker D is Luca, it's about Project Alpha

**Transcriber:** Got it. Here is the processed meeting note:

**Sprint Planning, Project Alpha** (saved to `00-Inbox/`)

- Executive Summary: 4-sentence overview of the meeting
- 6 Key Points covering the main topics discussed
- 3 Decisions Made (with who decided and rationale)
- Action Items table:

| Who | What | Deadline | Confidence |
|-----|------|----------|------------|
| You | Deliver pricing report | Friday | High |
| Marco | Review API specs | Next Monday | High |
| Sarah | Schedule client demo | TBD | Medium |
| Luca | Investigate performance issue | This week | Low (inferred) |

- Detailed notes broken into 4 topic sections with timestamps
- 2 Open questions flagged for follow-up
- Follow-up email draft ready to send to attendees

Want me to adjust anything?

---

### Podcast summary

**You:** Summarize this podcast transcript. It's the Tim Ferriss show, episode about deep work with Cal Newport

**Transcriber:** Created `2026-03-21 - Podcast - Tim Ferriss on Deep Work.md`

**TL;DR:** Cal Newport argues that deep work is becoming both rarer and more valuable in the knowledge economy. The key insight: scheduling deep work blocks is more effective than trying to "find time" for it.

**Key Insights (7):**
1. Deep work is a skill that atrophies without practice...
2. The "any benefit" mindset for tools is the enemy of focus...
[...]

**Notable Quotes:** 3 blockquotes captured with speaker attribution

**Resources Mentioned:** 4 books and 2 tools referenced in the episode

I also noticed this connects to your notes on productivity systems in `03-Resources/`. Want me to flag it for the Connector?

---

### Voice journal

**You:** Process my voice memo: [pastes a personal reflection transcript]

**Transcriber:** Processed as a Voice Journal entry.

**Detected mood:** Reflective, slightly anxious
**Energy level:** Medium

Core reflection: You are processing the tension between your desire to take on the new project and your concern about overcommitting, especially given recent burnout.

I structured your thoughts into 3 themes: work-life boundaries, the new project opportunity, and recovery from burnout.

Saved as `2026-03-21 - Voice Journal - New Project Tensions.md`. Want to review it?

## Works with

- **Sorter**: all transcription output lands in the Inbox for the Sorter to file
- **Postman**: when a meeting note references email threads, the Transcriber flags the Postman to cross-link
- **Architect**: when a meeting introduces a new project or area, the Transcriber notifies the Architect
- **Connector**: meeting notes that reference past decisions are flagged for cross-linking

## Tips

- **Provide participant names upfront.** The Transcriber asks for names, but giving them in your first message saves a round trip.
- **Mention the project or area.** Context helps the Transcriber tag and link more accurately.
- **Use the follow-up email draft.** For work meetings, the auto-generated email is a huge time saver. Review it and send.
- **Check the confidence scores on action items.** "High" means someone explicitly said it. "Low" means the Transcriber inferred it from context, so verify these.
- **Use voice journal mode for personal reflections.** It preserves your authentic voice instead of making everything sound corporate.
- **Paste raw transcripts without cleanup.** The Transcriber handles filler words, broken sentences, and transcription artifacts. Do not waste time pre-editing.

## What it remembers

The Transcriber keeps a post-it in `Meta/states/transcriber.md` with notes from its last transcription: speaker names and roles it learned, meeting series context, and domain terminology it discovered. This means it gets better at identifying speakers and jargon over time.
