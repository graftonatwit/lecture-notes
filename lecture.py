"""Record a lecture from the mic, transcribe it on your computer with faster-whisper, and let
Claude (the `claude` CLI) turn the transcript into study notes in your notes folder.

    python lecture.py "COMP 3400"                    # record until Ctrl+C, then write the note
    python lecture.py "COMP 3400" --file talk.m4a    # use an existing recording instead
    python lecture.py --set-notes-dir ~/Notes/Classes
"""
import argparse, datetime, glob, json, os, queue, re, shutil, subprocess, sys, wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"      # {"notes_dir": "...", "model": "small.en"}
SCHEDULE = HERE / "schedule.json"  # {"Class folder name": ["Tue 08:00-09:30"]}
RECORDINGS = HERE / "clips"        # audio waiting to be processed; deleted once the note is saved
NOTES_DIR = None                   # override (tests); normally from config.json or $LECTURE_NOTES_DIR
CLASS_SUBFOLDERS = ["Lectures", "Attachments"]
RATE = 16000

PROMPT = """You are writing study notes from a raw lecture/meeting transcript (auto-transcribed, may contain errors).
Output ONLY markdown, no preamble. First line must be "# <topic>": just the lecture topic, no "Study Notes"/"Notes"/"Lecture" prefix.
Then these sections: ## Key ideas, ## Examples, ## Action items / due dates (omit if none), ## Questions (things unclear or worth asking).
Passages starting with "[IMPORTANT]" were flagged by the student during class: if there are any, put a "## Flagged moments" section right after the title listing each one, and still cover them in the other sections.
Be concise. Use ONLY what the transcript says: no outside background, no offers to expand. Course: {course}."""


# ---------- config ----------
def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_notes_dir(path):
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({**load_config(), "notes_dir": str(p)}, indent=2) + "\n", encoding="utf-8")
    return p


def notes_dir():
    """Folder with one subfolder per class: an Obsidian vault folder or any plain folder."""
    p = NOTES_DIR or os.environ.get("LECTURE_NOTES_DIR") or load_config().get("notes_dir")
    if not p:
        sys.exit('No notes folder set. Run: python lecture.py --set-notes-dir "<folder>"')
    return Path(p).expanduser()


# ---------- classes ----------
def list_classes():
    return sorted(d.name for d in notes_dir().iterdir() if d.is_dir() and not d.name.startswith((".", "_")))


def find_class(query):
    hits = [c for c in list_classes() if query.lower() in c.lower()]
    if len(hits) != 1:
        sys.exit(f"'{query}' matched {hits or 'no class'} in {notes_dir()}. "
                 f"Classes are the folders there; make one (or use the app's + button) and retry.")
    return notes_dir() / hits[0]


def home_note(class_dir):
    homes = sorted(class_dir.glob("* Home.md"))
    return homes[0] if homes else None


def add_class(code, name):
    """Create <notes>/<code name>/ with Lectures + Attachments and a Home note. If the notes
    folder has a 'Classes Home.md' list, the new class is linked there too."""
    title = f"{code} {name}".strip()
    if not title or re.search(r'[\\/:*?"<>|]', title):
        raise ValueError(f"Bad class name: {title!r}")
    folder = notes_dir() / title
    if folder.exists():
        raise ValueError(f"{title} already exists")
    for sub in CLASS_SUBFOLDERS:
        (folder / sub).mkdir(parents=True)
    home = f"{code or name} Home"
    (folder / f"{home}.md").write_text(
        f'---\ncourse: "{title}"\ntype: "course-home"\n---\n\n# {title}\n\n## Recorded lectures\n', encoding="utf-8")
    index = notes_dir() / "Classes Home.md"
    if index.exists():
        lines = index.read_text(encoding="utf-8").splitlines()
        last = max((i for i, l in enumerate(lines) if l.startswith("- [[")), default=len(lines) - 1)
        lines.insert(last + 1, f"- [[{home}]] {name or code}")
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def class_now(now=None):
    """Class from schedule.json that is on now (or starts within 10 min), else None.
    Format: {"COMP 3400 Operating Systems": ["Tue 08:00-09:30", "Thu 08:00-09:30"]}"""
    now = now or datetime.datetime.now()
    try:
        sched = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for course, slots in sched.items():
        for slot in slots:
            m = re.fullmatch(r"(\w{3})\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", slot.strip())
            if not m or m[1].lower() != now.strftime("%a").lower():
                continue
            start = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(m[2].zfill(5)))
            end = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(m[3].zfill(5)))
            if start - datetime.timedelta(minutes=10) <= now <= end:
                return course
    return None


def open_path(p):
    if sys.platform == "win32":
        os.startfile(p)
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(p)])


# ---------- recording + transcription ----------
def record(path, stop=None, level=None):
    """Record until Ctrl+C, or until `stop` (a threading.Event) is set by the GUI.
    `level(rms)` gets the mic loudness (0..1) for a meter."""
    import numpy as np, sounddevice as sd
    q = queue.Queue()

    def cb(d, *_):
        q.put(bytes(d))
        if level:
            level(float(np.sqrt(np.mean(d.astype(np.float32) ** 2))) / 32768)
    # Written to disk as it records so a crash mid-lecture keeps the audio.
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(RATE)
        with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", callback=cb):
            print(f"Recording to {path}. Ctrl+C to stop.")
            try:
                while not (stop and stop.is_set()):
                    try:
                        wf.writeframes(q.get(timeout=0.2))
                    except queue.Empty:
                        pass
            except KeyboardInterrupt:
                pass
            while not q.empty():
                wf.writeframes(q.get())
    print("Stopped.")


def _add_cuda_dlls():
    # Optional GPU support: the nvidia-cublas-cu12 / nvidia-cudnn-cu12 pip packages ship the CUDA libs.
    try:
        import nvidia
    except ImportError:
        return
    for b in glob.glob(os.path.join(nvidia.__path__[0], "*", "bin")):
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(b)
        os.environ["PATH"] = b + os.pathsep + os.environ["PATH"]


def _flag(segs, marks):
    """Prefix "[IMPORTANT]" to the segment being spoken at each bookmark (seconds)."""
    flagged = {max([i for i, s in enumerate(segs) if s.start <= m] or [0]) for m in marks}
    return " ".join(("[IMPORTANT] " if i in flagged else "") + s.text.strip() for i, s in enumerate(segs))


def transcribe(path, marks=()):
    from faster_whisper import WhisperModel
    _add_cuda_dlls()
    model_name = load_config().get("model", "small.en")  # medium.en is more accurate but wants a GPU
    try:
        model = WhisperModel(model_name, device="cuda", compute_type="float16")
        segs = list(model.transcribe(str(path), vad_filter=True)[0])
    except Exception as e:  # no usable GPU: fall back to CPU
        print(f"GPU not used ({e}); using CPU (slower).")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segs = list(model.transcribe(str(path), vad_filter=True)[0])
    return _flag(segs, marks) if segs else ""


# ---------- notes ----------
def write_notes(transcript, class_dir, stamp):
    if not shutil.which("claude"):
        sys.exit("Claude Code CLI ('claude') not found on PATH. Install it and log in, then retry.")
    # --setting-sources "" keeps your own Claude settings/hooks out of the notes.
    # Prompt goes in on stdin: a multi-line argument gets cut at the first newline by cmd.exe.
    prompt = PROMPT.format(course=class_dir.name) + "\n\nTRANSCRIPT:\n" + transcript
    out = subprocess.run(["claude", "-p", "--setting-sources", ""], input=prompt,
                         capture_output=True, text=True, encoding="utf-8", shell=sys.platform == "win32",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # no console flash from the GUI
    if out.returncode != 0 or not out.stdout.strip().startswith("#"):
        sys.exit(f"claude failed:\n{out.stderr or out.stdout}")
    # Strip a "Study Notes:" style prefix/suffix in case the model adds one anyway.
    body = re.sub(r"^#\s*(study notes|lecture notes|notes)\s*[:\-–]?\s*", "# ", out.stdout.strip(), flags=re.I)
    body = re.sub(r"^(#.*?)(?:\s+|\s*[:\-–]\s*)(study notes|lecture notes|notes)\s*$", r"\1", body, count=1, flags=re.I | re.M)
    title = re.sub(r'[\\/:*?"<>|#\[\]]', "", body.splitlines()[0]).strip()
    date = stamp[:10]
    note = class_dir / "Lectures" / f"{date} {title}.md"
    note.parent.mkdir(exist_ok=True)
    i = 2
    while note.exists():  # never overwrite an existing note
        note = note.with_name(f"{date} {title} {i}.md"); i += 1

    # Raw transcript kept beside the class, searchable.
    tr = class_dir / "Attachments" / f"{note.stem} transcript.md"
    tr.parent.mkdir(exist_ok=True)
    tr.write_text(f'---\ncourse: "{class_dir.name}"\ntype: "transcript"\ndate: {date}\n---\n\n'
                  f"Lecture note: [[{note.stem}]]\n\n{transcript}\n", encoding="utf-8")

    home = home_note(class_dir)
    links = (f"Course: [[{home.stem}]] · " if home else "") + f"Transcript: [[{tr.stem}]]"
    head, _, rest = body.partition("\n")
    front = f'---\ncourse: "{class_dir.name}"\ntype: "lecture"\ndate: {date}\ntags: [lecture, transcript]\n---\n\n'
    note.write_text(f"{front}{head}\n\n{links}\n\n{rest.strip()}\n", encoding="utf-8")
    if home:
        link_home(home, note.stem)
    return note


def link_home(home, stem, heading="## Recorded lectures"):
    """Add [[stem]] under `heading` in the course Home note (heading created if missing)."""
    lines = home.read_text(encoding="utf-8").splitlines()
    if heading not in lines:
        lines += ["", heading]
    i = lines.index(heading) + 1
    while i < len(lines) and not lines[i].startswith("#"):
        i += 1
    while i > 0 and not lines[i - 1].strip():  # insert after the last item, not after blank lines
        i -= 1
    lines.insert(i, f"- [[{stem}]]")
    home.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process(audio, class_dir, stamp, delete_audio, marks=()):
    """Transcribe + write the note. Clips are only deleted after the note is saved."""
    print("Transcribing...")
    text = transcribe(audio, marks)
    RECORDINGS.mkdir(exist_ok=True)
    txt = RECORDINGS / f"{stamp}.txt"
    txt.write_text(text, encoding="utf-8")
    if not text.strip():
        sys.exit(f"Empty transcript. Clip kept: {audio}")
    print("Writing notes...")
    note = write_notes(text, class_dir, stamp)  # exits on failure, so clips survive a failed run
    txt.unlink()
    if delete_audio:  # only delete clips we recorded, never a file you passed in
        Path(audio).unlink()
    return note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("course", nargs="?", help="part of a class folder name, e.g. 3400")
    ap.add_argument("--file", help="existing audio file instead of recording")
    ap.add_argument("--set-notes-dir", metavar="FOLDER", help="folder that holds your class folders")
    a = ap.parse_args()
    if a.set_notes_dir:
        print("Notes folder:", set_notes_dir(a.set_notes_dir))
        return
    if not a.course:
        ap.error("give a class, e.g.: python lecture.py 3400")
    class_dir = find_class(a.course)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    RECORDINGS.mkdir(exist_ok=True)
    audio = Path(a.file) if a.file else RECORDINGS / f"{stamp}.wav"
    if not a.file:
        record(audio)
    print(process(audio, class_dir, stamp, delete_audio=not a.file))


if __name__ == "__main__":
    main()
