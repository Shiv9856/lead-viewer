import os
import requests
import pandas as pd
import shutil
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# CONFIG
# ==============================================================================

ELEVENLABS_API_KEY  = "sk_8c20c45f3dee90585a1eb12af0357ccb93fa40da4cf512a2"
UPLOAD_FOLDER       = "./upload"
MODEL_ID            = "scribe_v1"
NUM_SPEAKERS        = 2
LANGUAGE_CODE       = "hi"
SLEEP_AFTER_JOB     = 3

CSV_FILE = r"c:\Users\bbank\Downloads\view\transcript\ab.csv"
OUTPUT_CSV          = "output.csv"
AUDIO_COLUMN        = "call_audio"

MAX_WORKERS         = 5
SAVE_INTERVAL       = 5

# ==============================================================================
# SETUP
# ==============================================================================

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
warnings.filterwarnings("ignore", category=FutureWarning)

BLOCKED_URL_PATTERNS = [
    "command=downloadVoiceLog",
    "ameyowebaccess",
    "ameyoemerge",
]

def is_downloadable_url(url: str) -> bool:
    return not any(pattern in url for pattern in BLOCKED_URL_PATTERNS)

# ==============================================================================
# TRANSCRIPTION
# ==============================================================================

def transcribe_from_url(file_url: str, unique_id: str) -> str:
    subdir = os.path.join(UPLOAD_FOLDER, unique_id)
    os.makedirs(subdir, exist_ok=True)
    local_path = os.path.join(subdir, "audio.mp3")

    try:
        r = requests.get(file_url, stream=True, timeout=60)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")

    api_url = "https://api.elevenlabs.io/v1/speech-to-text"
    headers = {"xi-api-key": ELEVENLABS_API_KEY}
    with open(local_path, "rb") as audio_file:
        response = requests.post(
            api_url,
            headers=headers,
            files={"file": audio_file},
            data={
                "model_id": MODEL_ID,
                "language_code": LANGUAGE_CODE,
                "diarize": True,
                "num_speakers": NUM_SPEAKERS,
                "timestamps_granularity": "word",
                "tag_audio_events": True,
            },
            timeout=300,
        )

    if response.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")

    try:
        data = response.json()
    except Exception as e:
        raise RuntimeError(f"Could not parse ElevenLabs response: {e}")

    entries = []
    for word in data.get("words", []):
        speaker = word.get("speaker_id", "Unknown")
        text = word.get("text", "").strip()
        if not text:
            continue
        if entries and entries[-1]["speaker_id"] == speaker:
            entries[-1]["text"] += f" {text}"
        else:
            entries.append({"speaker_id": speaker, "text": text})

    transcript = "\n".join(f"{e['speaker_id']}: {e['text']}" for e in entries)

    shutil.rmtree(subdir, ignore_errors=True)
    time.sleep(SLEEP_AFTER_JOB)
    return transcript

# ==============================================================================
# ROW PROCESSOR
# ==============================================================================

def process_row(row_idx: int, row: pd.Series) -> tuple:
    url = str(row.get(AUDIO_COLUMN, "")).strip()

    if not url or url.lower() == "nan":
        print(f"[Row {row_idx}] No URL")
        return row_idx, url, "No audio URL provided"

    if not is_downloadable_url(url):
        msg = (
            "Skipped: Ameyo internal URL requires a live authenticated session. "
            "Export the recording as a direct public MP3 link and re-run."
        )
        print(f"[Row {row_idx}] Skipped (Ameyo auth URL)")
        return row_idx, url, msg

    try:
        transcript = transcribe_from_url(url, str(row_idx))
    except Exception as e:
        transcript = f"Transcription failed: {e}"
        print(f"[Row {row_idx}] Transcription error: {e}")

    print(f"[Row {row_idx}] Done")
    return row_idx, url, transcript

# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == "__main__":
    df = pd.read_csv(CSV_FILE)

    if AUDIO_COLUMN not in df.columns:
        raise ValueError(
            f"CSV must contain a column named '{AUDIO_COLUMN}'. Found: {list(df.columns)}"
        )

    if "transcript" not in df.columns:
        df["transcript"] = pd.Series(dtype="object")
    else:
        df["transcript"] = df["transcript"].astype("object")

    # Resume support
    if os.path.exists(OUTPUT_CSV):
        df_out = pd.read_csv(OUTPUT_CSV)
        if len(df_out) == len(df) and "transcript" in df_out.columns:
            df["transcript"] = df_out["transcript"].astype("object")
            print(f"Resuming from {OUTPUT_CSV}")

    to_process = [
        i for i, val in enumerate(df["transcript"])
        if pd.isna(val) or str(val).strip() == ""
    ]

    ameyo_count = sum(
        1 for val in df[AUDIO_COLUMN]
        if pd.notna(val) and str(val).strip() and not is_downloadable_url(str(val))
    )

    print(f"\nTotal rows      : {len(df)}")
    print(f"Ameyo URLs      : {ameyo_count}  (skipped - require auth)")
    print(f"Rows to process : {len(to_process)}\n")

    if not to_process:
        print("Nothing to process. Saving output.")
    else:
        completed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(process_row, idx, df.iloc[idx]): idx
                for idx in to_process
            }
            for future in as_completed(futures):
                try:
                    row_idx, url, transcript = future.result()
                    df.at[row_idx, AUDIO_COLUMN] = url
                    df.at[row_idx, "transcript"] = transcript
                    completed += 1
                    if completed % SAVE_INTERVAL == 0:
                        df.to_csv(OUTPUT_CSV, index=False)
                        print(f"  Progress saved ({completed}/{len(to_process)})")
                except Exception as e:
                    print(f"Unexpected error for row {futures[future]}: {e}")

    # Save with transcript column last for easy reading
    other_cols = [c for c in df.columns if c not in [AUDIO_COLUMN, "transcript"]]
    df[other_cols + [AUDIO_COLUMN, "transcript"]].to_csv(OUTPUT_CSV, index=False)
    print(f"\nDone! Output saved to: {OUTPUT_CSV}")

    for item in os.listdir(UPLOAD_FOLDER):
        item_path = os.path.join(UPLOAD_FOLDER, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path, ignore_errors=True)
    print("Upload folder cleaned up.")