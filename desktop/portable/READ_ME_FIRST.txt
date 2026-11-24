CHAUHAN CLIPPING - portable (nothing to install)

1. Right-click the zip > Extract All (into a folder such as D:\ChauhanClipping). Do NOT run it from inside the zip.
2. Open the folder and double-click  run.bat

Inside this folder already: Python, FFmpeg and the AI speech detector (Silero). No internet and no download is
needed for Simple Edit, Timeline, Auto Short, colour, text, overlays, silence cut and dialogue clean-up.

ONLY ONE OPTIONAL EXTRA: the Whisper speech-to-text model, used by "AI Clipping" and by "text editing" (removing words
like um/uh). It is a separate zip (ChauhanClipping-WhisperModel-small.zip, about 480 MB). Extract it INTO this same
folder (the folder "models" is merged). Without it the app works fine, and Whisper is downloaded once from the
internet the first time you use AI Clipping / text editing.

Projects are saved in the "projects" folder, exported videos in "exported_clips".
To update to a newer version later, replace only the .py files - or just extract the new zip over this folder.
run_check.bat = checks that everything works (optional).

NEW: VIRAL CLIPS (AI) TAB - movie / YouTube video / live stream to ready-to-post clips
- Choose a movie (Browse... or YouTube link), press FIND VIRAL CLIPS. The movie is worked on in parts: the clips
  of part 1 are exported while part 2 is already being listened to.
- Built-in works offline without a key. For AI-picked moments, titles and hashtags choose a service in the
  "AI Clips" tab (Google Gemini and Groq have free keys) and paste the key.
- Word-by-word captions, hook title, follow-the-speaker / facecam / interview layouts, cover + post text,
  and every edit of the section (colour, crop, overlay, text, effects, silence / dialogue cut, export quality).

NEW: "YouTube link" button (Simple Edit / AI Clipping / Viral Clips)
- Paste a YouTube / Instagram / Facebook / X link, the video is downloaded into input_movies and opened.
  Its captions are saved next to it (Viral Clips can use them instead of Whisper).
