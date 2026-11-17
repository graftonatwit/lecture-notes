"""Lecture Notes app: pick a class, hit Record, hit Stop. The note lands in <notes folder>/<class>/Lectures/.
Windows: double-click this file (.pyw = no console window). Mac/Linux: python app.pyw"""
import datetime, json, os, threading, time, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import lecture

SILENCE_WARN_S = 30    # warn if the mic hears nothing this long
SILENCE_LEVEL = 0.003  # rms below this counts as silence; raise if the room is noisy


def ensure_notes_dir():
    """First run: ask where the class folders live. Returns False if the user backs out."""
    try:
        lecture.notes_dir()
        return True
    except SystemExit:
        pass
    messagebox.showinfo("Lecture Notes", "Pick the folder that holds your class folders "
                        "(for example your Obsidian vault's Classes folder), or make a new empty one.")
    path = filedialog.askdirectory(title="Notes folder")
    if not path:
        return False
    lecture.set_notes_dir(path)
    return True


class App:
    def __init__(self, root):
        self.root, self.stop, self.busy, self.note = root, threading.Event(), False, None
        self.level, self.loud_at, self.marks, self.start = 0.0, 0.0, [], 0.0
        root.title("Lecture Notes")
        root.resizable(False, False)
        f = ttk.Frame(root, padding=16)
        f.pack()

        ttk.Label(f, text="Class").grid(row=0, column=0, sticky="w")
        self.course = ttk.Combobox(f, state="readonly", width=34)
        self.course.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        ttk.Button(f, text="+", width=3, command=self.add_class).grid(row=1, column=2, padx=(4, 0), pady=(2, 0))
        ttk.Button(f, text="Schedule…", command=self.edit_schedule).grid(row=0, column=1, columnspan=2, sticky="e")
        self.refresh_classes()

        self.timer = ttk.Label(f, text="00:00:00", font=("Segoe UI", 28))
        self.timer.grid(row=2, column=0, columnspan=3, pady=(12, 0))
        self.meter = ttk.Progressbar(f, maximum=1.0, length=300)
        self.meter.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        self.rec_btn = ttk.Button(f, text="● Record", command=self.toggle)
        self.rec_btn.grid(row=4, column=0, sticky="ew", padx=(0, 4), pady=8)
        self.mark_btn = ttk.Button(f, text="★ Important", command=self.bookmark, state="disabled")
        self.mark_btn.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=8)
        self.file_btn = ttk.Button(f, text="Process audio file / retry clip…", command=self.pick_file)
        self.file_btn.grid(row=5, column=0, columnspan=3, sticky="ew")

        self.status = ttk.Label(f, text="Ready.", wraplength=320, foreground="gray")
        self.status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.open_btn = ttk.Button(f, text="Open note", command=lambda: lecture.open_path(self.note), state="disabled")
        self.open_btn.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.dir_btn = ttk.Button(f, text="Change notes folder…", command=self.change_dir)
        self.dir_btn.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        kept = list(lecture.RECORDINGS.glob("*.wav")) if lecture.RECORDINGS.exists() else []
        if kept:
            self.status.config(text=f"{len(kept)} unprocessed clip(s) in clips/. Use 'retry clip' to finish them.")

    # ---------- classes ----------
    def refresh_classes(self, select=None):
        classes = lecture.list_classes()
        self.course.config(values=classes)
        pick = select or lecture.class_now()
        if pick in classes:
            self.course.set(pick)
        elif classes and self.course.get() not in classes:
            self.course.current(0)
        elif not classes:
            self.course.set("")

    def change_dir(self):
        path = filedialog.askdirectory(title="Notes folder", initialdir=lecture.notes_dir())
        if path and not self.busy:
            lecture.set_notes_dir(path)
            self.refresh_classes()
            self.status.config(text=f"Notes folder: {lecture.notes_dir()}")

    def add_class(self):
        code = simpledialog.askstring("Add class", "Course code (e.g. COMP 3500), or leave blank:", parent=self.root)
        if code is None:
            return
        name = simpledialog.askstring("Add class", "Class name (e.g. Networks):", parent=self.root)
        if not name and not code:
            return
        try:
            folder = lecture.add_class(code.strip(), (name or "").strip())
        except (ValueError, OSError) as e:
            messagebox.showerror("Add class", str(e))
            return
        self.refresh_classes(select=folder.name)
        self.status.config(text=f"Added {folder.name}. Add its times under Schedule… to auto-select it.")

    def edit_schedule(self):
        if not lecture.SCHEDULE.exists():
            example = {c: [] for c in lecture.list_classes()}
            lecture.SCHEDULE.write_text(json.dumps(example, indent=2) + "\n", encoding="utf-8")
        messagebox.showinfo("Schedule", 'Add times per class, e.g.\n"COMP 3400 Operating Systems": ["Tue 08:00-09:30", "Thu 08:00-09:30"]\n\n'
                            "Save the file, then reopen the app.")
        lecture.open_path(lecture.SCHEDULE)

    # ---------- recording ----------
    def set_status(self, msg):
        self.root.after(0, lambda: self.status.config(text=msg))

    def lock(self, on):
        state = "disabled" if on else "normal"
        self.root.after(0, lambda: (self.file_btn.config(state=state), self.dir_btn.config(state=state),
                                    self.course.config(state="disabled" if on else "readonly")))

    def on_level(self, rms):  # audio thread: just store; UI thread reads it
        self.level = rms
        if rms > SILENCE_LEVEL:
            self.loud_at = time.time()

    def bookmark(self):
        self.marks.append(time.time() - self.start)
        self.mark_btn.config(text=f"★ Important ({len(self.marks)})")

    def toggle(self):
        if self.busy and self.rec_btn["text"].startswith("■"):
            self.stop.set()
            self.rec_btn.config(text="● Record", state="disabled")
            self.mark_btn.config(state="disabled")
            return
        if self.busy or not self.course.get():
            return
        self.busy, self.note, self.marks = True, None, []
        self.stop.clear()
        self.open_btn.config(state="disabled")
        self.rec_btn.config(text="■ Stop")
        self.mark_btn.config(text="★ Important", state="normal")
        self.lock(True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
        lecture.RECORDINGS.mkdir(exist_ok=True)
        audio = lecture.RECORDINGS / f"{stamp}.wav"
        self.start = self.loud_at = time.time()

        def tick():
            if self.stop.is_set():
                self.meter.config(value=0)
                return
            s = int(time.time() - self.start)
            self.timer.config(text=f"{s // 3600:02}:{s // 60 % 60:02}:{s % 60:02}")
            self.meter.config(value=min(1.0, self.level * 8))  # *8 so speech fills a visible chunk of the bar
            quiet = time.time() - self.loud_at
            self.status.config(text=f"⚠ Mic has heard nothing for {int(quiet)}s. Check the mic." if quiet > SILENCE_WARN_S
                               else "Recording… press Stop when class ends.")
            self.root.after(200, tick)
        tick()
        threading.Thread(target=self.run, args=(audio, stamp, True, self.course.get()), daemon=True).start()

    def pick_file(self):
        path = filedialog.askopenfilename(initialdir=lecture.RECORDINGS,
                                          filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"), ("All", "*.*")])
        if not path or self.busy or not self.course.get():
            return
        p = Path(path)
        ours = p.parent.resolve() == lecture.RECORDINGS.resolve()  # a kept clip: reuse its date, delete when done
        stamp = p.stem if ours else datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
        self.busy = True
        self.rec_btn.config(state="disabled")
        self.lock(True)
        threading.Thread(target=self.run, args=(p, stamp, ours, self.course.get(), False), daemon=True).start()

    def run(self, audio, stamp, delete, course, record=True):
        try:
            if record:
                lecture.record(audio, self.stop, self.on_level)
            self.set_status("Transcribing…")
            self.root.after(0, lambda: self.rec_btn.config(state="disabled"))
            lecture.print = lambda *a: self.set_status(" ".join(map(str, a)))  # route progress to the window
            try:
                self.note = lecture.process(audio, lecture.notes_dir() / course, stamp, delete, self.marks if record else ())
            finally:
                del lecture.print
            self.set_status(f"Saved: {self.note.name}")
            self.root.after(0, lambda: self.open_btn.config(state="normal"))
        except BaseException as e:  # lecture.py uses sys.exit for errors; clip is kept in clips/
            self.set_status(f"Failed: {e}\nClip kept in clips/; use 'retry clip' to try again.")
        finally:
            self.busy = False
            self.stop.set()
            self.lock(False)
            self.root.after(0, lambda: self.rec_btn.config(text="● Record", state="normal"))

    def on_close(self):
        if self.busy:
            if not messagebox.askokcancel("Still working", "Recording or processing is in progress. Quit anyway?\n(Any audio so far stays in clips/.)"):
                return
            self.stop.set()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    if ensure_notes_dir():
        root.deiconify()
        App(root)
        root.mainloop()
