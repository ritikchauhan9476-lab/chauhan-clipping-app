# Chauhan Clipping

Video editor and AI viral clipper for Windows.

Tabs:
- **Simple Edit** - cut a movie into parts and edit each part (overlays, text, colour, crop, silence cut).
- **AI Clipping** - the AI finds funny / emotional clips, then you edit and export them with the same tools.
- **Timeline (advanced)** - multi-layer timeline editor for complex projects.
- **Projects** - save, open and continue later (project bar at the top).
- **Auto Short** - one button: continuous-dialogue shorts (silence cut from picture and sound), made one by one.

## First-time setup
1. Double-click **setup.bat** (needs internet, 5 to 15 minutes). It does everything:
   - finds Python 3.10 - 3.12 (if Python is missing it installs Python 3.12 with winget; then run setup.bat again),
   - creates the `venv` and installs all packages,
   - installs the **AI speech detector** (Silero VAD through onnxruntime, no PyTorch),
   - installs FFmpeg with winget if it is missing (restart the PC once afterwards).
2. Double-click **run.bat** to start the app.

Always start the app with run.bat. Do not open app.py directly. If the AI detector step failed, the app still works
with a built-in detector; double-click **install_ai.bat** later to try again.

## Projects: save your work and continue later
The **PROJECT** bar at the top of the window works like the project option of any editing software.
- **Save (Ctrl+S)** - the first time it asks for a name; the file (`.ccproj`) goes to the `projects` folder.
  **Save as** makes a copy under another name. **Open (Ctrl+O)** opens a project. **New** starts an empty one.
- A project remembers, for every tab (Simple Edit, AI Clipping, Timeline, Auto Short): the movie, the parts and which
  are ticked, all texts (with `{n}` part numbers and centring) and overlays, colour correction, crop, background,
  export settings, silence and dialogue settings, the **selected part and the exact second where you stopped**,
  and the tab you were in.
- **Close the software and open it again**: it opens the last project by itself and you are back where you stopped
  (untick "Open the last project when the app starts" if you do not want that).
- A `*` next to the project name means unsaved changes. When you close the window, New or Open, the software asks
  whether to save. Moving the playhead or switching tabs is not a change; if only that changed, the place where you
  stopped is saved silently when you close.
- **Autosave**: every 2 minutes, while there are unsaved changes, a recovery copy (`<project>.ccproj.autosave`) is
  written. After a crash or power cut, opening the project offers to restore it.
- The project stores the path of the movie, not the movie itself. If you moved the movie, the software looks next to
  the project file and in `input_movies`, and otherwise asks you to point to it. Exported videos are not part of the
  project. Silence scans are stored too, but they are used again only if the movie and the silence settings are the same.

## Simple Edit and AI Clipping (same tools in both tabs)
1. **Movie** - choose from the top bar (put files in `input_movies`, then click Refresh) or Browse.
2. **Parts** (left) - set Start and End (seconds), then either a number of parts or a part length, and click
   **Make parts**. In AI Clipping, click **Find clips with AI** instead.
   Tick a part to export it. Use **Show** to preview a part and **x** to remove it.
3. **Preview** (centre) - drag an overlay or text with the mouse. Use the position slider to move through the part.
5. **Colour** - brightness, contrast, saturation, gamma, sharpness, hue, warmth. Changes show live.
6. **Overlay** - add a photo, video or GIF. Position by dragging or by typing X / Y (%). Size, opacity and
   start / end time are set in the same panel.
   To remove a background: tick "Remove the colour I pick", click "Pick from picture" and click the colour on the
   preview, then adjust "Colour match" and "Edge softness".
7. **Text** - add text, change font, size, colour, outline, shadow, background box, position and timing.
**Cutting ON / OFF** - at the top of the Export tab there are two switches: *Cut silent pauses* and *Dialogue clean-up*. Both OFF = the movie is only converted into parts and nothing is removed. The export button shows what it will do (PLAIN PARTS / SILENCE CUT / DIALOGUE CLEAN-UP).

8. **Silence** - cut silent pauses longer than a set number of seconds (default 2 s, quieter than -35 dB).
   Click **Scan** once; the scan is fast (audio only). Each part can also be left uncut with its "cut silence" box.
9. **Export** - resolution, frame rate, codec and bitrate, then **EXPORT SELECTED PARTS**.

Output folder: `exported_clips`. Each run creates a folder named after the movie.

## Preview before you export
- **Play selected part with sound** and **Play whole edit** render a fast preview with the same edits
  (overlays, text, colour, crop, silence cut) and play it in a player window with sound.
  The player is ffplay, which comes with the FFmpeg full build.

## Part number (1, 2, 3 ...)
Two ways:
- **Number inside your own text**: Text tab > **+ Add text**, write your line, for example `Part 1 finding best movie for you`.
  Select only the `1` with the mouse and press **Make selected number = part number**. The `1` becomes `{n}`: the first
  part shows 1, the second 2, the third 3 and so on. **The rest of the text stays exactly the same in every video.**
  If nothing is selected, the first number in the text is used. You can also type `{n}` yourself, anywhere in a text.
- **Only a number**: Text tab > **+ Add part number**.
- The preview shows the number of the part you are looking at. Start from another number with **First part number** in the
  Parts panel (for example 5 gives 5, 6, 7 ...). The number is also used in the output file name and in Auto Short.
- It is a normal text, so font (Hindi fonts too), colour, size, outline, shadow, box, opacity and timing all work, and you
  can drag it with the mouse in the preview.

## Centre a text with one click
Select a text, then:
- **Center left-right** - exactly in the middle of the frame from side to side (the up-down position stays),
- **Center up-down**,
- **Center on screen** - both,
- **Unlock (move freely)** - back to normal. Moving the X / Y sliders or choosing a Position preset also unlocks.
A centred direction stays centred while you drag the text with the mouse. Preview and export are centred the same way.

## Crop the movie, then set the final frame (two separate steps)
Aspect & Crop tab:
- **1. IMPORTED MOVIE - crop it here**: ratio of the picture you imported (for example 1:1 or 4:5), Zoom in, and move
  left-right / up-down. This crops only the movie itself.
- **2. FINAL OUTPUT - the video you export**: the ratio of the finished video (for example 9:16 for shorts), and the
  **Background of the frame**:
  - **Blur background** - a blurred copy of the movie fills the frame (Blur strength slider),
  - **Black bars**,
  - **Solid colour** - pick any colour with Background colour,
  - **Crop (fill frame)** - the movie fills the whole frame and the edges are cut.
- **Movie size in frame %** makes the movie smaller inside the frame (30 - 100 %), and **Movie up-down in frame %** moves it
  up or down (for example move the picture up and leave room for text below). These work with Blur, Black bars and
  Solid colour.
- Example: a 16:9 movie, cropped to 1:1 in step 1, exported as 9:16 in step 2 with a blur or colour background = a tall
  video with the square picture in the middle.
- The preview shows exactly this, and Auto Short uses the same settings.

## Quality and bitrate
- Export tab > **Bitrate mode**:
  - **Exact bitrate (use my number)** (default): the file gets the bitrate you type. 50000 kbps = 50 Mbps, and the file's
    Properties > Details shows about that. The file size is bitrate x length (50 Mbps = about 375 MB per minute).
  - **Quality (bitrate is only a limit)**: constant quality. Simple scenes use far fewer bits than the number, so the
    exported bitrate can be much lower than what you typed.
- Bitrate goes up to 150000 kbps. A higher bitrate cannot add detail that the original movie does not have.
- **Resolution: Original** keeps your movie's own size. Pick 720p / 1080p / 4K only when you need a change.

## Smooth cuts (no flash cuts, no montage)
Too many very fast cuts make a short look cheap, and a low bitrate then makes every cut look blocky. The dialogue cut and
Auto Short therefore have three safeguards (Dialogue tab and Auto Short tab):
- **Shortest clip (s)**, default 1.0: no dialogue piece is shorter than this. A short piece is made longer with the sound
  and picture around it, and pieces that then touch are joined. No more 0.1 - 0.3 second flashes made by the software.
- **Scan the picture** (on in Auto Short, off by default in Simple Edit; it adds some seconds per 2 minutes of movie):
  - parts with **fast-cut montage** (a shot shorter than 0.3 s, or more than 1 picture cut per second) are skipped -
    music and effects over action montage are not dialogue;
  - every start / end of a piece is **moved onto a nearby shot change** of the movie (within 0.5 s), so the cut hides in
    a real cut; a sliver of the previous or next shot at the start / end is cut off. Starts only move inside the
    padding or outwards, so no word is lost.
- The log shows for every short: number of cuts, shortest and average piece.
Tip: if the log says "built-in detector", run **install_ai.bat**. The Silero AI detector knows speech from music and
effects; the built-in one can take loud background sound for speech.

## Export quality
- Export tab > **Quick preset**: *Reels / Shorts - best quality* (1080p = 1080x1920 for 9:16, Exact 12 Mbps),
  *YouTube 1080p* (16 Mbps) and *Small file for WhatsApp* (720p, 3 Mbps). You can still change every value afterwards.
- Social apps (Instagram, YouTube) compress an upload again. The higher the quality you upload (1080x1920 and a high
  bitrate), the better the result after their compression. A 720x1280 file at under 1 Mbps looks soft and blocky,
  especially with fast cuts.

## Dialogue cut (Simple Edit > Dialogue tab)
- Works only on the time range of the ticked parts, not the whole movie, so it is fast.
- Click **EXPORT TICKED PARTS WITH DIALOGUE CLEAN-UP**. For every ticked part the app finds where people are talking
  and **cuts both the picture and the sound** wherever nobody talks. The result is one continuous talking video.
- Each part is analysed right before it is exported, so the first file is ready while the next part is still waiting.
- Speech detection: **Silero AI** (neural network) when installed, otherwise a built-in voice-band detector.
  Speech padding (default 150 ms) and minimum silence (default 300 ms) can be changed in the tab.
- Picture and sound are cut and joined in ONE FFmpeg pass, so they always stay in sync. Every cut has a 20 ms fade.
- Optional: noise reduction (FFmpeg), and text editing with faster-whisper (tick it and list the words to remove).
- Overlay and text times count from the start of the joined clip.

## Notes
- Overlay and text times are measured from the start of each part. When silence is cut, an overlay stays with the
  footage it was placed on; if that footage is cut away, the overlay is cut away too.
- Hindi text needs a Devanagari font such as **Nirmala UI** or **Mangal**.
- The timeline does not play audio; sound is heard in the exported file.
- NVIDIA codecs use the GPU. If the GPU encoder fails, the CPU codec is used automatically.

## Auto Short tab

One movie in, continuous-dialogue shorts out (45 to 59 seconds by default), **one file at a time**.

1. Choose the movie in the Simple Edit tab.
2. Open the Auto Short tab. Choose what to scan: the whole movie, a Start / End range, or only the parts you ticked in
   the Simple Edit tab. Set the minimum / maximum length of a short if you want something other than 45 - 59 s.
3. Press **CREATE AUTO SHORTS**.

What happens:
- The movie is scanned in small chunks (2 minutes at a time), not all at once.
- The AI finds where people are talking. Everything else is cut from the picture and the sound.
- As soon as enough dialogue is found for one short, that short is exported and appears in the list on the right
  (Play / Folder buttons) while the scan of the rest continues. **Stop** ends the run; finished shorts stay.
- A short ends at a natural pause when one exists after the minimum length, otherwise it is filled up to the maximum.
- Colour, Aspect & Crop, Overlay, Text and Export settings come from the Simple Edit tab and are applied to every short.
  Overlay and text times count from the start of each short. A text with Auto-number and `{n}` becomes Part 1, Part 2 ...
- Dialogue left at the end that is shorter than the minimum is not turned into a short (tick "Keep the last short"
  to keep it).

Output goes to `exported_clips/<movie>_auto_short/`.

## Speed
- NVIDIA codecs (default) use the GPU for encoding. Speech detection runs on the CPU and takes a few seconds per 2 minutes
  of movie. Text editing with Whisper is slow on the CPU, so it is off by default.
