"""Call audio → speaker-labelled turns.

1. Groq Whisper (`whisper-large-v3-turbo`, verbose_json segments). Accepts an uploaded file or a recording URL
   (MCube gives one); Groq fetches the URL itself, so long recordings never pass through our 4.5 MB request limit.
2. Whisper has no speaker labels, so a strict structured LLM call assigns a speaker and side to every segment from
   the participant list. Labels are marked `speaker_inferred` and are editable in the preview.
"""
import os

from contracts import Participant, SpeakerLabels, Turn

from . import llm
from .errors import InvalidInput, TranscriptionFailed

STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # Groq free tier file limit
SEGMENTS_PER_CALL = 120              # keeps each labelling request inside the Groq free-tier token budget


def _stamp(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


async def transcribe(audio: bytes | None, file_name: str | None, url: str | None) -> list[dict]:
    """Returns [{start, end, text}] segments."""
    from groq import AsyncGroq
    if not audio and not url:
        raise InvalidInput("Upload an audio file or give a recording URL.")
    if audio and len(audio) > MAX_UPLOAD_BYTES:
        raise InvalidInput("Audio is over 25 MB. Compress it (mono 16 kHz mp3) or give the recording URL.")
    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
    try:
        kwargs = dict(model=STT_MODEL, response_format="verbose_json", timestamp_granularities=["segment"])
        if audio:
            r = await client.audio.transcriptions.create(file=(file_name or "call.mp3", audio), **kwargs)
        else:
            r = await client.audio.transcriptions.create(url=url, **kwargs)
    except Exception as e:
        raise TranscriptionFailed(f"Speech-to-text failed: {str(e)[:200]}. Paste the transcript instead.") from e
    data = r.to_dict() if hasattr(r, "to_dict") else dict(r)
    segments = [dict(start=s.get("start", 0), end=s.get("end", 0), text=(s.get("text") or "").strip())
                for s in data.get("segments") or []]
    segments = [s for s in segments if s["text"]]
    if not segments and (data.get("text") or "").strip():
        segments = [dict(start=0, end=0, text=data["text"].strip())]
    if not segments:
        raise TranscriptionFailed("No speech found in the recording.")
    return segments


async def label_speakers(segments: list[dict], participants: list[Participant], exec_name: str) -> list[Turn]:
    """Assign a speaker to every segment, then merge consecutive segments of the same speaker into turns."""
    people = [f"- {p.name} ({p.role or 'role unknown'}), {'our side' if p.side == 'ours' else 'customer side'}"
              for p in participants] or ["(no participant list given)"]
    instructions = (
        "You label a sales call transcript. Our salesperson is " + exec_name + ". Known participants:\n"
        + "\n".join(people) +
        "\nFor EVERY segment return its index, the speaker's name (from the list when you can tell, otherwise "
        "'Salesperson' or 'Customer') and side: 'ours' for our salesperson, 'customer' for the buyer's people, "
        "'unknown' only if it truly cannot be told. Use content cues: who asks discovery questions, who talks "
        "about their own company's problems, who quotes prices.")
    labels: dict[int, tuple[str, str]] = {}
    for start in range(0, len(segments), SEGMENTS_PER_CALL):
        chunk = segments[start:start + SEGMENTS_PER_CALL]
        prompt = "\n".join(f"{start + i}. [{_stamp(s['start'])}] {s['text']}" for i, s in enumerate(chunk))
        out = await llm.structured(SpeakerLabels, instructions, prompt, max_tokens=4000)
        for t in out.turns:
            labels[t.segment] = (t.speaker, t.side)
    turns: list[Turn] = []
    for i, s in enumerate(segments):
        speaker, side = labels.get(i, ("Unknown", "unknown"))
        if turns and turns[-1].speaker == speaker and turns[-1].side == side:
            turns[-1].text += " " + s["text"]
        else:
            turns.append(Turn(speaker=speaker, side=side, text=s["text"], at=_stamp(s["start"]),
                              speaker_inferred=True))
    return turns
