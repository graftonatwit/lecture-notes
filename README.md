# Lecture Notes

Record a lecture, press Stop, and get organized study notes in your notes folder. A small desktop app (or command line) that records your mic, transcribes it on your own computer with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and has Claude write the notes.

You get, per lecture:

- a note with **Key ideas**, **Examples**, **Action items / due dates** and **Questions**
- a **Flagged moments** section for anything you marked with the ★ Important button during class
- the full transcript, saved as a searchable note next to it
- links between the note, its transcript and the class's Home note, so it works nicely in Obsidian (plain folders work too)

> **Ask your professor before recording.** Many schools and instructors require permission to record a class. Follow your school's policy.

## What you need

- Python 3.10 or newer (on Linux, also `python3-tk`)
- A microphone
- The [Claude Code CLI](https://claude.com/claude-code), installed and logged in. It writes the notes, so you need a Claude plan that includes Claude Code.

## Setup

```bash
git clone https://github.com/graftonatwit/lecture-notes
cd lecture-notes
pip install -r requirements.txt
```

The first transcription downloads a speech model (a few hundred MB), then works offline.

## Use the app

- **Windows:** double-click `app.pyw`.
- **Mac/Linux:** `python app.pyw`.

On first run it asks for a **notes folder**: the folder that holds one subfolder per class. Pick your Obsidian vault (or a `Classes` folder inside it), or make a new empty folder.

1. Press **+** to add a class (it creates the folder, a Home note, and `Lectures` / `Attachments` subfolders). A plain folder you create yourself works as well.
2. Pick the class and press **● Record**. The green bar moves when the mic hears sound, and a warning appears if it hears nothing for 30 seconds.
3. Press **★ Important** whenever the instructor says something worth flagging, like an exam hint.
4. Press **■ Stop** when class ends. Transcribing and writing take a minute or a few, then **Open note**.

**Schedule…** opens `schedule.json`, where you can list each class's times (for example `"Tue 08:00-09:30"`) so the app preselects the class that's on now.

**Process audio file / retry clip…** turns an existing recording into a note, or finishes a clip left behind by a failed run.

### Command line

```bash
python lecture.py --set-notes-dir "~/Notes/Classes"   # once
python lecture.py "3400"                              # record until Ctrl+C, then write the note
python lecture.py "3400" --file lecture.m4a           # use an existing recording
```

The class argument is any part of a class folder's name.

## Notes layout

```
<notes folder>/
  COMP 3400 Operating Systems/
    COMP 3400 Home.md
    Lectures/2026-11-12 Implementing Locks.md
    Attachments/2026-11-12 Implementing Locks transcript.md
```

## Speed and accuracy

By default it uses the `small.en` model, which is fast enough on a laptop CPU. With an NVIDIA GPU, uncomment the two `nvidia-*` lines in `requirements.txt`, install them, and set a better model in `config.json`:

```json
{ "model": "medium.en" }
```

## Privacy

- Audio is recorded and transcribed **on your computer**. The recording is deleted as soon as the note is saved (a failed run keeps it in `clips/` so you can retry).
- The **transcript text is sent to Claude** to write the notes, so it is covered by Anthropic's terms for your account. Don't use it for lectures you aren't allowed to share with an AI service.
- `config.json`, `schedule.json` and `clips/` are git-ignored and stay on your machine.

## Tests

```bash
python test_lecture.py
```

## License

MIT. Not affiliated with any school.
