import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
import re
from deep_translator import GoogleTranslator
from gtts import gTTS
import tempfile
import os
from yt_dlp import YoutubeDL
import whisper

# ======================== Configuration ========================
st.set_page_config(page_title="AI Voiceover Translator", layout="wide")
st.title("🎙️ Video Voiceover Translator (No Video Download)")
st.markdown("Extract transcript directly from YouTube (or audio from other sites), translate, and play video with new voiceover.")

supported_languages = {
    "Hindi": "hi",
    "Chinese (Simplified)": "zh-cn",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Russian": "ru",
    "Italian": "it",
    "Portuguese": "pt",
    "English": "en",
}

def get_youtube_video_id(url):
    """Extract video ID from YouTube URL"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([\w-]+)',
        r'(?:youtu\.be\/)([\w-]+)',
        r'(?:youtube\.com\/embed\/)([\w-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_transcript(video_id):
    """Fetch transcript using youtube-transcript-api (no download)"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Try to get manually created or auto-generated captions
        transcript = transcript_list.find_generated_transcript(['en'])
        if not transcript:
            transcript = transcript_list.find_manually_created_transcript(['en'])
        formatter = TextFormatter()
        text = formatter.format_transcript(transcript.fetch())
        return text
    except Exception as e:
        st.warning(f"Could not fetch transcript from YouTube: {str(e)}")
        return None

def extract_audio_only(video_url):
    """Download only audio stream (small) from any site using yt-dlp"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = tmp.name
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': audio_path.replace('.mp3', '.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            # yt-dlp returns path with extension, adjust
            base = audio_path.replace('.mp3', '')
            actual_path = base + '.mp3'
            if os.path.exists(actual_path):
                return actual_path
            return None
    except Exception as e:
        st.error(f"Audio download failed: {str(e)}")
        return None

def transcribe_audio(audio_path):
    """Transcribe using Whisper (local, requires audio download)"""
    try:
        model = whisper.load_model("base")
        result = model.transcribe(audio_path)
        return result["text"]
    except Exception as e:
        st.error(f"Transcription failed: {str(e)}")
        return None

#def translate_text(text, target_code):
#    translator = Translator()
#    return translator.translate(text, dest=target_code).text


def translate_text(text, target_language_code):
    """Translate text using deep-translator (Google Translate backend)"""
    try:
        translator = GoogleTranslator(source='auto', target=target_language_code)
        translation = translator.translate(text)
        return translation
    except Exception as e:
        st.error(f"Translation failed: {str(e)}")
        return None

def generate_tts(text, lang_code):
    """Generate speech and return path to mp3 file"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tts_path = tmp.name
    tts = gTTS(text=text, lang=lang_code, slow=False)
    tts.save(tts_path)
    return tts_path

# ======================== Main UI ========================
with st.sidebar:
    st.header("Settings")
    video_url = st.text_input("🔗 Video URL", placeholder="https://youtube.com/watch?v=... or https://twitter.com/...")
    target_lang = st.selectbox("🎧 Target Voiceover Language", list(supported_languages.keys()))
    process = st.button("✨ Translate Voiceover", type="primary", use_container_width=True)

if process and video_url:
    # Step 1: Extract transcript
    transcript = None
    video_id = get_youtube_video_id(video_url)

    with st.status("Processing...", expanded=True) as status:
        if video_id:
            status.update(label="📝 Fetching YouTube transcript...")
            transcript = get_youtube_transcript(video_id)
            if transcript:
                st.success("✅ Transcript extracted directly from YouTube (no download)")

        # If not YouTube or transcript failed, fallback to audio-only download + Whisper
        if not transcript:
            status.update(label="🎵 Downloading audio only (required for transcription)...")
            audio_file = extract_audio_only(video_url)
            if audio_file:
                status.update(label="🗣️ Transcribing audio with Whisper...")
                transcript = transcribe_audio(audio_file)
                os.unlink(audio_file)  # clean up
                if transcript:
                    st.success("✅ Transcript generated from audio (audio file deleted)")

        if not transcript:
            st.error("Could not extract any transcript. Only YouTube (with captions) and sites with clear audio are supported.")
            st.stop()

        # Step 2: Translate
        status.update(label="🌍 Translating...")
        target_code = supported_languages[target_lang]
        translated = translate_text(transcript, target_code)

        # Step 3: Generate TTS
        status.update(label="🗣️ Generating new voiceover...")
        tts_file = generate_tts(translated, target_code)

        # Step 4: Prepare player HTML (video + audio overlay)
        status.update(label="🎬 Building player...")

        # For YouTube, we can embed the original video with ?mute=1
        # For other platforms, we use the original URL inside <video> tag if possible, else link.
        if "youtube.com" in video_url or "youtu.be" in video_url:
            embed_url = video_url.replace("watch?v=", "embed/").split("&")[0]
            video_html = f"""
            <iframe width="100%" height="500" src="{embed_url}?autoplay=0&mute=1" frameborder="0" allowfullscreen></iframe>
            """
        else:
            # Fallback: try to use native <video> if URL points to direct video file, else show link
            video_html = f"""
            <video width="100%" height="500" controls muted>
                <source src="{video_url}" type="video/mp4">
                Your browser does not support video.
            </video>
            <p><small>If video does not play, the URL may not be a direct video file.</small></p>
            """

        # Convert TTS to base64 for inline audio
        import base64
        with open(tts_file, "rb") as f:
            tts_base64 = base64.b64encode(f.read()).decode()
        os.unlink(tts_file)

        # JavaScript to play the new audio while video is muted
        player_html = f"""
        <div id="voiceover-player">
            {video_html}
            <audio id="tts-audio" src="data:audio/mp3;base64,{tts_base64}" preload="auto"></audio>
            <div style="margin-top: 1rem; display: flex; gap: 1rem; justify-content: center;">
                <button onclick="document.getElementById('tts-audio').play()" style="background:#4CAF50; color:white; padding:0.5rem 1rem; border:none; border-radius:8px;">▶ Play Translated Voiceover</button>
                <button onclick="document.getElementById('tts-audio').pause()" style="background:#f44336; color:white; padding:0.5rem 1rem; border:none; border-radius:8px;">⏸ Pause</button>
                <label style="margin-left: 1rem;">🔊 Volume: <input type="range" id="volume" min="0" max="1" step="0.1" value="1" onchange="document.getElementById('tts-audio').volume=this.value"></label>
            </div>
            <p style="margin-top: 1rem; font-style: italic;">The original video is muted. Use the button above to hear the translated voiceover.</p>
        </div>
        <hr>
        <h3>Translated Transcript</h3>
        <div style="background:#f0f2f6; padding:1rem; border-radius:12px;">
            {translated.replace(chr(10), '<br>')}
        </div>
        """

        status.update(label="✅ Ready", state="complete")

    st.markdown(player_html, unsafe_allow_html=True)

    # Show original transcript in expander
    with st.expander("📄 Original Transcript (English/Detected)"):
        st.text(transcript[:2000] + ("..." if len(transcript) > 2000 else ""))

else:
    st.info("Enter a video URL and select a language, then click 'Translate Voiceover'.")

st.markdown("---")
st.caption("**How it works**: For YouTube, the app grabs existing captions (no download). For other sites, it downloads only the **audio** (a few MB), transcribes it with Whisper, then deletes the audio. The new voiceover is played alongside the original video — no video file is ever stored on the server.")